"""Reads a plain answer to the sharing question ("Can we share a short note...? Reply YES or NO").
Runs in code so a "sure" or "可以" always counts, whatever the AI makes of the rest of the message."""

import re

_YES = (
    "yes", "yeah", "yep", "yup", "ya", "yah", "sure", "ok", "okay", "of course", "fine", "go ahead",
    "please do", "please share", "sounds good", "alright", "no problem",
    "可以", "好", "得", "冇問題", "無問題", "没问题", "係", "是", "行", "ok",
)
_NO = (
    "no", "nope", "nah", "don't", "dont", "do not", "please don't", "not now", "rather not", "i'd rather not",
    "唔好", "唔可以", "不可以", "不要", "唔要", "唔使", "不用", "否",
)
_UNSURE = ("not sure", "unsure", "maybe", "唔知", "不知道", "諗下", "考慮")


def _starts_with(text: str, words) -> bool:
    for word in words:
        if re.match(r"[一-鿿]", word):
            if text.startswith(word):
                return True
        elif re.match(rf"{re.escape(word)}(?![a-z])", text):
            return True
    return False


def read_answer(text: str) -> str | None:
    """'yes', 'no', or None when the message doesn't start with a clear answer."""
    cleaned = re.sub(r"^[\W_]+", "", (text or "").strip().lower())
    if not cleaned or _starts_with(cleaned, _UNSURE):
        return None
    if _starts_with(cleaned, _NO):
        return "no"
    if _starts_with(cleaned, _YES):
        return "yes"
    if re.search(r"don'?t share|do not share|唔好分享|不要分享", cleaned):
        return "no"
    return None
