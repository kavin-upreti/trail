"""Getting a trustworthy JSON object back out of a language model (SPEC 11.3).

Two separate jobs: dig the JSON out of whatever wrapping it arrived in, then check
it says only things we allow. The important check is `concepts` — an id that isn't
in the vocabulary gets demoted to `other_concepts`, where it renders without a link
(hard rule 6). Demote, never reject: a good explanation shouldn't be thrown away
because one label was unfamiliar.
"""

from __future__ import annotations

import json
import re
from typing import Any

MAX_TITLE = 70
MAX_SELF_CHECK = 3
DIRECTIONS = {"improved", "worse", "unchanged", "unclear"}
CONFIDENCES = {"high", "medium", "low"}

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class InvalidAnalysis(ValueError):
    """The model's reply wasn't usable."""


def extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a reply that may be fenced or chatty."""
    if not text or not text.strip():
        raise InvalidAnalysis("the reply was empty")

    candidates: list[str] = []
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise InvalidAnalysis("couldn't find a JSON object in the reply")


def _string_list(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def validate(data: dict[str, Any], is_known_concept) -> dict[str, Any]:
    """Coerce the model's object into the shape the renderer can rely on."""
    if not isinstance(data, dict):
        raise InvalidAnalysis("expected a JSON object")

    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not title:
        raise InvalidAnalysis("missing 'title'")
    if not summary:
        raise InvalidAnalysis("missing 'summary'")

    changes: list[dict[str, str]] = []
    raw_changes = data.get("changes")
    if isinstance(raw_changes, list):
        for item in raw_changes[:12]:
            if isinstance(item, dict) and str(item.get("what", "")).strip():
                entry = {"what": str(item["what"]).strip()}
                if str(item.get("detail") or "").strip():
                    entry["detail"] = str(item["detail"]).strip()
                changes.append(entry)
            elif isinstance(item, str) and item.strip():
                changes.append({"what": item.strip()})

    raw_effect = data.get("effect") if isinstance(data.get("effect"), dict) else {}
    direction = str(raw_effect.get("direction") or "unclear").lower()
    confidence = str(raw_effect.get("confidence") or "low").lower()
    effect = {
        "metric": (str(raw_effect.get("metric")).strip() if raw_effect.get("metric") else None),
        "before": _number_or_none(raw_effect.get("before")),
        "after": _number_or_none(raw_effect.get("after")),
        "direction": direction if direction in DIRECTIONS else "unclear",
        "confidence": confidence if confidence in CONFIDENCES else "low",
        "noise_note": (
            str(raw_effect.get("noise_note")).strip() if raw_effect.get("noise_note") else None
        ),
    }

    # Hard rule 6: unknown ids lose their link rather than inventing one.
    concepts: list[str] = []
    other: list[dict[str, str]] = []
    for concept_id in _string_list(data.get("concepts")):
        if is_known_concept(concept_id):
            concepts.append(concept_id)
        else:
            other.append({"name": concept_id, "why_relevant": "suggested, not in the vocabulary"})

    for item in data.get("other_concepts") or []:
        if isinstance(item, dict) and str(item.get("name", "")).strip():
            other.append(
                {
                    "name": str(item["name"]).strip(),
                    "why_relevant": str(item.get("why_relevant") or "").strip(),
                }
            )
        elif isinstance(item, str) and item.strip():
            other.append({"name": item.strip(), "why_relevant": ""})

    self_check: list[dict[str, str]] = []
    for item in data.get("self_check") or []:
        if isinstance(item, dict) and str(item.get("question", "")).strip():
            self_check.append(
                {
                    "question": str(item["question"]).strip(),
                    "answer": str(item.get("answer") or "").strip(),
                }
            )
    if not self_check:
        raise InvalidAnalysis("need at least one self_check question")

    return {
        "title": title[:MAX_TITLE],
        "summary": summary,
        "changes": changes,
        "why": str(data.get("why") or "").strip(),
        "effect": effect,
        "tradeoffs": _string_list(data.get("tradeoffs")),
        "concepts": concepts,
        "other_concepts": other[:8],
        "context_warnings": _string_list(data.get("context_warnings")),
        "plot_observations": (
            str(data.get("plot_observations")).strip() if data.get("plot_observations") else None
        ),
        "try_next": _string_list(data.get("try_next")),
        "self_check": self_check[:MAX_SELF_CHECK],
    }


SCHEMA_TEXT = """{
  "title": "string, <= 70 chars, sentence case",
  "summary": "2-3 sentences",
  "changes": [{"what": "string", "detail": "optional string"}],
  "why": "1-3 short paragraphs, beginner-friendly but precise",
  "effect": {
    "metric": "loss | val_loss | duration_s | other name | null",
    "before": "number | null", "after": "number | null",
    "direction": "improved | worse | unchanged | unclear",
    "confidence": "high | medium | low",
    "noise_note": "string | null"
  },
  "tradeoffs": ["string"],
  "concepts": ["concept ids from the vocabulary only"],
  "other_concepts": [{"name": "string", "why_relevant": "string"}],
  "context_warnings": ["e.g. 'lr also changed in cell hparams between these runs'"],
  "plot_observations": "string | null",
  "try_next": ["string"],
  "self_check": [{"question": "string", "answer": "string"}]
}"""
