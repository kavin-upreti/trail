"""Packaging guards.

The zero-third-party-import rule (hard rule 3) is the one that decides whether
`pip install trail-nb` is safe to run inside a Colab notebook that already has a
carefully pinned torch. It is worth a real test.
"""

import subprocess
import sys

import trail

PROBE = """
import sys, json
stdlib = set(sys.stdlib_module_names)
before = set(sys.modules)
import trail
new = set(sys.modules) - before
third_party = sorted(
    name for name in new
    if not name.startswith(("trail", "_"))
    and name.partition(".")[0] not in stdlib
)
print(json.dumps(third_party))
"""


def test_version_is_a_string():
    assert isinstance(trail.__version__, str)
    assert trail.__version__


def test_importing_trail_pulls_in_nothing_third_party():
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[]", f"trail imported third-party modules: {out}"


def test_public_api_is_present():
    for name in ("start", "stop", "pause", "resume", "status", "checkpoint", "note", "metric"):
        assert callable(getattr(trail, name)), name


def test_start_outside_a_kernel_explains_itself():
    import pytest

    with pytest.raises(RuntimeError, match="notebook cells"):
        trail.start("no-kernel-here")
