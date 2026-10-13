"""Rule classification (ADR-0072, ADR-0075).

With a model provider the planner decides what a message is (plan, clarify, reply or
unsupported); these rules only answer greetings and help when no model can, that is with the
offline provider or while the model is unavailable.
"""

import re

GREETING = re.compile(
    r"^\s*(hi+|hello+|hey+|hiya|yo|ola|olá|hola|namaste|namaskar|hallo|bonjour|salut|ciao|"
    r"howdy|greetings|sup|wh?at'?s up|wassup|what'?s happening|how are you( doing)?|"
    r"good (morning|afternoon|evening|night)|morning|evening|"
    r"thanks|thank you|thanks a lot|thx|ty|cheers|ok|okay|cool|great|nice|bye|goodbye)"
    r"[\s!.,?]*(floatchat|there|bot|assistant|all|everyone)?[\s!.,?]*$",
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
    "Hello! I'm FloatChat. I look up Argo float observations of ocean temperature, salinity "
    'and pressure and turn them into tables and charts. Try something like "monthly mean '
    'temperature in the Arabian Sea from January to March 2025 in the upper 100 dbar".'
)


def classify(text: str) -> str:
    """``greeting``, ``help`` or ``query``."""
    if len(text) <= 60 and GREETING.match(text):
        return "greeting"
    if HELP.search(text):
        return "help"
    return "query"
