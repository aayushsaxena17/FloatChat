"""Gemini REST adapter (ADR-0070), ``v1beta`` as read from the reference on 2026-10-12.

- ``POST /models/{model}:generateContent``: ``systemInstruction``, ``contents``,
  ``generationConfig`` (``responseMimeType``, ``responseJsonSchema``, ``temperature``,
  ``maxOutputTokens``, ``candidateCount``, ``seed``, ``thinkingConfig.thinkingLevel``); the
  answer in ``candidates[0].content.parts[].text``; tokens in ``usageMetadata``
  (``promptTokenCount``, ``candidatesTokenCount``, ``thoughtsTokenCount``).
- ``POST /models/{model}:streamGenerateContent?alt=sse``: the same body, ``data:`` lines.
- ``POST /models/{model}:batchEmbedContents``: ``requests[]`` with ``taskType`` and
  ``outputDimensionality``; vectors in ``embeddings[].values`` (manual L2 normalisation below
  3072 dimensions, as the embeddings guide requires for ``gemini-embedding-001``).

The key travels in the ``x-goog-api-key`` header only; it is never in a URL or a body.
"""

import json
from collections.abc import Generator, Sequence
from typing import Any

import httpx

from .config import EMBEDDING_DIMENSIONS, GEMINI_BASE_URL
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

TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}
EMBED_BATCH = 100
BLOCKED_FINISH = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "ESCALATION",
}


def translate_http(error: Exception) -> ProviderError:
    if isinstance(error, httpx.TimeoutException):
        return ProviderError("timeout", "request timed out")
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            return ProviderError("rate_limited", "rate limited", status)
        if status >= 500:
            return ProviderError("server", "server error", status)
        return ProviderError("client", "rejected request", status)
    if isinstance(error, httpx.HTTPError):
        return ProviderError("server", "transport failure")
    return ProviderError("malformed", type(error).__name__)


def _usage(document: dict[str, Any]) -> Usage:
    meta = document.get("usageMetadata") or {}
    return Usage(
        int(meta.get("promptTokenCount") or 0),
        int(meta.get("candidatesTokenCount") or 0),
        int(meta.get("thoughtsTokenCount") or 0),
    )


def _candidate_text(document: dict[str, Any]) -> str:
    feedback = document.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise ProviderError("blocked", "prompt blocked")
    candidates = document.get("candidates") or []
    if not candidates:
        raise ProviderError("malformed", "no candidates")
    candidate = candidates[0]
    finish = candidate.get("finishReason") or "STOP"
    if finish in BLOCKED_FINISH:
        raise ProviderError("blocked", finish)
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts if not part.get("thought", False))
    if finish == "MAX_TOKENS":
        raise ProviderError("malformed", "output truncated")
    return text


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        embedding_model: str,
        *,
        timeout_seconds: float = 20.0,
        thinking_level: str = "LOW",
        base_url: str = GEMINI_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.embedding_model = embedding_model
        self.thinking_level = thinking_level
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    # ----- requests ---------------------------------------------------------------------------

    def _generation_body(
        self,
        system: str,
        user: str,
        *,
        max_output_tokens: int,
        temperature: float,
        seed: int | None,
        schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "candidateCount": 1,
        }
        if seed is not None:
            config["seed"] = seed
        if schema is not None:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = schema
        if self.thinking_level:
            config["thinkingConfig"] = {"thinkingLevel": self.thinking_level}
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": config,
        }

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

    def structured(self, request: StructuredRequest) -> StructuredResult:
        body = self._generation_body(
            request.system,
            request.user,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            seed=request.seed,
            schema=request.schema,
        )
        document = self._post(f"/models/{self.model}:generateContent", body)
        text = _candidate_text(document)
        try:
            data = json.loads(text)
        except ValueError:
            raise ProviderError("malformed", "not JSON") from None
        return StructuredResult(
            data=data,
            raw_text=text,
            usage=_usage(document),
            model=self.model,
            model_version=document.get("modelVersion"),
        )

    def embed(self, texts: Sequence[str], task: EmbedTask) -> EmbedResult:
        vectors: list[list[float]] = []
        usage = Usage()
        for start in range(0, len(texts), EMBED_BATCH):
            batch = texts[start : start + EMBED_BATCH]
            body = {
                "requests": [
                    {
                        "model": f"models/{self.embedding_model}",
                        "content": {"parts": [{"text": text}]},
                        "taskType": TASK_TYPES[task],
                        "outputDimensionality": EMBEDDING_DIMENSIONS,
                    }
                    for text in batch
                ]
            }
            document = self._post(f"/models/{self.embedding_model}:batchEmbedContents", body)
            embeddings = document.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise ProviderError("malformed", "embedding count")
            for item in embeddings:
                values = item.get("values") if isinstance(item, dict) else None
                if not isinstance(values, list) or len(values) != EMBEDDING_DIMENSIONS:
                    raise ProviderError("malformed", "embedding dimension")
                vectors.append(normalize([float(value) for value in values]))
            meta = document.get("usageMetadata") or {}
            usage = usage + Usage(int(meta.get("promptTokenCount") or 0), 0, 0)
        return EmbedResult(vectors=vectors, usage=usage, model=self.embedding_model)

    def stream_text(self, request: TextRequest) -> TextStream:
        body = self._generation_body(
            request.system,
            request.user,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            seed=None,
            schema=None,
        )
        return TextStream(self._stream(body), self.model)

    def _stream(self, body: dict[str, Any]) -> Generator[str, None, Usage]:
        path = f"/models/{self.model}:streamGenerateContent"
        try:
            with self._client.stream("POST", path, params={"alt": "sse"}, json=body) as response:
                response.raise_for_status()
                usage = Usage()
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        document = json.loads(payload)
                    except ValueError:
                        raise ProviderError("malformed", "bad stream chunk") from None
                    if document.get("usageMetadata"):
                        usage = _usage(document)
                    for candidate in document.get("candidates") or []:
                        if candidate.get("finishReason") in BLOCKED_FINISH:
                            raise ProviderError("blocked", str(candidate.get("finishReason")))
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            if part.get("thought"):
                                continue
                            text = str(part.get("text", ""))
                            if text:
                                yield text
                return usage
        except httpx.HTTPError as error:
            raise translate_http(error) from None
