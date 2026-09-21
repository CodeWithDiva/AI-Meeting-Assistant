"""Notes/task extraction on transcripts as speech recognition really writes them.

Urdu meetings come out in Urdu script while accounts are registered in Latin
letters; a first-person commitment belongs to the speaker; one sentence can
hand out two tasks; and noise must never turn into invented work.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.ai.fallback import analyze_with_fallback
from app.ai.ollama import _fill_missing_deadlines, _snap_assigned_by, _snap_assignees
from app.ai.prompts import build_notes_prompt
from app.database import SessionLocal
from app.models import Meeting, Participant, User
from app.services.action_items import resolve_assignee
from app.services.meeting_analysis import build_roster
from app.services.name_matching import phonetic_keys

ROSTER = ["Ali", "Sara", "Tasmia", "Kalsoom"]


def _tasks(transcript: str, roster: list[str] | None = ROSTER) -> dict[str, dict]:
    notes = analyze_with_fallback(transcript, roster)
    return {(i["assignee"] or "?"): i for i in notes["action_items"]}


# ── Names across scripts ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("urdu", "latin"),
    [
        ("تاسمیہ", "Tasmia"),
        ("کلثوم", "Kalsoom"),
        ("سارہ", "Sarah"),
        ("احمد", "Ahmed"),
        ("محمد", "Muhammad"),
        ("وسیم", "Waseem"),
        ("فاطمہ", "Fatima"),
        ("زینب", "Zainab"),
    ],
)
def test_the_urdu_and_latin_spellings_of_a_name_share_a_key(urdu: str, latin: str) -> None:
    assert phonetic_keys(urdu) & phonetic_keys(latin)


def test_different_names_do_not_share_a_key() -> None:
    assert not phonetic_keys("Ali Raza") & phonetic_keys("Tasmia")
    assert not phonetic_keys("کلثوم") & phonetic_keys("Sara")


def test_a_lone_consonant_is_too_weak_to_trust_by_default() -> None:
    assert phonetic_keys("علی") == set()
    assert phonetic_keys("علی", min_len=1) == {"l"}


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def people(db):
    tag = uuid.uuid4().hex[:6]
    made = [
        User(email=f"tasmia.rauf{tag}@example.com", password_hash="x", full_name="Tasmia Rauf"),
        User(email=f"kalsoom{tag}@example.com", password_hash="x", full_name="Kalsoom Malik"),
    ]
    db.add_all(made)
    db.commit()
    yield made
    for user in made:
        db.delete(user)
    db.commit()


def test_a_name_said_in_urdu_script_finds_the_latin_account(db, people) -> None:
    assert resolve_assignee("تاسمیہ", db).id == people[0].id
    assert resolve_assignee("کلثوم", db).id == people[1].id


def test_a_name_that_sounds_like_two_people_is_left_unassigned(db, people) -> None:
    twin = User(email=f"tasmiya{uuid.uuid4().hex[:6]}@example.com", password_hash="x", full_name="Tasmiya Bibi")
    db.add(twin)
    db.commit()
    try:
        # Two accounts sound like "تاسمیہ": guessing wrong is worse than nobody.
        assert resolve_assignee("تاسمیہ", db) is None
    finally:
        db.delete(twin)
        db.commit()


def test_an_unrelated_name_stays_unresolved(db, people) -> None:
    assert resolve_assignee("بلال", db) is None


def test_the_roster_lists_the_team_not_just_the_zoom_display_names(db, people) -> None:
    meeting = Meeting(owner_id=people[0].id, title="roster", platform="zoom")
    db.add(meeting)
    db.flush()
    db.add(Participant(meeting_id=meeting.id, name="Um-e- Kalsoom", role="human"))
    db.commit()
    try:
        roster = build_roster(meeting.id, db)
        assert roster[0] == "Um-e- Kalsoom"  # attendees first
        assert "Tasmia Rauf" in roster and "Kalsoom Malik" in roster
        assert len(roster) == len(set(roster))
    finally:
        db.query(Participant).filter(Participant.meeting_id == meeting.id).delete()
        db.delete(meeting)
        db.commit()


def test_a_user_without_a_full_name_is_listed_by_their_email_prefix(db) -> None:
    tag = uuid.uuid4().hex[:6]
    user = User(email=f"bilal{tag}@example.com", password_hash="x", full_name=None)
    meeting_owner = user
    db.add(user)
    db.flush()
    meeting = Meeting(owner_id=meeting_owner.id, title="r2", platform="zoom")
    db.add(meeting)
    db.commit()
    try:
        assert f"bilal{tag}" in build_roster(meeting.id, db)
    finally:
        db.delete(meeting)
        db.delete(user)
        db.commit()


# ── Offline extractor ───────────────────────────────────────────────────


def test_two_assignments_in_one_english_sentence_become_two_tasks() -> None:
    tasks = _tasks(
        "[Sara]: Ali will send the report by Friday, and Tasmia will prepare "
        "the presentation for the client meeting next week."
    )
    assert "report" in tasks["Ali"]["task"] and tasks["Ali"]["deadline"].lower().endswith("friday")
    assert "presentation" in tasks["Tasmia"]["task"] and "next week" in tasks["Tasmia"]["deadline"]
    assert tasks["Ali"]["assigned_by"] == "Sara"


def test_a_sentence_that_merely_starts_with_a_capital_word_is_not_a_task() -> None:
    # "Today we will review…" used to make "Today" the assignee.
    notes = analyze_with_fallback(
        "[Sara]: Today we will review the project status.\n"
        "[Sara]: The budget must be approved before that."
    )
    assert notes["action_items"] == []


def test_first_person_commitments_belong_to_the_speaker() -> None:
    tasks = _tasks("[Kalsoom]: I will check the budget approval today.")
    assert tasks["Kalsoom"]["deadline"] == "today"
    assert tasks["Kalsoom"]["assigned_by"] is None

    roman = _tasks("[Kalsoom]: Main budget ki approval aaj hi dekh lungi.")
    assert roman["Kalsoom"]["deadline"].startswith("aaj")


def test_roman_urdu_assignments_in_their_common_shapes() -> None:
    tasks = _tasks(
        "[Sara]: Ali ko report Friday tak bhejni hai aur Tasmia presentation tayyar karegi client meeting ke liye agle hafte tak."
    )
    assert "report" in tasks["Ali"]["task"] and tasks["Ali"]["deadline"].lower().startswith("friday")
    assert "presentation" in tasks["Tasmia"]["task"]

    request = _tasks("[Speaker]: Tasmia, tum design ki files Wednesday tak share kar do.")
    assert "design" in request["Tasmia"]["task"] and request["Tasmia"]["deadline"].lower().startswith("wednesday")

    aap_ne = _tasks("[Speaker]: Ali aap ne kal tak client ko email bhejni hai.")
    assert "email" in aap_ne["Ali"]["task"] and aap_ne["Ali"]["deadline"].startswith("kal")


def test_urdu_script_assignments_resolve_to_the_roster_spelling() -> None:
    tasks = _tasks(
        "[Sara]: علی جمعہ تک رپورٹ بھیجے گا اور تاسمیہ اگلے ہفتے کلائنٹ میٹنگ کے لئے پریزنٹیشن تیار کرے گی\n"
        "[کلثوم]: میں آج بجٹ کی منظوری دیکھ لوں گی"
    )
    assert set(tasks) == {"Ali", "Tasmia", "Kalsoom"}
    assert "رپورٹ" in tasks["Ali"]["task"] and tasks["Ali"]["deadline"].startswith("جمعہ")
    assert "ہفتے" in tasks["Tasmia"]["deadline"]
    assert tasks["Kalsoom"]["deadline"].startswith("آج")


def test_an_urdu_subject_nobody_knows_is_not_guessed_at() -> None:
    # No capital letters in Urdu: without a roster there is nothing to say
    # "موسم" (weather) isn't a person.
    assert analyze_with_fallback("[Sara]: موسم کل اچھا ہوگا", None)["action_items"] == []
    assert analyze_with_fallback("[Sara]: علی رپورٹ بھیجے گا", None)["action_items"] == []


def test_urdu_obligation_form_names_its_owner() -> None:
    tasks = _tasks("[Sara]: علی کو رپورٹ بھیجنی ہے")
    assert "Ali" in tasks and "رپورٹ" in tasks["Ali"]["task"]


def test_questions_and_noise_never_become_tasks() -> None:
    notes = analyze_with_fallback(
        "[Speaker]: Alina. Are you listening Alina?\n"
        "[Speaker]: The user can do this.\n"
        "[Speaker]: Will Ali send the report?\n"
        "[Speaker]: And they are as soon as possible.",
        ROSTER,
    )
    assert notes["action_items"] == []


def test_a_decision_is_still_picked_up_in_each_language() -> None:
    notes = analyze_with_fallback(
        "[Sara]: We decided to move the deployment to Monday.\n"
        "[Sara]: Humne faisla kiya hai ke deployment Monday ko hogi.\n"
        "[Sara]: ہم نے فیصلہ کیا ہے کہ ڈیپلامنٹ پیر کو ہوگی",
        ROSTER,
    )
    assert len(notes["decisions"]) == 3


# ── Snapping the model's assignees to real people ───────────────────────


def test_a_model_assignee_in_urdu_script_is_snapped_to_the_roster_spelling() -> None:
    notes = {"action_items": [{"assignee": "تاسمیہ", "task": "x"}, {"assignee": "tasmia", "task": "y"}]}
    _snap_assignees(notes, ROSTER, "تاسمیہ tasmia")
    assert [i["assignee"] for i in notes["action_items"]] == ["Tasmia", "Tasmia"]


def test_an_assignee_that_appears_nowhere_is_treated_as_invented() -> None:
    notes = {"action_items": [{"assignee": "Zubair", "task": "x"}, {"assignee": "Ali", "task": "y"}]}
    _snap_assignees(notes, ROSTER, "[Sara]: Ali will send it")
    assert [i["assignee"] for i in notes["action_items"]] == [None, "Ali"]


def test_a_name_in_the_transcript_but_not_the_roster_is_kept() -> None:
    notes = {"action_items": [{"assignee": "Zubair", "task": "x"}]}
    _snap_assignees(notes, ROSTER, "[Sara]: Zubair will send it")
    assert notes["action_items"][0]["assignee"] == "Zubair"


# ── The prompt ──────────────────────────────────────────────────────────


def test_the_prompt_carries_the_roster_the_recognition_warning_and_an_example() -> None:
    prompt = build_notes_prompt("[Sara]: hi", ["Ali", "Tasmia"], "en")
    assert "Ali, Tasmia" in prompt
    assert "speech recognition" in prompt
    assert "Example (Roman Urdu" in prompt
    assert prompt.rstrip().endswith("[Sara]: hi")


def test_an_urdu_meeting_is_asked_to_answer_in_urdu() -> None:
    assert "اردو" in build_notes_prompt("x", None, "ur")
    assert "in English" in build_notes_prompt("x", None, "en")


# ── Recovering what the model dropped ───────────────────────────────────

TRANSCRIPT = (
    "[Sara]: Ali will send the report by Friday, and Tasmia will prepare the presentation next week.\n"
    "[Kalsoom]: I will check the budget approval today.\n"
    "[Sara]: Please remind Bilal about the invoices on Monday."
)


def test_a_dropped_deadline_is_recovered_from_the_owners_own_sentence() -> None:
    notes = {"action_items": [
        {"assignee": "Ali", "task": "Send the report", "deadline": None},
        {"assignee": "Tasmia", "task": "Prepare the presentation", "deadline": None},
    ]}
    _fill_missing_deadlines(notes, TRANSCRIPT)
    assert [i["deadline"] for i in notes["action_items"]] == ["Friday", "next week"]


def test_a_first_person_commitment_gets_its_deadline_too() -> None:
    notes = {"action_items": [{"assignee": "Kalsoom", "task": "Check the budget", "deadline": None}]}
    _fill_missing_deadlines(notes, TRANSCRIPT)
    assert notes["action_items"][0]["deadline"] == "today"


def test_a_deadline_is_never_borrowed_from_a_sentence_about_someone_else() -> None:
    # "Monday" belongs to the invoices reminder; Bilal is only mentioned in it.
    notes = {"action_items": [{"assignee": "Bilal", "task": "Invoices", "deadline": None}]}
    _fill_missing_deadlines(notes, TRANSCRIPT)
    assert notes["action_items"][0]["deadline"] is None


def test_a_deadline_the_model_did_give_is_left_alone() -> None:
    notes = {"action_items": [{"assignee": "Ali", "task": "Send the report", "deadline": "kal tak"}]}
    _fill_missing_deadlines(notes, TRANSCRIPT)
    assert notes["action_items"][0]["deadline"] == "kal tak"


def test_nobody_is_recorded_as_having_assigned_a_task_to_themselves() -> None:
    notes = {"action_items": [
        {"assignee": "Kalsoom", "assigned_by": "کلثوم", "task": "x"},
        {"assignee": "Ali", "assigned_by": "sara", "task": "y"},
    ]}
    _snap_assigned_by(notes, ROSTER)
    assert [i["assigned_by"] for i in notes["action_items"]] == [None, "Sara"]
