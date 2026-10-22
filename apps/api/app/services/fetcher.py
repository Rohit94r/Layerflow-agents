"""Polite, safe HTTP fetcher (plan §12.1).

- SSRF guard: only http(s); private, loopback, link-local, reserved and multicast addresses are refused, and the
  check is repeated on every redirect hop.
- robots.txt honoured for page fetches (feeds/APIs published for syndication are exempt by the caller).
- <=1 request/second/domain, 4 concurrent globally, 3 redirects max, 15 s timeout, 3 MB cap.
- 7-day on-disk cache keyed by URL hash; 401/403 recorded and never retried aggressively.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from charset_normalizer import from_bytes

from app.core.config import Settings, get_settings

DEFAULT_ACCEPT = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/json",
    "text/plain",
)
BLOCKED_HOSTS = ("localhost", "localhost.localdomain", "metadata.google.internal", "metadata")
Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchError(Exception):
    def __init__(self, message: str, *, status: int | None = None, retry_after_s: float | None = None, kind: str = "error") -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_s = retry_after_s
        self.kind = kind  # blocked | robots | ssrf | too_large | content_type | http | network | rate_limited


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    size: int
    elapsed_ms: int
    from_cache: bool = False
    headers: dict[str, str] = field(default_factory=dict)


async def default_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


class Fetcher:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
        cache_dir: Path | None = None,
        min_interval_s: float | None = None,
    ) -> None:
        self.s = settings or get_settings()
        self.resolver = resolver or default_resolver
        self.cache_dir = Path(cache_dir or self.s.fetch_cache_dir)
        self.min_interval_s = self.s.fetch_min_interval_s if min_interval_s is None else min_interval_s
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(self.s.fetch_timeout_s, connect=10.0),
            follow_redirects=False,
            headers={
                "User-Agent": self.s.fetch_user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
                "Accept-Language": "en;q=0.9",
            },
            http2=transport is None,
        )
        self._global = asyncio.Semaphore(self.s.fetch_global_concurrency)
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._domain_last: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Fetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ---- guards ----
    async def check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise FetchError(f"Scheme '{parts.scheme}' not allowed", kind="ssrf")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host or host in BLOCKED_HOSTS or host.endswith((".local", ".internal", ".localhost")):
            raise FetchError(f"Host '{host}' not allowed", kind="ssrf")
        try:
            ipaddress.ip_address(host)
            ips = [host]
        except ValueError:
            try:
                ips = await self.resolver(host, parts.port or (443 if parts.scheme == "https" else 80))
            except OSError as exc:
                raise FetchError(f"DNS lookup failed for {host}", kind="network") from exc
        if not ips or not all(_is_public_ip(ip) for ip in ips):
            raise FetchError(f"Host '{host}' resolves to a non-public address", kind="ssrf")

    async def _rate_limit(self, host: str) -> asyncio.Lock:
        lock = self._domain_locks.setdefault(host, asyncio.Lock())
        await lock.acquire()
        wait = self._domain_last.get(host, 0) + self.min_interval_s - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        return lock

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = None
            try:
                res = await self._raw_get(origin + "/robots.txt", accept=("text/plain", "text/html", "application/octet-stream"), max_bytes=512_000)
                if res.status == 200:
                    parser = RobotFileParser()
                    parser.parse(res.text.splitlines())
            except FetchError:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return True
        agent = self.s.fetch_user_agent.split("/")[0]
        return parser.can_fetch(agent, url)

    # ---- cache ----
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    def _cache_get(self, url: str) -> FetchResult | None:
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(data["fetched_at"])
            if datetime.now(UTC) - fetched > timedelta(days=self.s.fetch_cache_days):
                return None
            return FetchResult(
                url=url,
                final_url=data["final_url"],
                status=data["status"],
                content_type=data["content_type"],
                text=data["text"],
                size=len(data["text"]),
                elapsed_ms=0,
                from_cache=True,
            )
        except (OSError, ValueError, KeyError):
            return None

    def _cache_put(self, url: str, res: FetchResult) -> None:
        path = self._cache_path(url)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "final_url": res.final_url,
                        "status": res.status,
                        "content_type": res.content_type,
                        "text": res.text,
                        "fetched_at": datetime.now(UTC).isoformat(),
                    }
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            pass

    # ---- core ----
    async def _raw_get(
        self,
        url: str,
        *,
        accept: tuple[str, ...] = DEFAULT_ACCEPT,
        max_bytes: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        max_bytes = max_bytes or self.s.fetch_max_bytes
        current = url
        started = time.perf_counter()
        for _hop in range(4):
            await self.check_url(current)
            host = (urlsplit(current).hostname or "").lower()
            async with self._global:
                lock = await self._rate_limit(host)
                try:
                    try:
                        async with self._client.stream("GET", current, headers=headers) as resp:
                            if resp.is_redirect:
                                location = resp.headers.get("location")
                                if not location:
                                    raise FetchError("Redirect without location", status=resp.status_code, kind="http")
                                current = urljoin(current, location)
                                continue
                            ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                            status = resp.status_code
                            if status in (401, 403):
                                raise FetchError(f"Access denied ({status})", status=status, kind="blocked")
                            if status in (429, 503):
                                retry_after = resp.headers.get("retry-after")
                                ra = float(retry_after) if retry_after and retry_after.isdigit() else 120.0
                                raise FetchError(f"Rate limited ({status})", status=status, retry_after_s=ra, kind="rate_limited")
                            if status >= 400:
                                raise FetchError(f"HTTP {status}", status=status, kind="http")
                            if ctype and not any(ctype.startswith(a) for a in accept):
                                raise FetchError(f"Content type '{ctype}' not allowed", status=status, kind="content_type")
                            chunks: list[bytes] = []
                            size = 0
                            async for chunk in resp.aiter_bytes():
                                size += len(chunk)
                                if size > max_bytes:
                                    raise FetchError(f"Response larger than {max_bytes} bytes", status=status, kind="too_large")
                                chunks.append(chunk)
                            body = b"".join(chunks)
                            text = self._decode(body, resp.encoding if resp.charset_encoding else None)
                            return FetchResult(
                                url=url,
                                final_url=str(resp.url),
                                status=status,
                                content_type=ctype,
                                text=text,
                                size=size,
                                elapsed_ms=int((time.perf_counter() - started) * 1000),
                                headers={k.lower(): v for k, v in resp.headers.items() if k.lower() in ("last-modified", "etag", "content-type")},
                            )
                    except httpx.TimeoutException as exc:
                        raise FetchError("Timed out", kind="network") from exc
                    except httpx.HTTPError as exc:
                        raise FetchError(f"Network error: {exc.__class__.__name__}", kind="network") from exc
                finally:
                    self._domain_last[host] = time.monotonic()
                    lock.release()
        raise FetchError("Too many redirects", kind="http")

    @staticmethod
    def _decode(body: bytes, declared: str | None) -> str:
        if declared:
            try:
                return body.decode(declared)
            except (LookupError, UnicodeDecodeError):
                pass
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            best = from_bytes(body).best()
            return str(best) if best else body.decode("latin-1", "replace")

    async def get(
        self,
        url: str,
        *,
        respect_robots: bool = True,
        use_cache: bool = True,
        accept: tuple[str, ...] = DEFAULT_ACCEPT,
        max_bytes: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        if use_cache:
            cached = self._cache_get(url)
            if cached:
                return cached
        if respect_robots and not await self.allowed_by_robots(url):
            raise FetchError("Disallowed by robots.txt", kind="robots")
        res = await self._raw_get(url, accept=accept, max_bytes=max_bytes, headers=headers)
        if use_cache and res.status == 200:
            self._cache_put(url, res)
        return res
