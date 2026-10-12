"""The provider interface: structured output, embeddings, streamed text (ADR-0070)."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EmbedTask = Literal["document", "query"]
ErrorKind = Literal["timeout", "rate_limited", "server", "client", "malformed", "blocked"]


class ProviderError(Exception):
    """A failed provider call. ``retryable`` drives the policy; the text never reaches a user."""

    def __init__(self, kind: ErrorKind, detail: str = "", status: int | None = None) -> None:
        super().__init__(f"{kind}: {detail}"[:200])
        self.kind: ErrorKind = kind
        self.status = status
        self.retryable = kind in ("timeout", "rate_limited", "server")


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.thinking_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.thinking_tokens + other.thinking_tokens,
        )


@dataclass(frozen=True)
class StructuredRequest:
    """One structured-output call. ``context`` carries what the offline planner needs; the HTTP
    adapters send only ``system`` and ``user``."""

    purpose: Literal["plan", "narrate"]
    system: str
    user: str
    schema: dict[str, Any]
    max_output_tokens: int = 2048
    temperature: float = 0.0
    seed: int | None = 7
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextRequest:
    purpose: Literal["narrate"]
    system: str
    user: str
    max_output_tokens: int = 400
    temperature: float = 0.2
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StructuredResult:
    data: Any
    raw_text: str
    usage: Usage
    model: str
    model_version: str | None = None


@dataclass(frozen=True)
class EmbedResult:
    vectors: list[list[float]]
    usage: Usage
    model: str


class TextStream:
    """Chunks of a streamed answer; ``usage`` is known once the iterator is exhausted."""

    def __init__(self, chunks: Iterator[str], model: str) -> None:
        self._chunks = chunks
        self.model = model
        self.usage = Usage()
        self.text = ""

    def __iter__(self) -> Iterator[str]:
        """Yields the chunks; a generator that ``return``s a ``Usage`` sets ``usage``."""
        chunks = self._chunks
        while True:
            try:
                chunk = next(chunks)
            except StopIteration as stop:
                if isinstance(stop.value, Usage):
                    self.usage = stop.value
                return
            self.text += chunk
            yield chunk

    def set_usage(self, usage: Usage) -> None:
        self.usage = usage


class Provider(Protocol):
    name: str
    model: str
    embedding_model: str

    def structured(self, request: StructuredRequest) -> StructuredResult: ...

    def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbedResult: ...

    def stream_text(self, request: TextRequest) -> TextStream: ...


def normalize(vector: Sequence[float]) -> list[float]:
    """L2 normalisation; a zero vector stays zero (cosine similarity is then 0)."""
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]
