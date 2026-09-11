#!/usr/bin/env python3
"""Check every URL in concepts.yaml actually resolves (SPEC 11.6).

Hard rule 6 says Trail never invents a paper link. This is how we keep that true:
run it, and if a link is dead, **set it aside — never guess a replacement.**

    uv run python scripts/check_concept_links.py
"""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from trail.analysis import concepts as concepts_mod  # noqa: E402

TIMEOUT = 25
ATTEMPTS = 3
PACE_SECONDS = 0.7
# Some publishers reject the default urllib agent outright.
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; trail-link-check/0.1)"}


def _try_once(url: str) -> tuple[bool, str]:
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers=HEADERS)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if 200 <= response.status < 300:
                    return True, str(response.status)
        except urllib.error.HTTPError as exc:
            if method == "GET" or exc.code not in (403, 405, 501):
                return False, f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001 - report anything, never crash the run
            if method == "GET":
                return False, type(exc).__name__
    return False, "no response"


def check(url: str) -> tuple[bool, str]:
    """Verify a URL, retrying transient failures.

    why: arXiv rate-limits a rapid sweep and returns URLError for links that are
    perfectly fine. A false alarm here is dangerous — it invites deleting a real
    citation — so a URL is only called broken after it fails every attempt.
    """
    detail = "no response"
    for attempt in range(ATTEMPTS):
        ok, detail = _try_once(url)
        if ok:
            return True, detail
        if attempt < ATTEMPTS - 1:
            time.sleep(2**attempt)
    return False, detail


def main() -> int:
    refs = concepts_mod.all_refs()
    print(f"Checking {len(refs)} link(s) in {concepts_mod.PACKAGED}\n")
    broken: list[tuple[str, str, str]] = []
    for index, (concept_id, ref) in enumerate(refs):
        if index:
            time.sleep(PACE_SECONDS)  # be a polite client
        ok, detail = check(ref.url)
        print(f"  {'✓' if ok else '✗'} {concept_id:<28} {detail:<12} {ref.url}")
        if not ok:
            broken.append((concept_id, ref.url, detail))

    if not broken:
        print(f"\nAll {len(refs)} links resolve.")
        return 0
    print(f"\n{len(broken)} broken link(s):")
    for concept_id, url, detail in broken:
        print(f"  {concept_id}: {url} ({detail})")
    print("\nRemove the ref or leave it empty. Do NOT substitute a guessed URL.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
