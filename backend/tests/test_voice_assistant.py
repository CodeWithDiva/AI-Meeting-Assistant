from app.services.voice_assistant import AvaVoiceAssistant


def test_ava_wake_word_supports_english_and_urdu() -> None:
    assistant = AvaVoiceAssistant(meeting_id=1)
    assert assistant._question_after_wake_word("Ava, what did we decide?") == "what did we decide"
    assert assistant._question_after_wake_word("اوا، کیا فیصلہ ہوا؟") == "کیا فیصلہ ہوا"
    assert assistant._question_after_wake_word("The team discussed the roadmap.") is None
