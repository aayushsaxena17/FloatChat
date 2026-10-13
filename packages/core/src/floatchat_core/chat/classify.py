"""Rule classification before any model call (ADR-0072): greetings and help need no model."""

import re

GREETING = re.compile(
    r"^\s*(hi|hello|hey|hiya|yo|good (morning|afternoon|evening)|greetings|howdy|"
    r"thanks|thank you|cheers|bye|goodbye)[\s!.,]*(floatchat|there|bot|assistant)?[\s!.,]*$",
    re.IGNORECASE,
)
HELP = re.compile(
    r"^\s*(help|/help|\?+)\s*$|what can you (do|answer)|how (do|can|should) i (use|ask)|"
    r"what (questions|kind of questions|sort of questions)|what (data|datasets?) (do you|is) "
    r"(have|available)|how much data|what data|which data|data (is )?(available|avail?lable|"
    r"do you have)|what (is )?(the )?coverage|which regions|what regions|what variables|"
    r"what are you",
    re.IGNORECASE,
)

GREETING_TEXT = (
    "Hello. Ask me about Argo temperature, salinity and pressure observations, for example "
    "'monthly mean temperature in the Arabian Sea from January to March 2025 in the upper "
    "100 dbar'."
)


def classify(text: str) -> str:
    """``greeting``, ``help`` or ``query`` (everything else goes to the planner)."""
    if len(text) <= 60 and GREETING.match(text):
        return "greeting"
    if HELP.search(text):
        return "help"
    return "query"
