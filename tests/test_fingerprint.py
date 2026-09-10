import math

from trail.capture import fingerprint


def test_scalars_are_stored_as_values():
    fp = fingerprint.take({"lr": 0.1, "n": 200, "ok": True, "nothing": None})
    assert fp == {"lr": 0.1, "n": 200, "ok": True, "nothing": None}


def test_non_json_floats_become_strings():
    fp = fingerprint.take({"a": math.nan, "b": math.inf, "c": -math.inf})
    assert fp == {"a": "nan", "b": "inf", "c": "-inf"}


def test_long_strings_are_summarised():
    fp = fingerprint.take({"short": "hi", "long": "x" * 500})
    assert fp["short"] == "hi"
    assert fp["long"] == {"type": "str", "len": 500}


def test_containers_report_only_their_length():
    fp = fingerprint.take({"words": list(range(32033)), "d": {"a": 1}})
    assert fp["words"] == {"type": "list", "len": 32033}
    assert fp["d"] == {"type": "dict", "len": 1}


def test_arrays_report_shape_and_dtype():
    import numpy as np

    fp = fingerprint.take({"W1": np.zeros((30, 200), dtype=np.float32)})
    assert fp["W1"] == {"shape": [30, 200], "dtype": "float32"}


def test_skips_private_names_modules_functions_and_classes():
    import os

    fp = fingerprint.take(
        {"_hidden": 1, "os": os, "f": lambda: 1, "C": type, "In": [], "get_ipython": 1}
    )
    assert fp == {}


class Hostile:
    """Touching this object in any way is an error — like a lazy loader or a CUDA tensor."""

    def __repr__(self):
        raise AssertionError("repr() was called on a user object")

    def __getattr__(self, name):
        raise AssertionError(f"attribute {name!r} was read on a user object")

    def __len__(self):
        raise AssertionError("len() was called on a user object")


def test_never_touches_an_unknown_object():
    # The whole point of SPEC 8.5's rules; if this regresses, notebooks break.
    assert fingerprint.take({"danger": Hostile(), "lr": 0.1}) == {"lr": 0.1}


def test_entry_cap():
    fp = fingerprint.take({f"v{i:04d}": i for i in range(500)})
    assert len(fp) == fingerprint.MAX_ENTRIES
    assert "v0000" in fp  # alphabetical, so the cap is deterministic


def test_diff_reports_added_removed_and_changed():
    d = fingerprint.diff({"lr": 0.1, "gone": 1}, {"lr": 0.01, "new": 2})
    assert d["added"] == {"new": 2}
    assert d["removed"] == ["gone"]
    assert d["changed"] == {"lr": {"before": 0.1, "after": 0.01}}
