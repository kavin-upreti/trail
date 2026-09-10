from trail.common import tags


def test_cell_tag_with_colon_and_space():
    assert tags.parse("# @cell: mlp-init\nx = 1").cell == "mlp-init"
    assert tags.parse("# @cell mlp-init").cell == "mlp-init"
    assert tags.parse("#@cell:mlp-init").cell == "mlp-init"
    assert tags.parse("    # @cell: mlp-init").cell == "mlp-init"


def test_checkpoint_note_is_kept():
    t = tags.parse("# @cp fixing dead tanh neurons\nW1 = 1")
    assert t.checkpoint and t.checkpoint_note == "fixing dead tanh neurons"
    assert tags.parse("# @checkpoint").checkpoint
    assert tags.parse("# @cp").checkpoint_note == ""


def test_flag_tags():
    t = tags.parse("# @fix\n# @keep\n# @skip")
    assert (t.fix, t.keep, t.skip) == (True, True, True)


def test_unknown_tags_are_collected_not_raised():
    assert tags.parse("# @wat something").unknown == ("wat",)


def test_a_tag_must_own_its_line():
    # Trailing comments are not tags, or every mention of @cp in prose would be one.
    assert tags.parse("x = 1  # @cp not a tag").cell is None
    assert not tags.parse("x = 1  # @cp not a tag").checkpoint


def test_unusable_cell_slug_is_ignored():
    assert tags.parse("# @cell: !!!").cell is None


def test_slugify():
    assert tags.slugify("Makemore 3") == "makemore-3"
    assert tags.slugify("  --A_b--  ") == "a-b"
    assert tags.slugify("!!!") == ""
    assert len(tags.slugify("x" * 200)) == 64


def test_parse_never_raises():
    for bad in ["", "\x00", "# @", "# @cell:"]:
        tags.parse(bad)
