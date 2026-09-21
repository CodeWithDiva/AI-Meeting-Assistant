"""Match a spoken/transcribed name to a registered one across scripts.

The live transcript is written by Whisper in whatever script it heard the
meeting in, so an Urdu meeting names people in Urdu script ("تاسمیہ") while
employees are registered in Latin letters ("Tasmia"). Comparing those as plain
strings never matches, so tasks assigned aloud in Urdu reached nobody.

`phonetic_key` reduces a name to a rough consonant skeleton that is the same
for the Urdu and Latin spellings of one name:

    تاسمیہ / Tasmia / Tasmiya      -> "tsm"
    کلثوم / Kalsoom / Kalsum       -> "klsm"
    سارہ / Sara / Sarah            -> "sr"
    احمد / Ahmed / Ahmad           -> "hmd"

It is deliberately coarse, so it is only ever a *tiebreaker after exact
matching fails*, and only when exactly one registered person fits — a task
assigned to the wrong person is worse than an unassigned one.
"""

from __future__ import annotations

import re

# Urdu/Arabic letters -> the Latin consonant they contribute ("" = vowel/silent).
_URDU_TO_KEY = {
    "ا": "", "آ": "", "أ": "", "ع": "", "ئ": "", "ء": "", "ے": "", "ی": "", "ى": "",
    "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ط": "t",
    "ث": "s", "س": "s", "ص": "s", "ش": "s",
    "ز": "s", "ذ": "s", "ض": "s", "ظ": "s", "ژ": "s",
    "ج": "j", "چ": "c",
    "ح": "h", "ہ": "h", "ھ": "h", "ه": "h", "ة": "h",
    "خ": "k", "ک": "k", "ك": "k", "ق": "k",
    "گ": "g", "غ": "g",
    "د": "d", "ڈ": "d",
    "ر": "r", "ڑ": "r",
    "ف": "f",
    "ل": "l", "م": "m", "ن": "n", "ں": "n",
    "و": "w",  # a vowel except at the start of a name; handled below
}

# Latin digraphs first, then single letters.
_LATIN_DIGRAPHS = [
    ("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("ph", "f"),
    ("th", "t"), ("dh", "d"), ("zh", "s"),
]
_LATIN_TO_KEY = {
    "b": "b", "p": "p", "t": "t", "s": "s", "z": "s", "c": "k", "k": "k", "q": "k",
    "j": "j", "h": "h", "g": "g", "d": "d", "r": "r", "f": "f", "l": "l", "m": "m",
    "n": "n", "v": "w", "w": "w", "x": "k",
}

_DIACRITICS = re.compile(r"[ً-ٰٟـۖ-ۭ]")
_HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "sir", "madam", "engr", "sahab", "sahib",
    "saab", "bhai", "baji", "apa", "janab", "صاحب", "جناب", "سر", "بھائی", "باجی",
}
_SPLIT = re.compile(r"[\s.,_\-@()\[\]\"']+")


def _key_for_token(token: str) -> str:
    token = _DIACRITICS.sub("", token.casefold())
    out: list[str] = []
    i = 0
    while i < len(token):
        ch = token[i]
        if ch in _URDU_TO_KEY:
            key = _URDU_TO_KEY[ch]
            # `و` is the vowel in "کلثوم" but the consonant in "وسیم".
            if ch == "و":
                key = "w" if i == 0 else ""
            out.append(key)
            i += 1
            continue
        pair = token[i : i + 2]
        digraph = next((short for long, short in _LATIN_DIGRAPHS if long == pair), None)
        if digraph is not None:
            out.append(_LATIN_TO_KEY.get(digraph, digraph))
            i += 2
            continue
        if ch in _LATIN_TO_KEY:
            # A leading "w"/"v" is a consonant; elsewhere it is mostly a vowel
            # sound in these names ("Kalsoom", "Naveed" is the exception we accept).
            out.append(_LATIN_TO_KEY[ch])
        i += 1  # vowels (a e i o u y) and anything else contribute nothing

    # Collapse doubled letters ("Sammy" -> "sm"), drop a trailing silent "h"
    # ("Sarah", "تاسمیہ").
    collapsed: list[str] = []
    for key in out:
        if key and (not collapsed or collapsed[-1] != key):
            collapsed.append(key)
    if len(collapsed) > 1 and collapsed[-1] == "h":
        collapsed.pop()
    return "".join(collapsed)


def phonetic_keys(name: str | None, min_len: int = 2) -> set[str]:
    """Skeleton of every name token that is long enough to be distinctive.

    `min_len=1` keeps single-consonant skeletons ("علی" / "Ali" -> "l"). Too
    weak to trust against a whole workspace, but fine when comparing against a
    handful of known people and only accepting a *unique* hit.
    """
    if not name:
        return set()
    keys = set()
    for token in _SPLIT.split(name):
        if not token or token.casefold() in _HONORIFICS:
            continue
        key = _key_for_token(token)
        if len(key) >= min_len:
            keys.add(key)
    return keys
