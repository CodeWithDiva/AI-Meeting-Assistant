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


# ── Multi-meeting context (the workspace-wide "Ask Alina" panel) ─────────

MULTI_MEETING_CONTEXT = (
    "Meeting: Q1 budget review\n"
    "Summary: Capped the marketing budget.\n"
    "Decisions: Cap marketing spend at 50000 for Q1\n"
    "Action Items: File the finance report (Assigned to Ali, Status: pending, Due: Friday)\n"
    "\n"
    "Meeting: Sprint planning\n"
    "Summary: Planned the next sprint.\n"
    "Action Items: Migrate the database (Assigned to Sara, Status: done, Due: TBD)"
)


def test_a_task_question_over_several_meetings_lists_every_meetings_tasks() -> None:
    answer = _fallback_answer(MULTI_MEETING_CONTEXT, "What tasks are pending?")
    # Both meetings' Action Items must appear — a flat key→value scan over the
    # whole prompt would keep only the last meeting's and silently drop the first.
    assert "Q1 budget review" in answer and "File the finance report" in answer
    assert "Sprint planning" in answer and "Migrate the database" in answer


def test_a_decision_question_over_several_meetings_only_cites_the_one_with_a_decision() -> None:
    answer = _fallback_answer(MULTI_MEETING_CONTEXT, "What did we decide?")
    assert "Cap marketing spend at 50000 for Q1" in answer
    assert "Migrate the database" not in answer
