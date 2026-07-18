"""[pause] marker parsing for narration scripts (pipelines.s2_pipeline)."""

from app.pipelines.s2_pipeline import parse_pause_markers


def test_no_markers_is_one_part() -> None:
    assert parse_pause_markers("Hello there. How are you?") == [
        ("Hello there. How are you?", 0.0)
    ]


def test_default_pause() -> None:
    assert parse_pause_markers("First part. [pause] Second part.") == [
        ("First part.", 0.6),
        ("Second part.", 0.0),
    ]


def test_timed_pause_variants() -> None:
    assert parse_pause_markers("A [pause:2] B") == [("A", 2.0), ("B", 0.0)]
    assert parse_pause_markers("A [PAUSE: 1.5] B") == [("A", 1.5), ("B", 0.0)]
    assert parse_pause_markers("A [pause 3s] B") == [("A", 3.0), ("B", 0.0)]


def test_pause_is_capped() -> None:
    assert parse_pause_markers("A [pause:99] B") == [("A", 10.0), ("B", 0.0)]


def test_adjacent_markers_accumulate() -> None:
    assert parse_pause_markers("A [pause:2][pause:3] B") == [("A", 5.0), ("B", 0.0)]


def test_leading_and_trailing_markers_are_dropped() -> None:
    assert parse_pause_markers("[pause] A [pause:4]") == [("A", 0.0)]


def test_marker_only_script_is_empty() -> None:
    assert parse_pause_markers("[pause] [pause:2]") == []
