"""Three-layer dedupe (plan §10.2): exact canonical URL -> 64-bit SimHash title fingerprint (Hamming <= 3)
-> semantic similarity (embeddings when available, TF-IDF cosine otherwise)."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

from app.services.text import STOPWORDS, ascii_fold

SIMHASH_MAX_DISTANCE = 3
EMBED_THRESHOLD = 0.92
TFIDF_THRESHOLD = 0.62


def _title_tokens(text: str) -> list[str]:
    t = ascii_fold(text).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    # Drop publisher suffixes like " - Reuters" / " | Mint"
    return [w for w in t.split() if w not in STOPWORDS and len(w) > 1]


def strip_publisher_suffix(title: str) -> str:
    return re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", title.strip())


def simhash64(text: str) -> int:
    toks = _title_tokens(strip_publisher_suffix(text))
    feats = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False)]
    if not feats:
        return 0
    v = [0] * 64
    for feat in feats:
        h = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if v[i] > 0:
            out |= 1 << i
    return out


def fingerprint(text: str) -> str:
    return f"{simhash64(text):016x}"


def hamming(a: int | str, b: int | str) -> int:
    ai = int(a, 16) if isinstance(a, str) else a
    bi = int(b, 16) if isinstance(b, str) else b
    return (ai ^ bi).bit_count()


def is_title_duplicate(fp_a: str, fp_b: str) -> bool:
    if fp_a == "0" * 16 or fp_b == "0" * 16:
        return False
    return hamming(fp_a, fp_b) <= SIMHASH_MAX_DISTANCE


class TfidfIndex:
    """Tiny in-memory TF-IDF for similarity on short texts; no external service needed."""

    def __init__(self, docs: Sequence[str]) -> None:
        self.tokens = [_title_tokens(d) for d in docs]
        df: Counter[str] = Counter()
        for toks in self.tokens:
            df.update(set(toks))
        n = max(1, len(docs))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors = [self._vec(t) for t in self.tokens]

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        vec = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        return {t: x / norm for t, x in vec.items()}

    def vector(self, text: str) -> dict[str, float]:
        return self._vec(_title_tokens(text))

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())


def cosine_dense(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def are_duplicates(title_a: str, title_b: str, *, summary_a: str = "", summary_b: str = "") -> bool:
    """Pairwise decision used by tests and the labelled-set benchmark."""
    if is_title_duplicate(fingerprint(title_a), fingerprint(title_b)):
        return True
    idx = TfidfIndex([f"{title_a} {summary_a}", f"{title_b} {summary_b}"])
    return TfidfIndex.cosine(idx.vectors[0], idx.vectors[1]) >= TFIDF_THRESHOLD
