"""A fast keyword check that runs before the AI, so crisis numbers go out even if the AI is slow or down."""

import re

_CRISIS_PATTERNS = [
    # English
    r"\bsuicid",
    r"\bkill (?:my ?self|me)\b",
    r"\bend (?:my|it all)\b",
    r"\bwant(?:s)? to die\b",
    r"\bdon'?t want to (?:live|be alive)\b",
    r"\bself[- ]?harm",
    r"\bhurt(?:ing)? myself\b",
    r"\boverdos",
    r"\bjump(?:ing)? off\b",
    r"\b(?:he|she|they) (?:hits?|beats?|hurts?) me\b",
    r"\bdomestic violence\b",
    r"\bnot safe at home\b",
    r"\bcan'?t breathe\b",
    r"\bchest pain\b",
    # Chinese
    r"自殺",
    r"想死",
    r"唔想(?:再)?(?:生存|活|生活落去)",
    r"不想活",
    r"輕生",
    r"了結",
    r"跳樓",
    r"傷害自己",
    r"𠝹手|割手|鎅手",
    r"家暴",
    r"被打|打我",
    r"透唔到氣|呼吸困難",
]
_CRISIS_RE = re.compile("|".join(_CRISIS_PATTERNS), re.IGNORECASE)

CRISIS_SLUGS = ["18111", "sbhk", "samaritans"]

_CRISIS_NOTE = {
    "en": "If you or someone else is in danger right now, please call 999.",
    "zh": "如果你或其他人現在有危險，請立即致電 999。",
}


def looks_like_crisis(text: str) -> bool:
    return bool(_CRISIS_RE.search(text or ""))


def crisis_note(language: str) -> str:
    return _CRISIS_NOTE["zh" if language == "zh" else "en"]


def guess_language(text: str) -> str:
    """Cheap guess used before the AI has answered (or if it fails)."""
    return "zh" if re.search(r"[一-鿿]", text or "") else "en"
