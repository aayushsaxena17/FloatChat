"""OpenAI-compatible chat-completions adapter (ADR-0070): the second model of the ablation.

``POST {base}/chat/completions`` with ``response_format.json_schema`` and ``POST
{base}/embeddings`` with ``dimensions``. Any endpoint speaking this shape works (OpenAI, Groq,
Together, a local server); the key is a bearer header only.
"""

import json
from collections.abc import Generator, Sequence
from typing import Any

import httpx

from .config import EMBEDDING_DIMENSIONS
from .gemini import translate_http
from .provider import (
    EmbedResult,
    EmbedTask,
    ProviderError,
    StructuredRequest,
    StructuredResult,
    TextRequest,
    TextStream,
    Usage,
    normalize,
)

EMBED_BATCH = 100


def _usage(document: dict[str, Any]) -> Usage:
    usage = document.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    reasoning = int(details.get("reasoning_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    return Usage(int(usage.get("prompt_tokens") or 0), max(0, completion - reasoning), reasoning)


class OpenAICompatibleProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        embedding_model: str,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.embedding_model = embedding_model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(path, json=body)
            response.raise_for_status()
            document = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise translate_http(error) from None
        if not isinstance(document, dict):
            raise ProviderError("malformed", "object expected")
        return document

    @staticmethod
    def _messages(system: str, user: str) -> list[dict[str, str]]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def structured(self, request: StructuredRequest) -> StructuredResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(request.system, request.user),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.purpose, "schema": request.schema},
            },
        }
        if request.seed is not None:
            body["seed"] = request.seed
        document = self._post("/chat/completions", body)
        choices = document.get("choices") or []
        if not choices:
            raise ProviderError("malformed", "no choices")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ProviderError("malformed", "output truncated")
        if choice.get("finish_reason") == "content_filter":
            raise ProviderError("blocked", "content filter")
        text = str((choice.get("message") or {}).get("content") or "")
        try:
            data = json.loads(text)
        except ValueError:
            raise ProviderError("malformed", "not JSON") from None
        return StructuredResult(
            data=data,
            raw_text=text,
            usage=_usage(document),
            model=self.model,
            model_version=document.get("model"),
        )

    def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbedResult:
        vectors: list[list[float]] = []
        usage = Usage()
        for start in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[start : start + EMBED_BATCH])
            document = self._post(
                "/embeddings",
                {"model": self.embedding_model, "input": batch, "dimensions": EMBEDDING_DIMENSIONS},
            )
            data = document.get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                raise ProviderError("malformed", "embedding count")
            for item in sorted(data, key=lambda row: int(row.get("index", 0))):
                values = item.get("embedding")
                if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS:
                    raise ProviderError("malformed", "embedding dimension")
                vectors.append(normalize([float(value) for value in values]))
            usage = usage + _usage(document)
        return EmbedResult(vectors=vectors, usage=usage, model=self.embedding_model)

    def stream_text(self, request: TextRequest) -> TextStream:
        body = {
            "model": self.model,
            "messages": self._messages(request.system, request.user),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        return TextStream(self._stream(body), self.model)

    def _stream(self, body: dict[str, Any]) -> Generator[str, None, Usage]:
        try:
            with self._client.stream("POST", "/chat/completions", json=body) as response:
                response.raise_for_status()
                usage = Usage()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        document = json.loads(payload)
                    except ValueError:
                        raise ProviderError("malformed", "bad stream chunk") from None
                    if document.get("usage"):
                        usage = _usage(document)
                    for choice in document.get("choices") or []:
                        if choice.get("finish_reason") == "content_filter":
                            raise ProviderError("blocked", "content filter")
                        text = (choice.get("delta") or {}).get("content")
                        if text:
                            yield str(text)
                return usage
        except httpx.HTTPError as error:
            raise translate_http(error) from None
