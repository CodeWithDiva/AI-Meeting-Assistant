import pytest

from app.services.voice_assistant import AvaVoiceAssistant, VoiceReply, _edit_distance_le1


@pytest.fixture()
def alina() -> AvaVoiceAssistant:
    """The assistant under its default name, pinned so env changes can't shift it."""
    return AvaVoiceAssistant(meeting_id=1, wake_word="alina")


def test_wake_word_supports_english_and_urdu(alina: AvaVoiceAssistant) -> None:
    assert alina._question_after_wake_word("Alina, what did we decide?") == "what did we decide"
    assert alina._question_after_wake_word("الینا، کیا فیصلہ ہوا؟") == "کیا فیصلہ ہوا"
    assert alina._question_after_wake_word("The team discussed the roadmap.") is None


def test_the_wake_word_follows_the_configured_name() -> None:
    # Renaming the bot renames what it answers to — the old name stops working.
    ava = AvaVoiceAssistant(meeting_id=1, wake_word="ava")
    assert ava._question_after_wake_word("Ava, what did we decide?") == "what did we decide"
    assert ava._question_after_wake_word("Alina, what did we decide?") is None


# ── Fuzzy wake-word matching ────────────────────────────────────────────
# Whisper on a weak/CPU model mishears a short name often enough that a strict
# substring match silently drops the wake-word — these lock in the tolerance
# added for that, and that it doesn't start firing on unrelated words.


@pytest.mark.parametrize(
    "text",
    [
        "Aleena kya faisla hua",
        "Alena batao kya hua",
        "Elina can you help",
        "alina, summary do",
        "Alinaa what do you think",
    ],
)
def test_common_mishearings_still_trigger(alina: AvaVoiceAssistant, text: str) -> None:
    assert alina._question_after_wake_word(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "We need to align on this",
        "Let us realign the plan",
        "I will send the alignment doc",
        "The meeting is about Linux servers",
        "We need to move the meeting to Monday",
    ],
)
def test_unrelated_words_do_not_trigger(alina: AvaVoiceAssistant, text: str) -> None:
    # A false wake-up mid-meeting is worse than a missed one, so near-miss
    # ordinary words must stay silent.
    assert alina._question_after_wake_word(text) is None


def test_edit_distance_helper() -> None:
    assert _edit_distance_le1("alina", "alina")
    assert _edit_distance_le1("alina", "elina")   # substitution
    assert _edit_distance_le1("alina", "alinaa")  # insertion
    assert _edit_distance_le1("alina", "alna")    # deletion
    assert not _edit_distance_le1("alina", "align")
    assert not _edit_distance_le1("alina", "alignment")


# ── Echo guard ──────────────────────────────────────────────────────────
# The spoken reply plays into the meeting and comes straight back through the
# capture, so it is transcribed like anyone else's speech.


def test_the_assistant_ignores_its_own_reply_coming_back(alina: AvaVoiceAssistant) -> None:
    alina.last_reply = VoiceReply(
        question="q", answer="The team agreed to launch the dashboard on Monday.", audio_wav=b""
    )
    assert alina._is_own_echo("the team agreed to launch the dashboard on monday")


def test_a_new_question_right_after_a_reply_still_gets_through(alina: AvaVoiceAssistant) -> None:
    alina.last_reply = VoiceReply(
        question="q", answer="The team agreed to launch the dashboard on Monday.", audio_wav=b""
    )
    # Shares a word or two with the last answer, but is plainly a new question.
    assert not alina._is_own_echo("Alina, when is the client report due?")


def test_no_previous_reply_means_nothing_is_an_echo(alina: AvaVoiceAssistant) -> None:
    assert not alina._is_own_echo("the team agreed to launch the dashboard on monday")
