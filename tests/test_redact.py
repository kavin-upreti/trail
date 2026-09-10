from trail.capture.redact import PLACEHOLDER, redact


def test_known_token_shapes_are_redacted():
    samples = [
        "sk-ant-api03-" + "a" * 40,
        "sk-" + "b" * 32,
        "hf_" + "c" * 30,
        "ghp_" + "d" * 36,
        "github_pat_" + "e" * 40,
        "AKIA" + "F" * 16,
        "AIza" + "g" * 35,
    ]
    for token in samples:
        out = redact(f"my key is {token} ok")
        assert token not in out, token
        assert PLACEHOLDER in out


def test_assignment_keeps_the_name_and_drops_the_value():
    out = redact('api_key = "hunter2-hunter2"')
    assert "api_key" in out
    assert "hunter2" not in out


def test_ordinary_text_is_untouched():
    code = "loss = 3.31\nprint('hello')"
    assert redact(code) == code


def test_empty_and_none_pass_through():
    assert redact("") == ""
    assert redact(None) is None
