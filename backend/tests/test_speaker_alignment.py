import dataclasses

import pytest

from app.ai.asr.provider import TimedText
from app.ai.speaker.provider import DiarizedSegment
from app.services.speaker_alignment import SpeakerTurn, align_timed_text_to_speakers


def word(text: str, start: float, end: float) -> TimedText:
    return TimedText(text, start, end)


def seg(speaker_id: str, start: float, end: float) -> DiarizedSegment:
    return DiarizedSegment(speaker_id, start, end)


def test_single_speaker_single_item():
    turns = align_timed_text_to_speakers(
        [word("vanakkam", 0.5, 1.5)], [seg("A", 0.0, 3.0)]
    )

    assert turns == (SpeakerTurn("A", "vanakkam", 0.5, 1.5),)


def test_alternating_speakers_produce_separate_turns():
    items = [word("a", 0.0, 1.0), word("b", 1.0, 2.0), word("c", 2.0, 3.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0), seg("A", 2.0, 3.0)]

    turns = align_timed_text_to_speakers(items, segments)

    assert [(t.speaker_id, t.text) for t in turns] == [
        ("A", "a"),
        ("B", "b"),
        ("A", "c"),
    ]


def test_consecutive_items_of_same_speaker_are_merged():
    items = [
        word("hello", 0.0, 1.0),
        word("sir", 1.0, 2.0),
        word("how", 2.0, 3.0),
        word("are", 3.0, 4.0),
    ]
    segments = [seg("A", 0.0, 2.0), seg("B", 2.0, 4.0)]

    turns = align_timed_text_to_speakers(items, segments)

    assert turns == (
        SpeakerTurn("A", "hello sir", 0.0, 2.0),
        SpeakerTurn("B", "how are", 2.0, 4.0),
    )


def test_item_without_overlap_is_ignored():
    items = [word("x", 0.0, 1.0), word("y", 5.0, 6.0)]

    turns = align_timed_text_to_speakers(items, [seg("A", 0.0, 1.0)])

    assert turns == (SpeakerTurn("A", "x", 0.0, 1.0),)


def test_item_touching_segment_boundary_is_ignored():
    turns = align_timed_text_to_speakers([word("x", 1.0, 2.0)], [seg("A", 0.0, 1.0)])

    assert turns == ()


def test_ignored_item_does_not_split_a_speaker_turn():
    items = [word("a", 0.0, 1.0), word("gap", 2.0, 3.0), word("b", 4.0, 5.0)]
    segments = [seg("A", 0.0, 1.0), seg("A", 4.0, 5.0)]

    turns = align_timed_text_to_speakers(items, segments)

    assert turns == (SpeakerTurn("A", "a b", 0.0, 5.0),)


def test_overlapping_segments_pick_greatest_overlap():
    segments = [seg("A", 0.0, 1.5), seg("B", 1.2, 3.0)]

    turns = align_timed_text_to_speakers([word("x", 1.0, 2.0)], segments)

    assert [t.speaker_id for t in turns] == ["B"]


def test_overlapping_segments_of_same_speaker_are_not_double_counted():
    segments = [seg("A", 0.0, 0.7), seg("A", 0.3, 1.0), seg("B", 0.9, 2.0)]

    turns = align_timed_text_to_speakers([word("x", 0.0, 2.0)], segments)

    assert [t.speaker_id for t in turns] == ["B"]


def test_equal_overlap_goes_to_earliest_speaker_regardless_of_input_order():
    segments = [seg("B", 1.0, 2.0), seg("A", 0.0, 1.0)]

    turns = align_timed_text_to_speakers([word("x", 0.0, 2.0)], segments)

    assert [t.speaker_id for t in turns] == ["A"]


def test_output_is_chronological_for_unordered_input():
    items = [word("c", 2.0, 3.0), word("a", 0.0, 1.0), word("b", 1.0, 2.0)]
    segments = [seg("A", 0.0, 1.0), seg("B", 1.0, 2.0), seg("A", 2.0, 3.0)]

    turns = align_timed_text_to_speakers(items, segments)

    assert [(t.speaker_id, t.text) for t in turns] == [
        ("A", "a"),
        ("B", "b"),
        ("A", "c"),
    ]
    assert [t.start_time for t in turns] == sorted(t.start_time for t in turns)


@pytest.mark.parametrize(
    "items, segments",
    [([], [seg("A", 0.0, 1.0)]), ([word("a", 0.0, 1.0)], [])],
)
def test_empty_input_returns_empty_result(items, segments):
    assert align_timed_text_to_speakers(items, segments) == ()


def test_result_is_immutable():
    turns = align_timed_text_to_speakers(
        [word("a", 0.0, 1.0)], [seg("A", 0.0, 1.0)]
    )

    assert isinstance(turns, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(turns[0], "text", "changed")