"""The prompt that turns a meeting transcript into structured notes.

Kept apart from the Ollama transport so it can be read, tuned and evaluated on
its own. Tuned against transcripts as speech recognition really writes them —
Urdu script, Roman Urdu, English, misspelled or re-scripted names, repeated
noise lines — not against tidy typed text.
"""

from __future__ import annotations

_JSON_SHAPE = """Return ONLY valid JSON with exactly these keys:
  "summary": (string) what the meeting was about and what came out of it
  "decisions": (array of strings) each decision the group actually settled on
  "action_items": (array of objects) each with:
      "assignee":    (string) the ONE person who must do it
      "assigned_by": (string or null) who gave them the task
      "task":        (string) what exactly they must do
      "deadline":    (string or null) when it is due, in the words used
"""

_RULES = """Rules:
- The transcript is labelled with speaker names like '[Ali]: ...'. That label
  is only who was SPEAKING. It is NOT automatically the assignee.
- CRITICAL — the assignee is the person NAMED IN THE SENTENCE as the one who
  must do the work, not the person who said it. Examples:
    '[Sara]: Ali will send the report'      -> assignee 'Ali', assigned_by 'Sara'
    '[Sara]: Bilal ko report bhejni hai'    -> assignee 'Bilal', assigned_by 'Sara'
    '[Sara]: علی رپورٹ بھیجے گا'             -> assignee 'Ali', assigned_by 'Sara'
    '[Sara]: I will send the report'        -> assignee 'Sara', assigned_by null
    '[Kalsoom]: میں بجٹ دیکھ لوں گی'         -> assignee 'Kalsoom', assigned_by null
  Only fall back to the speaker when they clearly took the task themselves
  ('I will...', 'main kar dunga', 'let me handle it', 'میں ... گا/گی').
- Copy the deadline in the speaker's own words ('Friday', 'kal tak',
  'اگلے ہفتے'). today / tomorrow / next week / 'Friday tak' ARE deadlines.
- Never invent a person who does not appear in the transcript or the list.
- One object per person per task. If three people were each given something,
  return three objects — even when they are all in ONE sentence.
- A decision is something the group AGREED ('we decided', 'faisla hua',
  'ہم نے فیصلہ کیا'). Do not list mere suggestions, questions, or things still
  being debated.
- If a task has no clear owner, set "assignee" to null rather than guessing.
- If nothing was decided or assigned, return empty arrays. Never invent
  content to fill them.
"""

_EXAMPLE = """Example (Roman Urdu — different people and topics from the meeting below,
copy only the SHAPE of the answer, never its names, tasks or dates):
  [Hamza]: Areeba ko invoices Thursday tak bhejni hain aur Bilal server backup kal tak check karega.
  [Hamza]: Humne faisla kiya ke office Saturday ko band rahega.
  -> {"summary": "Invoices, server backup and the Saturday office closure were discussed.",
      "decisions": ["Office closed on Saturday"],
      "action_items": [
        {"assignee": "Areeba", "assigned_by": "Hamza", "task": "Send the invoices", "deadline": "Thursday tak"},
        {"assignee": "Bilal", "assigned_by": "Hamza", "task": "Check the server backup", "deadline": "kal tak"}]}
"""


def build_notes_prompt(transcript: str, participants: list[str] | None, language: str) -> str:
    if language == "ur":
        language_rule = (
            "یہ میٹنگ اردو میں ہے۔ summary، decisions اور tasks سب اردو میں لکھیں۔ "
            "ناموں، اعداد اور انگریزی اصطلاحات (deadline, client, report) کو ویسے ہی رہنے دیں۔"
        )
    else:
        language_rule = (
            "Write the summary, decisions and tasks in English. "
            "If the meeting is in Roman Urdu, keep the speakers' own wording for "
            "names, dates and technical terms instead of translating them away."
        )

    roster = ""
    if participants:
        roster = (
            "\nPeople in this workspace (use these exact spellings for assignees "
            "whenever the transcript refers to them):\n  "
            + ", ".join(participants)
            + "\n"
        )

    recognition_note = (
        "The transcript was produced by speech recognition, not typed. Names and "
        "words are often misspelled, and a name may be written in Urdu script or "
        'in Latin letters ("تاسمیہ" and "Tasmia" are the same person). Match every '
        "name to the closest person in the list above and use THAT spelling. "
        "Ignore lines that are greetings, that repeat the same sentence again and "
        "again, or that make no sense — those are recognition errors, not "
        "decisions or tasks."
    )

    return (
        "You are an expert meeting analyst. Read the transcript and extract "
        "structured notes.\n\n"
        f"{language_rule}\n"
        f"{roster}\n"
        f"{recognition_note}\n\n"
        f"{_JSON_SHAPE}\n"
        f"{_RULES}\n"
        f"{_EXAMPLE}\n"
        "Transcript:\n\n" + transcript
    )
