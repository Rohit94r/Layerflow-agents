"""Versioned prompts (plan §11.6). Files under prompts/ are the baseline; Settings edits are saved as new
versions in prompt_versions (never in place), so any change can be compared and rolled back."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import PromptVersion

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass
class PromptRef:
    key: str
    version: str
    body: str
    source: str  # file | db
    id: str | None = None

    @property
    def tag(self) -> str:
        return f"{self.key}@{self.version}"


def _path_for(key: str) -> Path:
    root = get_settings().prompts_dir
    if key == "style/banned":
        return root / "style" / "banned.txt"
    return root / f"{key}.md"


@lru_cache(maxsize=128)
def _read_file(path: str, mtime: float) -> tuple[str, str]:
    text = Path(path).read_text(encoding="utf-8")
    version = "1.0.0"
    m = _FRONT.match(text)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
            version = str(meta.get("version", version))
        except yaml.YAMLError:
            pass
        text = text[m.end() :]
    return text.strip(), version


def file_prompt(key: str) -> PromptRef | None:
    path = _path_for(key)
    if not path.exists():
        return None
    body, version = _read_file(str(path), path.stat().st_mtime)
    return PromptRef(key=key, version=version, body=body, source="file")


def list_keys() -> list[str]:
    root = get_settings().prompts_dir
    keys = []
    if root.exists():
        for p in sorted(root.rglob("*.md")):
            keys.append(p.relative_to(root).with_suffix("").as_posix())
        if (root / "style" / "banned.txt").exists():
            keys.append("style/banned")
    return sorted(set(keys))


async def get_prompt(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> PromptRef:
    row = (
        await db.execute(
            select(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key, PromptVersion.active.is_(True))
            .order_by(PromptVersion.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is not None:
        return PromptRef(key=key, version=row.version, body=row.body, source="db", id=str(row.id))
    ref = file_prompt(key)
    if ref is None:
        return PromptRef(key=key, version="0.0.0", body="", source="missing")
    return ref


def bump(version: str) -> str:
    m = _SEMVER.match(version or "")
    if not m:
        return "1.0.1"
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


async def save_version(
    db: AsyncSession, tenant_id: uuid.UUID, key: str, body: str, *, user_id: uuid.UUID | None, note: str | None
) -> PromptVersion:
    current = await get_prompt(db, tenant_id, key)
    existing = (
        await db.execute(select(PromptVersion.version).where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key))
    ).scalars().all()
    candidates = [current.version, *existing]

    def _key(v: str) -> tuple[int, int, int]:
        m = _SEMVER.match(v)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)  # type: ignore[return-value]

    new_version = bump(max(candidates, key=_key))
    await db.execute(
        update(PromptVersion).where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key).values(active=False)
    )
    row = PromptVersion(tenant_id=tenant_id, key=key, version=new_version, body=body.strip(), note=note, active=True, created_by=user_id)
    db.add(row)
    await db.flush()
    return row


async def activate(db: AsyncSession, tenant_id: uuid.UUID, key: str, version_id: str | None) -> None:
    """Activate a DB version, or fall back to the file baseline when version_id is 'file'."""
    await db.execute(
        update(PromptVersion).where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key).values(active=False)
    )
    if version_id and version_id != "file":
        await db.execute(
            update(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key, PromptVersion.id == uuid.UUID(version_id))
            .values(active=True)
        )
    await db.flush()


async def versions(db: AsyncSession, tenant_id: uuid.UUID, key: str) -> list[dict]:
    rows = (
        await db.execute(
            select(PromptVersion)
            .where(PromptVersion.tenant_id == tenant_id, PromptVersion.key == key)
            .order_by(PromptVersion.created_at.desc())
        )
    ).scalars().all()
    out = [
        {
            "id": str(r.id),
            "version": r.version,
            "body": r.body,
            "note": r.note,
            "source": "db",
            "active": r.active,
            "created_at": r.created_at.isoformat(),
            "created_by": str(r.created_by) if r.created_by else None,
        }
        for r in rows
    ]
    base = file_prompt(key)
    if base:
        out.append(
            {
                "id": "file",
                "version": base.version,
                "body": base.body,
                "note": "Baseline from repository",
                "source": "file",
                "active": not any(r.active for r in rows),
                "created_at": None,
                "created_by": None,
            }
        )
    return out


async def compose_system(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    agent: str,
    category: str | None = None,
    include_persona: bool = True,
    include_style: bool = True,
    extra: str | None = None,
) -> tuple[str, dict[str, str]]:
    """system/base + persona + style + category playbook + agent task. Returns text and the versions used."""
    parts: list[str] = []
    used: dict[str, str] = {}

    async def add(key: str, heading: str | None = None) -> None:
        ref = await get_prompt(db, tenant_id, key)
        if ref.body:
            parts.append(f"## {heading}\n{ref.body}" if heading else ref.body)
            used[key] = ref.version

    await add("system/base")
    if include_persona:
        await add("persona/ten", "PERSONA")
    if include_style:
        await add("style/structure", "STRUCTURE RULES")
        await add("style/lexicon", "LEXICON")
        banned = await get_prompt(db, tenant_id, "style/banned")
        phrases = [ln.strip() for ln in banned.body.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        if phrases:
            parts.append("## BANNED PHRASES (never use)\n" + "; ".join(phrases))
            used["style/banned"] = banned.version
    if category:
        await add(f"categories/{category}", "CATEGORY PLAYBOOK")
    await add(f"agents/{agent}", "YOUR TASK")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts), used


def parse_banned(body: str) -> list[str]:
    return [ln.strip().lower() for ln in (body or "").splitlines() if ln.strip() and not ln.strip().startswith("#")]


async def banned_list(db: AsyncSession, tenant_id: uuid.UUID) -> list[str]:
    """The tenant's active banned-phrase list (DB version if edited in Settings, else the file)."""
    ref = await get_prompt(db, tenant_id, "style/banned")
    return parse_banned(ref.body)


def versions_tag(used: dict[str, str]) -> str:
    return ",".join(f"{k}@{v}" for k, v in sorted(used.items()))
