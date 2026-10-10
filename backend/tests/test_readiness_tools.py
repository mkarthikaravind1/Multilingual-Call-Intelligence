"""The fast live-analysis setting, and the scoring rules of the accuracy
measurement and the load test (neither tool calls a real service here)."""

import json
import logging

import pytest

from app.api.wiring import live_analysis_interval_seconds
from app.core.config import Settings
from app.domain.call_alert import QuestionOutcome, QuestionOutcomeChoice
from app.domain.sentiment import SentimentLabel
from app.domain.utterance import SpeakerRole, Utterance
from app.services.call_alerts import InMemoryQuestionOutcomeRepository
from app.services.live_analysis_scheduler import LiveAnalysisScheduler
from scripts import load_test
from scripts.evaluate_transcription import score
from scripts.measure_accuracy import (
    MIN_QUESTION_OUTCOMES,
    CallResult,
    Label,
    LabelError,
    conversation_of,
    spoken_lines,
    without_speakers,
    load_label,
    measures,
    report,
)

NEG, FRU, NEU, POS = (
    SentimentLabel.NEGATIVE,
    SentimentLabel.FRUSTRATED,
    SentimentLabel.NEUTRAL,
    SentimentLabel.POSITIVE,
)


# ---- LIVE_ANALYSIS_SPEED ----

def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def test_standard_speed_keeps_the_interval_and_fast_has_none(caplog):
    assert live_analysis_interval_seconds(_settings()) == 30.0
    assert live_analysis_interval_seconds(_settings(live_analysis_min_interval_seconds=10)) == 10
    assert live_analysis_interval_seconds(_settings(live_analysis_speed=" FAST ")) == 0.0

    with caplog.at_level(logging.WARNING):
        assert live_analysis_interval_seconds(_settings(live_analysis_speed="turbo")) == 30.0
    assert "Unknown LIVE_ANALYSIS_SPEED" in caplog.text


class _Workflow:
    def __init__(self) -> None:
        self.analysed = 0

    def record_utterance(self, call_id, utterance):
        pass

    def record_utterance_update(self, call_id, utterance):
        pass

    def analyze_latest_speech(self, call_id):
        self.analysed += 1

    def analyze_call(self, call_id):
        return None


class _Inline:
    """Runs the work at once, on the caller's thread."""

    def submit(self, work):
        work()


def _line(index: int) -> Utterance:
    return Utterance(f"u{index}", "Hello.", SpeakerRole.CUSTOMER, ("en",), float(index), index + 0.5)


def test_fast_analyses_after_every_line_and_standard_waits_its_interval():
    fast, waits = _Workflow(), []

    def later(seconds, work):
        waits.append(seconds)
        work()

    scheduler = LiveAnalysisScheduler(
        fast, executor=_Inline(), min_interval_seconds=0.0, later=later
    )
    for index in range(3):
        scheduler.process_utterance("call-1", _line(index))
    assert (fast.analysed, waits) == (3, [])

    standard, waits = _Workflow(), []
    scheduler = LiveAnalysisScheduler(
        standard, executor=_Inline(), min_interval_seconds=30.0, later=later
    )
    for index in range(3):
        scheduler.process_utterance("call-1", _line(index))
    # The first runs at once; each later one waits out the rest of its 30 s.
    assert standard.analysed == 3
    assert len(waits) == 2 and all(29.0 < wait <= 30.0 for wait in waits)


def test_a_call_waiting_out_its_interval_does_not_hold_up_other_calls():
    """With one worker, a second call is analysed while the first waits."""
    order: list[str] = []
    waiting: list = []
    queue: list = []

    class Queue:
        def submit(self, work):
            queue.append(work)

    class Workflow(_Workflow):
        def analyze_latest_speech(self, call_id):
            order.append(call_id)
            if order == ["a"]:
                scheduler.request_analysis("a")  # more speech on call a meanwhile

    scheduler = LiveAnalysisScheduler(
        Workflow(),
        executor=Queue(),
        min_interval_seconds=30.0,
        later=lambda seconds, work: waiting.append(work),
    )
    scheduler.request_analysis("a")
    queue.pop(0)()  # a is analysed; its follow-up goes to the back of the queue
    scheduler.request_analysis("b")
    while queue:
        queue.pop(0)()

    # a's follow-up is waiting for its interval, and b was not kept waiting.
    assert order == ["a", "b"]
    assert len(waiting) == 1
    assert scheduler.wait_until_idle(timeout=0) is False

    waiting.pop()()  # the interval is over
    while queue:
        queue.pop(0)()
    assert order == ["a", "b", "a"]
    assert scheduler.wait_until_idle(timeout=0) is True


def test_the_number_of_analysis_workers_is_a_setting():
    assert _settings().live_analysis_workers == 16
    assert _settings(live_analysis_workers=40).live_analysis_workers == 40


# ---- Accuracy: labels ----

KNOWN = {"cost": "Cost", "turnaround time": "Turnaround Time", "hygiene": "Hygiene"}


def _label_file(tmp_path, name: str, content) -> object:
    path = tmp_path / f"{name}.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def test_a_label_is_read_with_the_systems_spelling_and_its_recording(tmp_path):
    path = _label_file(
        tmp_path,
        "call_01",
        {"transcript": "  The bill was high. ", "categories": ["cost", " turnaround  TIME "], "sentiment": "frustrated"},
    )
    (tmp_path / "call_01.mp3").write_bytes(b"audio")

    label = load_label(path, KNOWN)

    assert label.name == "call_01"
    assert label.transcript == "The bill was high."
    assert label.categories == {"Cost", "Turnaround Time"}
    assert label.sentiment is FRU
    assert label.recording == tmp_path / "call_01.mp3"


def test_a_label_may_leave_things_out(tmp_path):
    label = load_label(_label_file(tmp_path, "bare", {}), KNOWN)

    assert (label.transcript, label.categories, label.sentiment, label.recording) == (
        "",
        frozenset(),
        None,
        None,
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ({"categories": ["Costs"]}, "'Costs' is not a complaint category"),
        ({"categories": "Cost"}, "must be a list"),
        ({"sentiment": "ANGRY"}, "must be one of POSITIVE"),
        ({"transcript": 5}, "must be text"),
    ],
)
def test_a_mistake_in_a_label_is_named(tmp_path, content, message):
    with pytest.raises(LabelError, match=message) as error:
        load_label(_label_file(tmp_path, "bad", content), KNOWN)
    assert "bad.json" in str(error.value)


# ---- Accuracy: scoring ----

def _result(expected, detected, expected_tone=None, given_tone=None, transcription=None, name="c"):
    return CallResult(
        Label(name, "", frozenset(expected), expected_tone),
        frozenset(detected),
        given_tone,
        transcription,
    )


def _by_name(rows):
    return {row.name.split(" (")[0]: row for row in rows}


def test_categories_are_right_when_expected_and_detected_agree():
    rows = _by_name(
        measures(
            [
                _result({"Cost", "Hygiene"}, {"Cost", "Hygiene"}),
                _result({"Cost"}, {"Cost", "Turnaround Time"}),  # one extra
                _result({"Hygiene", "Cost"}, {"Cost"}),  # one missed
                _result(set(), set()),
            ]
        )
    )

    categories = rows["Complaint categories"]
    # Expected or detected: 2 + 2 + 2 = 6; both: 2 + 1 + 1 = 4.
    assert (categories.correct, categories.total) == (4, 6)
    assert categories.rate == pytest.approx(4 / 6)
    assert categories.verdict == "below the target"
    assert categories.extra == ("missed: 1", "detected but not expected: 1")

    # Two calls expected several categories; one had them all detected.
    several = rows["Several categories on one call"]
    assert (several.correct, several.total) == (1, 2)


def test_extra_detections_do_not_fail_the_several_categories_target():
    several = _by_name(measures([_result({"Cost", "Hygiene"}, {"Cost", "Hygiene", "Turnaround Time"})]))[
        "Several categories on one call"
    ]

    assert (several.correct, several.total, several.verdict) == (1, 1, "meets the target")


def test_sentiment_must_be_the_expected_label_and_the_near_misses_are_shown():
    sentiment = _by_name(
        measures(
            [
                _result(set(), set(), NEG, NEG),
                _result(set(), set(), FRU, NEG),  # wrong label, right side
                _result(set(), set(), POS, NEG),  # wrong side
                _result(set(), set(), None, NEU),  # not labelled: not counted
            ]
        )
    )["Sentiment"]

    assert (sentiment.correct, sentiment.total) == (1, 3)
    assert sentiment.extra == ("right side (negative or not): 2 of 3",)


def test_speech_recognition_is_the_share_of_words_right_over_all_calls():
    rows = _by_name(
        measures(
            [
                _result(set(), set(), transcription=score("the bill was too high", "the bill was two high")),
                _result(set(), set(), transcription=score("nobody called me back", "nobody called me back")),
                _result(set(), set()),  # not transcribed
            ]
        )
    )

    speech = rows["Speech recognition"]
    assert (speech.correct, speech.total) == (8, 9)
    assert speech.verdict == "below the target"
    assert speech.extra[0].startswith("characters right: 9")


def test_what_could_not_be_measured_says_why():
    rows = _by_name(measures([_result({"Cost"}, {"Cost"})]))

    assert rows["Speech recognition"].rate is None
    assert rows["Speech recognition"].verdict == "not measured"
    assert "No call was transcribed" in rows["Speech recognition"].note
    assert "two or more categories" in rows["Several categories on one call"].note
    assert "No label gives a sentiment" in rows["Sentiment"].note
    assert "--question-outcomes" in rows["Question relevance"].note
    assert rows["Complaint categories"].verdict == "meets the target"


def test_question_relevance_needs_enough_choices_before_it_is_a_number():
    few = _by_name(measures([], (20, 5)))["Question relevance"]
    assert few.rate is None
    assert f"25 questions were accepted or skipped, and at least {MIN_QUESTION_OUTCOMES}" in few.note

    enough = _by_name(measures([], (27, 3)))["Question relevance"]
    assert (enough.correct, enough.total, enough.verdict) == (27, 30, "meets the target")
    assert _by_name(measures([], (20, 20)))["Question relevance"].verdict == "below the target"


def test_question_outcomes_are_totalled_over_every_call():
    outcomes = InMemoryQuestionOutcomeRepository()
    accepted, skipped = QuestionOutcomeChoice.ACCEPTED, QuestionOutcomeChoice.SKIPPED
    outcomes.save(QuestionOutcome("c1", "Q1", "Cost", accepted, "asha", 1.0))
    outcomes.save(QuestionOutcome("c1", "Q2", "Cost", skipped, "asha", 2.0))
    outcomes.save(QuestionOutcome("c2", "Q1", "Cost", accepted, "ravi", 3.0))

    assert outcomes.totals() == (2, 1)
    assert InMemoryQuestionOutcomeRepository().totals() == (0, 0)


def test_the_report_lists_each_target_and_each_call():
    results = [
        _result({"Cost"}, {"Cost", "Hygiene"}, NEG, FRU, score("a b c d", "a b c d"), name="call_01"),
        _result(set(), set(), name="call_02"),
    ]

    text = report(results, measures(results, (1, 1)))

    assert "| Complaint categories | 92% | 50.0% | 1 of 2 | below the target |" in text
    assert "| Speech recognition (words right) | 95% | 100.0% | 4 of 4 | meets the target |" in text
    assert "| Several categories on one call | 88% | - | - | not measured |" in text
    assert "| call_01 | 100.0% | Cost | Cost, Hygiene | NEGATIVE | FRUSTRATED |" in text
    assert "| call_02 | - | none | none | - | - |" in text
    assert "Not enough data yet: 2 questions" in text
    assert "speed targets" in text


def test_a_labelled_transcript_keeps_who_said_each_line():
    transcript = (
        "ICR: Good morning.\n"
        "customer: My car was due yesterday.\n"
        "  Nobody called me.\n"
        "\n"
        "Executive: I am sorry.\n"
        "CUSTOMER:\n"
        "Note: the bill is higher too."
    )

    conversation = conversation_of("call_01", transcript)

    assert conversation.call_id == "accuracy-call_01"
    assert [(u.speaker_role, u.transcript) for u in conversation.utterances] == [
        (SpeakerRole.ICR, "Good morning."),
        (SpeakerRole.CUSTOMER, "My car was due yesterday. Nobody called me."),
        # "Note:" names no speaker, so the line carries on the one before.
        (SpeakerRole.ICR, "I am sorry. Note: the bill is higher too."),
    ]
    assert without_speakers(transcript).startswith("Good morning. My car was due yesterday.")


def test_a_transcript_without_speakers_is_taken_as_the_customers_words():
    assert spoken_lines("The bill was high.\nNobody called.") == [
        (SpeakerRole.CUSTOMER, "The bill was high. Nobody called.")
    ]
    assert spoken_lines("  \n") == []


# ---- Load test: what counts as keeping up ----

def _outcome(**values) -> load_test.CallOutcome:
    return load_test.CallOutcome(
        **{
            "started": True,
            "completed": True,
            "expected_segments": 10,
            "transcribed_segments": 10,
            "finish_seconds": 1.0,
            **values,
        }
    )


def test_each_side_speaks_three_seconds_in_every_eight():
    # Caller at 0, 8, 16...; executive at 4, 12...; only whole stretches count.
    assert load_test.expected_segments(20) == 5
    assert load_test.expected_segments(60) == 15
    assert load_test.expected_segments(2) == 0
    assert load_test._speaking("inbound", 1.0) and not load_test._speaking("inbound", 3.5)
    assert load_test._speaking("outbound", 4.5) and not load_test._speaking("outbound", 1.0)


def test_the_backend_kept_up_only_when_every_call_was_heard_and_finished():
    results = load_test.Results(
        calls=[
            _outcome(watched=True, first_analysis_seconds=8.0),
            _outcome(transcribed_segments=9),
        ]
    )
    results.live_view_seconds = [0.1, 0.2]

    text, kept_up = load_test.summarize(results, calls=2, seconds=60)

    assert kept_up is True
    assert "calls completed        2 of 2" in text
    assert "19 of 20 stretches; 2 of 2 calls" in text
    assert "kept up" in text and "DID NOT" not in text


@pytest.mark.parametrize(
    "bad",
    [
        _outcome(completed=False, finish_seconds=None, transcribed_segments=0),
        _outcome(error="ConnectionClosed: gone"),
        _outcome(transcribed_segments=5),
        _outcome(finish_seconds=45.0),
        _outcome(watched=True, first_analysis_seconds=62.0),  # analysed only after it ended
        _outcome(watched=True, first_analysis_seconds=None),
    ],
)
def test_a_lost_call_lost_speech_or_a_slow_finish_means_it_did_not_keep_up(bad):
    results = load_test.Results(calls=[_outcome(), bad])

    text, kept_up = load_test.summarize(results, calls=2, seconds=60)

    assert kept_up is False
    assert "DID NOT keep up" in text


def test_a_failing_live_view_or_a_slow_sender_is_reported():
    results = load_test.Results(calls=[_outcome(sender_lag_seconds=6.0)])
    results.live_view_errors = 2

    text, kept_up = load_test.summarize(results, calls=1, seconds=60)

    assert kept_up is False
    assert "2 failed loads" in text
    assert "could not keep real time" in text
