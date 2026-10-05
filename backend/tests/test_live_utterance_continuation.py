"""Live audio is transcribed chunk by chunk, but a sentence cut by the
buffer's time limit stays one utterance that grows as speech continues; a
pause (or the end of the stream) closes it."""

import struct
from itertools import count

import pytest

from app.ai.asr.provider import ASRProvider, ASRResult
from app.ai.language.provider import (
    LanguageIdentificationProvider,
    LanguageIdentificationResult,
    LanguageSpan,
)
from app.ai.speaker.provider import (
    DiarizationProvider,
    DiarizedSegment,
    RoleIdentificationProvider,
    SpeakerRole as AISpeakerRole,
    SpeakerRoleAssignment,
)
from app.domain.utterance import SpeakerRole, Utterance
from app.services.audio_chunking_service import AudioChunk
from app.services.audio_processing_pipeline import (
    AudioPipelineError,
    AudioProcessingPipeline,
)
from app.services.conversation_service import ConversationService
from app.services.in_memory_conversation_repository import InMemoryConversationRepository
from app.services.live_chunk_processing_service import LiveChunkProcessingService
from app.services.telephony_audio_buffer import TelephonyAudioBuffer

CALL_ID = "call-1"
RESULT = object()


class ScriptedASR(ASRProvider):
    """Returns the next scripted transcript per chunk ("" = silence)."""

    def __init__(self, transcripts: list[str]) -> None:
        self._transcripts = list(transcripts)

    def transcribe(self, audio):
        text = self._transcripts.pop(0)
        return ASRResult(text, "en", 0.1, 2.9, None)


class EnglishOnly(LanguageIdentificationProvider):
    def identify(self, text):
        return LanguageIdentificationResult([LanguageSpan("en", 0.9)])


class OneSpeakerPerChunk(DiarizationProvider):
    # Labels are chunk-local, as with pyannote: always "SPEAKER_00".
    def diarize(self, audio):
        return [DiarizedSegment("SPEAKER_00", 0.0, 3.0)]


class ScriptedRoles(RoleIdentificationProvider):
    def __init__(self, roles: list[AISpeakerRole] | None = None) -> None:
        self._roles = list(roles or [])

    def identify_roles(self, segments):
        role = self._roles.pop(0) if self._roles else AISpeakerRole.UNKNOWN
        return [SpeakerRoleAssignment("SPEAKER_00", role)]


class ConversationWorkflow:
    """Stores utterances the way the live workflow does (no AI analysis)."""

    def __init__(self, conversations: ConversationService) -> None:
        self._conversations = conversations

    def process_utterance(self, call_id, utterance):
        self._conversations.add_utterance(call_id, utterance)
        return RESULT

    def process_utterance_update(self, call_id, utterance):
        self._conversations.update_latest_utterance(call_id, utterance)
        return RESULT


class Call:
    def __init__(self, transcripts: list[str], roles: list[AISpeakerRole] | None = None) -> None:
        self.conversations = ConversationService(InMemoryConversationRepository())
        self.conversations.create_conversation(CALL_ID)
        ids = count(1)
        self.pipeline = AudioProcessingPipeline(
            ScriptedASR(transcripts),
            EnglishOnly(),
            OneSpeakerPerChunk(),
            ScriptedRoles(roles),
            ConversationWorkflow(self.conversations),
            id_factory=lambda: f"utt-{next(ids)}",
        )
        self.service = LiveChunkProcessingService(lambda call_id: self.pipeline)
        self._sequence = 0
        self._offset = 0.0

    def chunk(self, *, continues: bool, pause: bool, final: bool = False, seconds: float = 3.0):
        chunk = AudioChunk(
            sequence=self._sequence,
            start_time=self._offset,
            end_time=self._offset + seconds,
            audio=b"wav",
            is_final=final,
            ends_on_pause=pause,
            continues_previous=continues,
        )
        self._sequence += 1
        self._offset += seconds
        return self.service.process_chunk(CALL_ID, chunk)

    @property
    def utterances(self) -> tuple[Utterance, ...]:
        return self.conversations.get_conversation(CALL_ID).utterances

    @property
    def texts(self) -> list[str]:
        return [u.transcript for u in self.utterances]


def test_continuous_speech_grows_one_utterance():
    call = Call([
        "This is Rohit Kulkarni. I'm calling about",
        "my Hyundai Creta registration",
        "number MH 12 CD 5678.",
    ])

    call.chunk(continues=False, pause=False)
    first = call.utterances[0]
    call.chunk(continues=True, pause=False)
    # Shown progressively: the same utterance already holds both chunks.
    assert call.texts == ["This is Rohit Kulkarni. I'm calling about my Hyundai Creta registration"]
    call.chunk(continues=True, pause=True)

    [utterance] = call.utterances
    assert utterance.transcript == (
        "This is Rohit Kulkarni. I'm calling about my Hyundai Creta "
        "registration number MH 12 CD 5678."
    )
    assert utterance.utterance_id == first.utterance_id
    # Starts where the speech started, ends where the last chunk's speech ends.
    assert utterance.start_time == pytest.approx(0.1)
    assert utterance.end_time == pytest.approx(6.0 + 2.9)


def test_speech_after_a_pause_is_a_new_utterance():
    call = Call(["I need help with my registration.", "I also have another issue."])

    call.chunk(continues=False, pause=True)
    call.chunk(continues=False, pause=True)

    assert call.texts == ["I need help with my registration.", "I also have another issue."]
    assert len({u.utterance_id for u in call.utterances}) == 2


def test_a_pause_closes_the_utterance_even_if_the_next_chunk_claims_to_continue():
    call = Call(["I need help with my registration.", "I also have another issue."])

    call.chunk(continues=False, pause=True)
    call.chunk(continues=True, pause=False)

    assert len(call.utterances) == 2


def test_the_time_limit_is_not_the_end_of_an_utterance():
    call = Call(["Thank you, Mr.", "Kulkarni, I can see your car"])

    call.chunk(continues=False, pause=False)  # cut by the 3 s limit
    call.chunk(continues=True, pause=True)

    assert call.texts == ["Thank you, Mr. Kulkarni, I can see your car"]


@pytest.mark.parametrize(
    ("first", "second", "joined"),
    [
        ("calling about", "about my Hyundai", "calling about my Hyundai"),
        ("Thank you, Mr.", "Mr. Kulkarni, I can see", "Thank you, Mr. Kulkarni, I can see"),
        ("my Hyundai Creta", "Hyundai Creta registration", "my Hyundai Creta registration"),
        ("calling about", "About my Hyundai", "calling about my Hyundai"),
        ("calling about", "my Hyundai", "calling about my Hyundai"),
        ("calling about", "about", "calling about"),
    ],
)
def test_words_heard_in_both_chunks_are_not_repeated(first, second, joined):
    call = Call([first, second])

    call.chunk(continues=False, pause=False)
    call.chunk(continues=True, pause=True)

    assert call.texts == [joined]


def test_an_update_is_never_also_stored_as_a_new_utterance():
    class NoResultWorkflow(ConversationWorkflow):
        def process_utterance_update(self, call_id, utterance):
            super().process_utterance_update(call_id, utterance)
            return None

    call = Call(["I'm calling about", "my Hyundai", "Creta."])
    call.pipeline._workflow_service = NoResultWorkflow(call.conversations)

    call.chunk(continues=False, pause=False)
    call.chunk(continues=True, pause=False)
    call.chunk(continues=True, pause=True)

    assert call.texts == ["I'm calling about my Hyundai Creta."]


def test_different_known_roles_are_never_merged():
    call = Call(
        ["Registration MH 12 CD 5678.", "Thank you, Mr. Kulkarni."],
        roles=[AISpeakerRole.CUSTOMER, AISpeakerRole.ICR],
    )

    call.chunk(continues=False, pause=False)
    call.chunk(continues=True, pause=True)

    assert [u.speaker_role for u in call.utterances] == [SpeakerRole.CUSTOMER, SpeakerRole.ICR]


def test_an_unknown_role_does_not_split_a_known_speaker():
    call = Call(
        ["This is Rohit Kulkarni.", "I'm calling about my car."],
        roles=[AISpeakerRole.CUSTOMER, AISpeakerRole.UNKNOWN],
    )

    call.chunk(continues=False, pause=False)
    call.chunk(continues=True, pause=True)

    [utterance] = call.utterances
    assert utterance.speaker_role is SpeakerRole.CUSTOMER


def test_the_final_chunk_is_kept_and_closes_the_utterance():
    call = Call(["I'm calling about", "my Hyundai Creta."])

    call.chunk(continues=False, pause=False)
    call.chunk(continues=True, pause=False, final=True)

    assert call.texts == ["I'm calling about my Hyundai Creta."]
    assert call.service.is_completed(CALL_ID)


def test_nothing_continues_an_utterance_after_it_is_closed():
    call = Call(["I'm calling about", "my Hyundai Creta.", "A new topic."])
    call.chunk(continues=False, pause=False)
    call.pipeline.process_audio(
        CALL_ID, b"wav", 3.0, continues_previous=True, ends_utterance=True
    )

    call.pipeline.process_audio(CALL_ID, b"wav", 6.0, continues_previous=True)

    assert call.texts == ["I'm calling about my Hyundai Creta.", "A new topic."]


def test_a_failed_chunk_never_extends_a_stale_utterance():
    call = Call(["I'm calling about", "", "my Hyundai Creta."])

    call.chunk(continues=False, pause=False)
    with pytest.raises(AudioPipelineError):
        call.chunk(continues=True, pause=False)  # empty transcript
    call.chunk(continues=True, pause=True)

    # Starting afresh is safe; text is never attached to the wrong utterance.
    assert call.texts == ["I'm calling about", "my Hyundai Creta."]


def test_an_utterance_added_in_between_is_never_overwritten():
    call = Call(["I'm calling about", "my Hyundai Creta."])
    call.chunk(continues=False, pause=False)
    other = Utterance("typed-1", "Typed note", SpeakerRole.ICR, ("en",), 2.95, 2.99)
    call.conversations.add_utterance(CALL_ID, other)

    call.chunk(continues=True, pause=True)

    assert call.texts == ["I'm calling about", "Typed note", "my Hyundai Creta."]


def test_an_utterance_is_not_kept_open_forever():
    call = Call([f"part {index}" for index in range(15)])

    call.chunk(continues=False, pause=False)
    for _ in range(14):
        call.chunk(continues=True, pause=False)

    # 45 s of unbroken speech (e.g. line noise hiding every pause) is split.
    assert 1 < len(call.utterances) < 15
    assert all(u.duration <= 30.0 for u in call.utterances)


def test_without_continuation_every_chunk_is_its_own_utterance():
    # Uploaded recordings and other non-live callers keep the old behaviour.
    call = Call(["first part", "second part"])

    call.pipeline.process_audio(CALL_ID, b"wav", 0.0)
    call.pipeline.process_audio(CALL_ID, b"wav", 3.0)

    assert call.texts == ["first part", "second part"]


# --- End to end from telephony frames ---

RATE = 8000
FRAME = 0.02


def _frame(level: int) -> bytes:
    samples = int(RATE * FRAME)
    return struct.pack(f"<{samples}h", *([level, -level] * (samples // 2)))


def test_frames_to_utterances_with_a_three_second_limit():
    # 9 s of unbroken speech (three chunks cut by the limit), a 1 s pause,
    # then 1.6 s of speech.
    call = Call([
        "This is Rohit Kulkarni. I'm calling about",
        "about my Hyundai Creta registration",
        "number MH 12 CD 5678.",
        "Thank you, Mr. Kulkarni.",
    ])
    buffer = TelephonyAudioBuffer(
        sample_rate=RATE,
        flush_after_seconds=3.0,
        pause_seconds=0.6,
        min_speech_seconds=1.5,
        silence_rms=350,
    )
    frames = [_frame(3000)] * 450 + [_frame(50)] * 50 + [_frame(3000)] * 80 + [_frame(50)] * 50
    for sequence, frame in enumerate(frames, start=1):
        buffer.accept(sequence, frame)
        chunk = buffer.flush()
        if chunk is not None:
            call.service.process_chunk(
                CALL_ID,
                AudioChunk(
                    sequence=call._sequence,
                    start_time=chunk.start_time,
                    end_time=chunk.end_time,
                    audio=chunk.audio,
                    ends_on_pause=chunk.ends_on_pause,
                    continues_previous=chunk.continues_previous,
                ),
            )
            call._sequence += 1

    assert call.texts == [
        "This is Rohit Kulkarni. I'm calling about my Hyundai Creta registration "
        "number MH 12 CD 5678.",
        "Thank you, Mr. Kulkarni.",
    ]
