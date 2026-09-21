"""Offline, deterministic meeting-notes fallback.

This runs when Ollama is unreachable (or out of memory — see memory_guard). It
is deliberately conservative: it never invents decisions, people, or dates — it
only lifts sentences that already contain an explicit decision or assignment
marker.

Markers cover English, Urdu script, and Roman Urdu, because a Pakistani office
meeting mixes all three in a single sentence ("Ali, ye report Friday tak bhej
dena"). Transcript lines produced by the live bot are speaker-labelled as
`[Ali]: ...`; a first-person commitment ("I will…", "main kar dunga", "میں …
لوں گی") is assigned to that speaker, and a sentence that names nobody keeps the
speaker only as `assigned_by`.

Urdu script has no capital letters to tell a name from any other word, so an
Urdu-script subject is only accepted when it sounds like someone in
`known_names` (the meeting's roster plus the registered team).
"""

from __future__ import annotations

import re
from typing import Any

from app.services.name_matching import phonetic_keys

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?۔؟])\s+|\n+")
_WHITESPACE = re.compile(r"[^\S\n]+")
_SPEAKER_LINE = re.compile(r"^\[(?P<speaker>[^\]]{1,60})\]:\s*(?P<text>.*)$")
# "…the report by Friday, and Tasmia will prepare…" is two assignments.
_CLAUSE_SPLIT = re.compile(
    r",?\s+(?:and|aur|اور)\s+(?=(?:[A-Z][a-z]{1,30}|[؀-ۿ]{2,15})\s)"
)

_DECISION_MARKER = re.compile(
    r"\b(decided|agreed|approved|confirmed|finalized|will proceed|let'?s go with"
    r"|tay hua|tay kiya|faisla|final hua|manzoor)\b"
    r"|طے\s*ہوا|فیصلہ|منظور|اتفاق",
    re.IGNORECASE | re.UNICODE,
)

# Words that start a sentence like a name but are not one.
_NOT_A_NAME = {
    "we", "they", "he", "she", "it", "this", "that", "these", "those", "the", "a", "an",
    "everyone", "everybody", "someone", "anyone", "team", "all", "today", "tomorrow",
    "please", "also", "then", "so", "and", "but", "you", "there", "here", "who", "what",
}
_NOT_A_NAME_URDU = {
    "ہم", "وہ", "یہ", "آپ", "تم", "سب", "میں", "ہمیں", "یہاں", "وہاں", "کوئی", "ٹیم", "پھر", "اب", "آج", "کل",
}

# English: "Ali will send the report by Friday"  (the name must really be capitalised)
_ACTION_ENGLISH = re.compile(
    r"\b(?P<assignee>(?-i:[A-Z][a-z]{1,30}))\s+"
    r"(?:will|shall|should|needs? to|has to|is going to|must)\s+"
    r"(?P<task>[^.!?]+?)[.!?]?$",
    re.IGNORECASE,
)
# English: "I will check the budget today" -> the speaker
_FIRST_PERSON_ENGLISH = re.compile(
    r"\b(?:I\s+will|I'll|I\s+shall|I\s+am\s+going\s+to|I'm\s+going\s+to|let\s+me)\s+(?P<task>[^.!?]+?)[.!?]?$",
    re.IGNORECASE,
)
# Roman Urdu: "Ali ko report Friday tak bhejni hai"
_ACTION_ROMAN_URDU = re.compile(
    r"\b(?P<assignee>[A-Za-z]{2,30})\s+(?:ko|ne)\s+(?P<task>[^.!?]+?)"
    r"\s*(?:karna|karni|karna hai|karni hai|bhejna|bhejni|dena|deni|dekhna|dekhni|"
    r"banana|banani|likhna|likhni|share karna|karna h[ae]i?)\b(?P<rest>[^.!?]*)",
    re.IGNORECASE,
)
# Roman Urdu: "Tasmia presentation tayyar karegi", "Ali report bhejega"
_ACTION_ROMAN_FUTURE = re.compile(
    r"\b(?P<assignee>(?-i:[A-Z][a-z]{1,30}))\s+(?P<task>[^.!?]+?)\s+"
    r"(?:karega|karegi|bhejega|bhejegi|dega|degi|banayega|banayegi|dekhega|dekhegi|likhega|likhegi)\b"
    r"(?P<rest>[^.!?]*)",
    re.IGNORECASE,
)
# Roman Urdu, first person: "Main budget ki approval aaj hi dekh lungi"
_FIRST_PERSON_ROMAN = re.compile(
    r"\b(?:main|mein|mai)\s+(?P<task>[^.!?]+?)\s+"
    r"(?:lunga|lungi|dunga|dungi|karunga|karungi|kar\s+dunga|kar\s+dungi|bhejunga|bhejungi)\b(?P<rest>[^.!?]*)",
    re.IGNORECASE,
)
# Roman Urdu, direct request: "Tasmia, tum design ki files Wednesday tak share kar do"
_REQUEST_ROMAN = re.compile(
    r"\b(?P<assignee>(?-i:[A-Z][a-z]{1,30}))[,\s]+(?:tum|aap)\s+(?P<task>[^.!?]+?)\s+"
    r"(?:kar\s+do|kar\s+dena|kar\s+dijiye|karo|kijiye|bhej\s+do|bhej\s+dena)\b",
    re.IGNORECASE,
)
# Roman Urdu: "Ali aap ne kal tak client ko email bhejni hai"
_ASSIGNED_ROMAN = re.compile(
    r"\b(?P<assignee>(?-i:[A-Z][a-z]{1,30}))[,\s]+(?:aap|tum)\s+ne\s+(?P<task>[^.!?]+?)\s+"
    r"(?:bhejni|bhejna|karni|karna|dena|deni|banani|banana)\s+(?:hai|hain)\b",
    re.IGNORECASE,
)
_ASSIGNMENT_HINT = re.compile(
    r"\b(karna hai|karni hai|bhejna hai|bhejni hai|dekh lena|complete karna"
    r"|responsible|assign|task|action item|todo)\b"
    r"|کرنا\s*ہے|کرنی\s*ہے|بھیجنا\s*ہے|ذمہ\s*دار",
    re.IGNORECASE | re.UNICODE,
)

# Urdu script. "علی جمعہ تک رپورٹ بھیجے گا" / "علی کو رپورٹ بھیجنی ہے"
_URDU_FUTURE_END = re.compile(r"(?:گا|گی|گے)$")
_URDU_OBLIGATION = re.compile(
    r"^(?P<a>[؀-ۿ]{2,15})\s+(?:کو|نے)\s+(?P<t>.+?)\s+"
    r"(?:کرنا|کرنی|بھیجنا|بھیجنی|دینا|دینی|دیکھنا|دیکھنی|بنانا|بنانی|لکھنا|لکھنی|کرنے)\s*ہے"
)
_URDU_TASK_VERB = re.compile(
    r"بھیج|کر[ےنی]|تیار|دیکھ|دے|شیئر|چیک|بنا|لکھ|مکمل|اپڈیٹ|ڈال|رکھ|جمع|ٹھیک|بات|پڑھ|سن"
)

# Deadlines, in whichever language the speaker used them.
_DEADLINE = re.compile(
    r"(?P<d>"
    r"\b(?:by|before|on|until|till)\s+(?:next\s+|this\s+)?(?:mon|tues|wednes|thurs|fri|satur|sun)day\b"
    r"|\b(?:by|before)\s+(?:end of (?:the )?(?:day|week|month)|tomorrow|today|tonight|\d{1,2}(?::\d\d)?\s*(?:am|pm))"
    r"|\b(?:next|this)\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b(?:today|tomorrow|tonight)\b"
    r"|\b(?:aaj|kal|parso|agle\s+hafte|is\s+hafte|agle\s+mahine)(?:\s+tak)?\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|somwar|mangal|budh|jumerat|juma|hafta)\s+tak\b"
    r"|\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\b\d+\s*(?:baje|din|hafte)\b"
    r"|(?:اگلے\s+ہفتے|اس\s+ہفتے|آج|کل|پرسوں)(?:\s+تک)?"
    r"|(?:جمعہ|پیر|منگل|بدھ|جمعرات|ہفتہ|اتوار)(?:\s+تک|\s+کو)?"
    r")",
    re.IGNORECASE | re.UNICODE,
)


def _lines(transcript: str) -> list[tuple[str | None, str]]:
    """Split a transcript into (speaker, sentence) pairs."""
    output: list[tuple[str | None, str]] = []
    for raw_line in transcript.splitlines():
        line = _WHITESPACE.sub(" ", raw_line).strip()
        if not line:
            continue
        speaker = None
        match = _SPEAKER_LINE.match(line)
        if match:
            speaker = match.group("speaker").strip()
            line = match.group("text").strip()
        for sentence in _SENTENCE_BOUNDARY.split(line):
            sentence = sentence.strip(" -•\t")
            if sentence:
                output.append((speaker, sentence))
    return output


def _is_generic_speaker(speaker: str | None) -> bool:
    return not speaker or speaker.casefold() in {"speaker", "participant", "unknown"}


def analyze_with_fallback(
    transcript: str,
    known_names: list[str] | None = None,
) -> dict[str, Any]:
    """Return safe structured notes without calling an external service."""
    pairs = _lines(transcript)
    sentences = [text for _, text in pairs]
    summary = " ".join(sentences[:3]) if sentences else "No transcript content was provided."

    decisions: list[str] = []
    action_items: list[dict[str, str | None]] = []

    for speaker, sentence in pairs:
        if _DECISION_MARKER.search(sentence) and sentence not in decisions:
            decisions.append(sentence)

        for clause in _CLAUSE_SPLIT.split(sentence):
            item = _extract_action(clause.strip(), speaker, known_names)
            if item and not any(existing["task"] == item["task"] for existing in action_items):
                action_items.append(item)

    return {
        "summary": summary,
        "decisions": decisions,
        "action_items": action_items,
    }


def _split_deadline(text: str) -> tuple[str, str | None]:
    """Separate a trailing/embedded deadline phrase from the task wording."""
    match = _DEADLINE.search(text)
    if not match:
        return text.strip(" ,"), None
    # "by Friday" -> "Friday": the deadline is stored as the moment, not the preposition.
    deadline = re.sub(r"^(?:by|on)\s+", "", match.group("d").strip(), flags=re.IGNORECASE)
    task = (text[: match.start()] + " " + text[match.end():]).strip(" ,")
    task = re.sub(r"\s{2,}", " ", task)
    return task or text.strip(" ,"), deadline


def _item(assignee: str | None, speaker: str | None, task: str, deadline_hint: str | None = None) -> dict[str, str | None]:
    task, deadline = _split_deadline(task)
    if deadline is None and deadline_hint:
        _, deadline = _split_deadline(deadline_hint)
    return {
        "assignee": assignee,
        "assigned_by": speaker if not _is_generic_speaker(speaker) else None,
        "task": task,
        "deadline": deadline,
    }


def _known(name: str, known_names: list[str] | None) -> str | None:
    """The roster spelling of `name` if it is (or sounds like) exactly one known person."""
    if not known_names:
        return None
    for candidate in known_names:
        if candidate.casefold() == name.casefold():
            return candidate
    keys = phonetic_keys(name, min_len=1)
    if not keys:
        return None
    hits = [c for c in known_names if keys & phonetic_keys(c, min_len=1)]
    return hits[0] if len(hits) == 1 else None


def _extract_action(
    sentence: str, speaker: str | None, known_names: list[str] | None = None
) -> dict[str, str | None] | None:
    """Pull one action item out of a sentence, or None if it holds no assignment."""
    if sentence.endswith(("?", "؟")):
        return None  # a question is not a commitment

    urdu = _extract_urdu_action(sentence, speaker, known_names)
    if urdu:
        return urdu

    for pattern in (_ASSIGNED_ROMAN, _REQUEST_ROMAN):
        match = pattern.search(sentence)
        if match and match.group("assignee").casefold() not in _NOT_A_NAME:
            return _item(match.group("assignee").title(), speaker, match.group("task"))

    for pattern in (_ACTION_ENGLISH, _ACTION_ROMAN_URDU, _ACTION_ROMAN_FUTURE):
        match = pattern.search(sentence)
        if match and match.group("assignee").casefold() not in _NOT_A_NAME:
            rest = match.groupdict().get("rest")
            return _item(
                match.group("assignee").strip().title(), speaker,
                match.group("task").strip(" ,"), rest,
            )

    for pattern in (_FIRST_PERSON_ENGLISH, _FIRST_PERSON_ROMAN):
        match = pattern.search(sentence)
        if match and not _is_generic_speaker(speaker):
            return _item(speaker, None, match.group("task").strip(" ,"), match.groupdict().get("rest"))

    # An unmistakable assignment phrase with no parseable name still belongs in
    # the notes — the speaker is recorded, the owner left blank rather than guessed.
    if _ASSIGNMENT_HINT.search(sentence):
        return {
            "assignee": None,
            "assigned_by": speaker if not _is_generic_speaker(speaker) else None,
            "task": sentence,
            "deadline": None,
        }
    return None


def _extract_urdu_action(
    sentence: str, speaker: str | None, known_names: list[str] | None
) -> dict[str, str | None] | None:
    if not re.search(r"[؀-ۿ]", sentence):
        return None
    text = sentence.strip(" ۔.")

    obligation = _URDU_OBLIGATION.match(text)
    if obligation:
        name = obligation.group("a")
        if name not in _NOT_A_NAME_URDU:
            return _item(_known(name, known_names) or name, speaker, obligation.group("t"))

    tokens = text.split()
    if len(tokens) < 3 or not _URDU_FUTURE_END.search(tokens[-1]):
        return None
    if not _URDU_TASK_VERB.search(text):
        return None  # "موسم اچھا ہوگا" is a forecast, not a task
    subject, rest = tokens[0], " ".join(tokens[1:])
    if subject == "میں":
        # "I will ..." — the speaker, but only when we actually know who spoke.
        if _is_generic_speaker(speaker):
            return None
        return _item(_known(speaker, known_names) or speaker, None, rest)
    if subject in _NOT_A_NAME_URDU:
        return None
    # No capitals in Urdu: only trust a subject that is someone we know.
    person = _known(subject, known_names)
    if person is None:
        return None
    return _item(person, speaker, rest)
