"""Smoke test: the package imports and reports a version.

Deliberately tiny — it exists so `pytest` has something real to run at M0 and so
a broken src-layout install fails loudly rather than at M1.
"""

import trail


def test_version_is_a_string():
    assert isinstance(trail.__version__, str)
    assert trail.__version__


def test_base_package_has_no_third_party_imports():
    # why: hard rule 3 — importing trail in Colab must not pull anything in.
    import subprocess
    import sys

    before = subprocess.run(
        [sys.executable, "-c", "import sys; print(len(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    after = subprocess.run(
        [sys.executable, "-c", "import trail, sys; print(len(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    # A handful of stdlib modules is fine; a third-party tree is not.
    assert int(after) - int(before) < 25
