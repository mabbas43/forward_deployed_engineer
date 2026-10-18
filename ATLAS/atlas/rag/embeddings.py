"""P2 — embeddings. Online: OpenAI embeddings. Offline: a deterministic hashing embedder.

The hashing embedder (words + character trigrams + a small synonym map, hashed into 768 dims) is *not*
semantic like a real model — but it behaves like one structurally, so hybrid fusion, reranking and the
golden-set eval all work and show real deltas. Swap in real embeddings and rerun the eval to see the gap.
"""

import hashlib
import re
from functools import lru_cache

import numpy as np
from langchain_core.embeddings import Embeddings

from atlas.config import settings
from atlas.logging import get_logger

log = get_logger()
DIMS = 768

SYNONYMS = {
    "login": "signin", "logon": "signin", "sign": "signin", "log": "signin",
    "locked": "lockout", "lockout": "lockout", "unlock": "lockout",
    "vacation": "leave", "holiday": "leave", "holidays": "leave", "urlaub": "leave", "days": "leave",
    "2fa": "mfa", "authenticator": "mfa", "token": "mfa", "otp": "mfa",
    "vpn": "remote", "globalprotect": "remote", "tunnel": "remote", "home": "remote",
    "invoice": "billing", "invoices": "billing", "charged": "billing", "payment": "billing", "paid": "billing",
    "refund": "billing", "twice": "duplicate", "double": "duplicate",
    "password": "credential", "passwort": "credential", "reset": "credential",
    "crash": "failure", "crashes": "failure", "bluescreen": "failure", "blue": "failure", "error": "failure",
    "phishing": "security", "clicked": "security", "breach": "security", "malware": "security",
    "abroad": "travel", "austria": "travel", "country": "travel", "expenses": "reimburse", "expense": "reimburse",
}
_TOKEN = re.compile(r"[a-z0-9äöüß][a-z0-9äöüß\-]*")


def _h(s: str) -> tuple[int, float]:
    d = hashlib.md5(s.encode()).digest()
    return int.from_bytes(d[:4], "little") % DIMS, 1.0 if d[4] & 1 else -1.0


def hash_embed(text: str) -> list[float]:
    v = np.zeros(DIMS, dtype=np.float32)
    toks = _TOKEN.findall(text.lower())
    for t in toks:
        i, s = _h("w:" + t)
        v[i] += s * 1.0
        if t in SYNONYMS:
            i, s = _h("c:" + SYNONYMS[t])
            v[i] += s * 1.5
        for k in range(max(1, len(t) - 2)):
            i, s = _h("g:" + t[k : k + 3])
            v[i] += s * 0.3
    n = float(np.linalg.norm(v))
    return (v / n).tolist() if n else v.tolist()


class HashingEmbeddings(Embeddings):
    model = "offline-hashing"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [hash_embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return hash_embed(text)


@lru_cache
def get_embeddings() -> Embeddings:
    if settings.online and settings.openai_api_key:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)
    return HashingEmbeddings()


def embed(texts: list[str]) -> np.ndarray:
    """Normalized embedding matrix. Shared by RAG, router, tool selection and the semantic cache."""
    m = np.asarray(get_embeddings().embed_documents(texts), dtype=np.float32)
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1
    return m / n


def cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
