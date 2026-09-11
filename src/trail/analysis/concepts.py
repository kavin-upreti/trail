"""The concept vocabulary (SPEC 11.6).

Hard rule 6: **no invented paper links.** Claude may only cite concepts from this
file, and every URL here is checked by `scripts/check_concept_links.py`. Anything it
wants to mention beyond the vocabulary is rendered as "unverified — no link".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PACKAGED = Path(__file__).resolve().parent.parent / "data" / "concepts.yaml"
USER = Path.home() / ".config" / "trail" / "concepts.yaml"


@dataclass(frozen=True)
class Ref:
    title: str
    url: str
    kind: str = "paper"


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    category: str = ""
    summary: str = ""
    aliases: tuple[str, ...] = ()
    refs: tuple[Ref, ...] = field(default_factory=tuple)


def _parse(path: Path) -> list[Concept]:
    if not path.is_file():
        return []
    try:
        import yaml
    except ImportError:  # pragma: no cover - yaml ships with the [mac] extra
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except Exception:
        return []

    concepts: list[Concept] = []
    for entry in data:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        refs = tuple(
            Ref(str(r.get("title", "")), str(r.get("url", "")), str(r.get("kind", "paper")))
            for r in entry.get("refs") or []
            if isinstance(r, dict) and r.get("url")
        )
        concepts.append(
            Concept(
                id=str(entry["id"]),
                name=str(entry.get("name", entry["id"])),
                category=str(entry.get("category", "")),
                summary=str(entry.get("summary", "")),
                aliases=tuple(str(a) for a in entry.get("aliases") or []),
                refs=refs,
            )
        )
    return concepts


@lru_cache(maxsize=1)
def load() -> dict[str, Concept]:
    """Packaged vocabulary, with a user file layered on top (same id → user wins)."""
    merged = {c.id: c for c in _parse(PACKAGED)}
    merged.update({c.id: c for c in _parse(USER)})
    return merged


def vocabulary_lines() -> str:
    """`id — name — summary` per concept. No URLs: they'd cost tokens for nothing."""
    return "\n".join(
        f"{c.id} — {c.name} — {c.summary}" for c in sorted(load().values(), key=lambda c: c.id)
    )


def known(concept_id: str) -> bool:
    return concept_id in load()


def get(concept_id: str) -> Concept | None:
    return load().get(concept_id)


def all_refs() -> list[tuple[str, Ref]]:
    return [(c.id, ref) for c in load().values() for ref in c.refs]


def as_dicts() -> list[dict[str, Any]]:
    return [
        {
            "id": c.id,
            "name": c.name,
            "category": c.category,
            "summary": c.summary,
            "refs": [{"title": r.title, "url": r.url, "kind": r.kind} for r in c.refs],
        }
        for c in sorted(load().values(), key=lambda c: c.id)
    ]
