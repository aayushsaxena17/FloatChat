"""Price table (ADR-0070): USD per million tokens, versioned, with its source.

Tokens are measured; USD is an estimate the owner confirms against the invoice. The table was
read from the Gemini pricing page on 2026-10-12 (page "last updated 2026-10-09"); prices marked
"through 2026-12-31" rise on 2027-01-01. An unknown model is priced at ``default`` and flagged.
"""

import json
from dataclasses import dataclass
from pathlib import Path

PRICING_VERSION = "gemini-pricing-2026-10-09"
PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float


DEFAULT_TABLE: dict[str, Price] = {
    "gemini-3.8-flash": Price(0.75, 3.75),
    "gemini-3.6-flash": Price(0.75, 3.75),
    "gemini-3-flash-preview": Price(0.50, 3.00),
    "gemini-2.5-flash": Price(0.30, 2.50),
    "gemini-3.5-flash-lite": Price(0.30, 2.50),
    "gemini-3.1-flash-lite": Price(0.25, 1.50),
    "gemini-2.5-flash-lite": Price(0.10, 0.40),
    "gemini-embedding-2-preview": Price(0.20, 0.0),
    # Not on the 2026-10-09 page (it lists Embedding 2 only); the last published price. Owner
    # confirms.
    "gemini-embedding-001": Price(0.15, 0.0),
    "offline-rules-v1": Price(0.0, 0.0),
    "hash-embed-v1": Price(0.0, 0.0),
    # Conservative bound for any model the table does not name (the OpenAI-compatible second
    # model included); the ledger flags such rows ``priced_as_default``.
    "default": Price(2.0, 12.0),
}


class PriceTable:
    def __init__(
        self,
        table: dict[str, Price] | None = None,
        version: str = PRICING_VERSION,
        source: str = PRICING_SOURCE,
    ) -> None:
        self.table = dict(DEFAULT_TABLE if table is None else table)
        self.version = version
        self.source = source

    @classmethod
    def from_file(cls, path: Path) -> "PriceTable":
        """``{"version": ..., "source": ..., "models": {name: [input, output]}}``."""
        document = json.loads(path.read_text())
        table = {
            name: Price(float(pair[0]), float(pair[1])) for name, pair in document["models"].items()
        }
        if "default" not in table:
            table["default"] = DEFAULT_TABLE["default"]
        return cls(table, str(document["version"]), str(document.get("source", "")))

    def estimate(self, model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
        """USD estimate and whether the default price was used. Thinking tokens are output."""
        price = self.table.get(model)
        flagged = price is None
        if price is None:
            price = self.table["default"]
        usd = (
            input_tokens * price.input_per_million + output_tokens * price.output_per_million
        ) / 1_000_000
        return round(usd, 6), flagged
