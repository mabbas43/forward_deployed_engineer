"""P2 — thin local stores: vectors, parents, manifest.

Production swaps these for pgvector/Qdrant/OpenSearch (vectors), Postgres/Redis (parents) and a table (manifest).
The interfaces are what matter: add/search with filters *inside* the search, get-by-id, purge-by-source.
"""

import json
from pathlib import Path

import numpy as np

from atlas.config import settings


class VectorStore:
    """Brute-force cosine search over a numpy matrix. Fine to ~100k chunks; then use a real index."""

    def __init__(self, path: Path):
        self.path = path
        self.ids: list[str] = []
        self.texts: dict[str, str] = {}
        self.metas: dict[str, dict] = {}
        self._vecs: list[list[float]] = []
        self._mat: np.ndarray | None = None
        if path.exists():
            data = json.loads(path.read_text())
            self.ids, self.texts, self.metas, self._vecs = data["ids"], data["texts"], data["metas"], data["vecs"]

    def __len__(self) -> int:
        return len(self.ids)

    def add(self, id_: str, text: str, meta: dict, vec: list[float]) -> bool:
        if id_ in self.texts:  # same content → same id → no duplicate. Idempotency for free.
            return False
        self.ids.append(id_)
        self.texts[id_] = text
        self.metas[id_] = meta
        self._vecs.append(list(map(float, vec)))
        self._mat = None
        return True

    def purge(self, source: str) -> int:
        keep = [i for i, id_ in enumerate(self.ids) if self.metas[id_]["source"] != source]
        removed = len(self.ids) - len(keep)
        keep_set = set(keep)
        for id_ in [self.ids[i] for i in range(len(self.ids)) if i not in keep_set]:
            self.texts.pop(id_)
            self.metas.pop(id_)
        self.ids = [self.ids[i] for i in keep]
        self._vecs = [self._vecs[i] for i in keep]
        self._mat = None
        return removed

    @staticmethod
    def _match(meta: dict, flt: dict) -> bool:
        for k, v in flt.items():
            if isinstance(v, (list, set, tuple)):
                if meta.get(k) not in v:
                    return False
            elif meta.get(k) != v:
                return False
        return True

    def search(self, qvec: np.ndarray, k: int, flt: dict) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        if self._mat is None:
            self._mat = np.asarray(self._vecs, dtype=np.float32)
        mask = np.array([self._match(self.metas[i], flt) for i in self.ids])
        if not mask.any():
            return []
        scores = self._mat @ qvec.astype(np.float32)
        scores[~mask] = -np.inf  # filter INSIDE the search — post-filtering a top-k can return nothing
        top = np.argsort(-scores)[:k]
        return [(self.ids[i], float(scores[i])) for i in top if np.isfinite(scores[i])]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"ids": self.ids, "texts": self.texts, "metas": self.metas,
                                         "vecs": self._vecs}))


class KVStore:
    """JSON-backed key → value store (parents, manifest)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = json.loads(path.read_text()) if path.exists() else {}

    def get(self, k: str, default=None):
        return self.data.get(k, default)

    def put(self, k: str, v):
        self.data[k] = v

    def pop(self, k: str):
        return self.data.pop(k, None)

    def items(self):
        return self.data.items()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))


class Index:
    """One named index = vectors + parents + manifest. Names let you A/B (e.g. 'main' vs 'contextual')."""

    def __init__(self, name: str = "main", root: Path | None = None):
        base = (root or settings.data_dir) / "index" / name
        self.name = name
        self.vectors = VectorStore(base / "vectors.json")
        self.parents = KVStore(base / "parents.json")
        self.manifest = KVStore(base / "manifest.json")

    def save(self):
        self.vectors.save()
        self.parents.save()
        self.manifest.save()
