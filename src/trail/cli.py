"""The `trail` command.

The real CLI (SPEC section 14) is built in M4. Until then this module exists so the
declared console script resolves, and so the missing-extras message from SPEC 5 is
already correct: the Mac extras carry Typer, and the notebook-side install has no
third-party dependencies at all.
"""

import sys

MISSING_EXTRAS = "The trail command needs the Mac extras: uv tool install -e '.[mac]'"


def app() -> None:
    try:
        import typer  # noqa: F401
    except ImportError:
        print(MISSING_EXTRAS, file=sys.stderr)
        raise SystemExit(1) from None
    print("trail: the CLI arrives in Milestone 4. See docs/SPEC.md section 14.")
