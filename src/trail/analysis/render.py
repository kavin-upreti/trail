"""Analysis JSON → Markdown (SPEC 11.4).

Two things this must get right. Concepts from the vocabulary get their real links;
anything else is labelled *(unverified — no link)*, because a plausible-looking
citation that doesn't exist is worse than none (hard rule 6). And the effect chip
always carries its confidence, so a 0.03 improvement inside ±0.05 of noise never
reads as a win.
"""

from __future__ import annotations

from typing import Any

from trail.analysis import concepts as concepts_mod

ARROWS = {"improved": "↓", "worse": "↑", "unchanged": "=", "unclear": "?"}


def effect_chip(effect: dict[str, Any]) -> str:
    """One line summarising the measured result, honest about uncertainty."""
    metric = effect.get("metric")
    before, after = effect.get("before"), effect.get("after")
    direction = effect.get("direction", "unclear")
    confidence = effect.get("confidence", "low")

    if metric and before is not None and after is not None:
        head = f"{metric} {before:.4g} → {after:.4g}"
    elif metric and after is not None:
        head = f"{metric} {after:.4g}"
    else:
        head = "no measured metric"
    return f"{head} · {direction} {ARROWS.get(direction, '')} · {confidence} confidence".strip()


def render(analysis: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    """The Markdown a human reads, saved next to the JSON."""
    out: list[str] = []
    add = out.append

    add(f"# {analysis['title']}")
    add("")
    add(f"**{effect_chip(analysis['effect'])}**")
    noise = analysis["effect"].get("noise_note")
    if noise:
        add("")
        add(f"> {noise}")
    add("")
    add(analysis["summary"])

    if analysis.get("changes"):
        add("")
        add("## What changed")
        for change in analysis["changes"]:
            detail = f" — {change['detail']}" if change.get("detail") else ""
            add(f"- **{change['what']}**{detail}")

    if analysis.get("why"):
        add("")
        add("## Why it helps")
        add("")
        add(analysis["why"])

    if analysis.get("context_warnings"):
        add("")
        add("## ⚠ Careful")
        add("")
        add("Other things changed at the same time, so the numbers aren't a clean comparison:")
        for warning in analysis["context_warnings"]:
            add(f"- {warning}")

    if analysis.get("tradeoffs"):
        add("")
        add("## Tradeoffs")
        for item in analysis["tradeoffs"]:
            add(f"- {item}")

    if analysis.get("plot_observations"):
        add("")
        add("## What the plots show")
        add("")
        add(analysis["plot_observations"])

    if analysis.get("concepts") or analysis.get("other_concepts"):
        add("")
        add("## Concepts")
        for concept_id in analysis.get("concepts") or []:
            concept = concepts_mod.get(concept_id)
            if concept is None:
                continue
            add("")
            add(f"### {concept.name}")
            if concept.summary:
                add(f"{concept.summary}")
            for ref in concept.refs:
                add(f"- [{ref.title}]({ref.url})")
        for other in analysis.get("other_concepts") or []:
            add("")
            why = f" — {other['why_relevant']}" if other.get("why_relevant") else ""
            add(f"### {other['name']} *(unverified — no link)*{why}")

    if analysis.get("try_next"):
        add("")
        add("## Try next")
        for item in analysis["try_next"]:
            add(f"- {item}")

    if analysis.get("self_check"):
        add("")
        add("## Check yourself")
        for item in analysis["self_check"]:
            add("")
            add(f"**{item['question']}**")
            add("")
            add("<details><summary>Answer</summary>")
            add("")
            add(item.get("answer") or "(no answer recorded)")
            add("")
            add("</details>")

    if meta:
        add("")
        add("---")
        bits = [f"{k}: {v}" for k, v in meta.items() if v not in (None, "")]
        add(f"*{' · '.join(bits)}*")

    return "\n".join(out) + "\n"
