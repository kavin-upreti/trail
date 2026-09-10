import io

from trail.capture.tee import HEAD_LINES, MAX_LINE_CHARS, TAIL_LINES, Tee


def make():
    sink = io.StringIO()
    return Tee(sink), sink


def test_writes_through_to_the_real_stream():
    tee, sink = make()
    tee.write("hello\n")
    assert sink.getvalue() == "hello\n"


def test_captures_committed_lines():
    tee, _ = make()
    tee.write("a\nb\n")
    assert tee.result() == {"text": "a\nb", "truncated": False, "total_lines": 2}


def test_partial_final_line_is_kept():
    tee, _ = make()
    tee.write("no newline")
    r = tee.result()
    assert r["text"] == "no newline" and r["total_lines"] == 1


def test_carriage_return_overwrites_in_place():
    # This is the tqdm case: only the final state of the line survives.
    tee, _ = make()
    tee.write("10%\r50%\r100%\n")
    assert tee.result()["text"] == "100%"


def test_a_line_left_on_a_carriage_return_is_still_captured():
    # tqdm ends its last bar with \r, not \n. A terminal still shows it, so do we.
    tee, _ = make()
    tee.write("10%\r100%\r")
    assert tee.result()["text"] == "100%"


def test_a_shorter_overwrite_leaves_the_tail_behind():
    # Exactly what a real terminal shows, and why "discard on \r" was wrong.
    tee, _ = make()
    tee.write("100%\rdone\n")
    assert tee.result()["text"] == "done"
    tee2, _ = make()
    tee2.write("abcdef\rXY\n")
    assert tee2.result()["text"] == "XYcdef"


def test_crlf_counts_as_one_newline():
    tee, _ = make()
    tee.write("a\r\nb\r\n")
    assert tee.result()["total_lines"] == 2


def test_ansi_escapes_are_stripped():
    tee, _ = make()
    tee.write("\x1b[31mred\x1b[0m\n")
    assert tee.result()["text"] == "red"


def test_writes_split_across_chunks_rejoin():
    tee, _ = make()
    tee.write("hel")
    tee.write("lo\nwor")
    tee.write("ld\n")
    assert tee.result()["text"] == "hello\nworld"


def test_middle_is_omitted_when_there_are_too_many_lines():
    tee, _ = make()
    total = HEAD_LINES + TAIL_LINES + 100
    tee.write("".join(f"line{i}\n" for i in range(total)))
    r = tee.result()
    assert r["truncated"] and r["total_lines"] == total
    assert "line0" in r["text"] and f"line{total - 1}" in r["text"]
    assert "[100 lines omitted]" in r["text"]
    assert "line250" not in r["text"]


def test_a_single_enormous_line_stays_bounded():
    tee, _ = make()
    tee.write("x" * 500_000 + "\n")
    assert len(tee.result()["text"]) <= MAX_LINE_CHARS


def test_forwards_attributes_of_the_wrapped_stream():
    tee, sink = make()
    assert tee.isatty() == sink.isatty()
    tee.flush()


def test_capture_failure_never_breaks_the_write(monkeypatch):
    tee, sink = make()
    monkeypatch.setattr(tee, "_absorb", lambda text: 1 / 0)
    tee.write("still printed\n")  # must not raise
    assert sink.getvalue() == "still printed\n"
