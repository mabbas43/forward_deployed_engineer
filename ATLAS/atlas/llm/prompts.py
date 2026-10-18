"""P1 — prompts are code. They live in prompts/<name>.v<N>.md with a version header; active.yaml picks what serves.

P7's registry (atlas/ops/registry.py) writes active.yaml; this module only reads it.
"""


import yaml

from atlas.config import ROOT

PROMPTS = ROOT / "prompts"


def active() -> dict:
    return yaml.safe_load((PROMPTS / "active.yaml").read_text()) or {}


def active_version(name: str) -> int:
    return int(active()["prompts"][name])


def load(name: str, version: int | None = None) -> tuple[str, int]:
    """Return (body, version). The `<!-- header -->` is metadata for humans and the registry, not the model."""
    v = version or active_version(name)
    text = (PROMPTS / f"{name}.v{v}.md").read_text()
    body = text.split("-->", 1)[1].strip() if text.lstrip().startswith("<!--") else text
    return body, v


def header(name: str, version: int) -> dict[str, str]:
    """Parse `<!-- version: 1 | owner: x | ... -->` into a dict."""
    text = (PROMPTS / f"{name}.v{version}.md").read_text()
    if not text.lstrip().startswith("<!--"):
        return {}
    raw = text.split("<!--", 1)[1].split("-->", 1)[0]
    pairs = [p.split(":", 1) for p in raw.split("|") if ":" in p]
    return {k.strip(): v.strip() for k, v in pairs}
