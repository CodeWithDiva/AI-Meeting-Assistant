"""Tests for the no-LLM fallback answer used by the chat and the voice assistant."""

from app.routers.chat import _fallback_answer

CONTEXT = (
    "Meeting Title: Sprint sync\n\n"
    "Summary: Planned the dashboard launch.\n\n"
    "Decisions: Launch the dashboard on Monday\n\n"
    "Action Items: Send the client report (Assigned to Ali, Due: Friday)"
)


def test_a_decision_question_is_answered_from_the_decisions() -> None:
    assert "Launch the dashboard on Monday" in _fallback_answer(CONTEXT, "What did we decide?")


def test_a_task_question_is_answered_from_the_action_items() -> None:
    answer = _fallback_answer(CONTEXT, "Ali ko kya kaam mila?")
    assert "Ali" in answer and "client report" in answer


def test_other_questions_fall_back_to_the_summary() -> None:
    assert _fallback_answer(CONTEXT, "How long was it?") == "Planned the dashboard launch."


def test_it_admits_when_the_meeting_has_nothing_to_go_on() -> None:
    assert "don't have enough" in _fallback_answer("Meeting Title: Empty", "What happened?")
