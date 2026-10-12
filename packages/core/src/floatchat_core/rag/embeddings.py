"""``hash-embed-v1``: a deterministic lexical embedding for the offline provider (ADR-0071).

Word unigrams, word bigrams and character trigrams are hashed into 768 signed buckets and the
vector is L2-normalised, so cosine similarity is a bag-of-features overlap. It needs no network,
no model file and gives the same vector on every host; it is named wherever it is used and is
never confused with a model embedding (retrieval filters on the embedding model).
"""

import hashlib
import re
from collections.abc import Iterable, Sequence

from ..llm.config import EMBEDDING_DIMENSIONS
from ..llm.provider import normalize

EMBEDDING_VERSION = "hash-embed-v1"
TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")
STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or the to was were what which with".split()
)


def tokens(text: str) -> list[str]:
    return [token for token in TOKEN.findall(text.lower()) if token not in STOPWORDS]


def features(text: str) -> Iterable[str]:
    words = tokens(text)
    yield from ("w:" + word for word in words)
    yield from ("b:" + a + "_" + b for a, b in zip(words, words[1:], strict=False))
    for word in words:
        padded = f" {word} "
        if len(padded) >= 3:
            yield from ("c:" + padded[i : i + 3] for i in range(len(padded) - 2))


def hash_embed(text: str, dimensions: int = EMBEDDING_DIMENSIONS) -> list[float]:
    vector = [0.0] * dimensions
    for feature in features(text):
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        bucket = value % dimensions
        sign = 1.0 if (value >> 63) & 1 else -1.0
        # Character trigrams are many and weak; words carry the meaning.
        weight = 0.35 if feature.startswith("c:") else 1.0
        vector[bucket] += sign * weight
    return normalize(vector)


def hash_embed_many(texts: Sequence[str]) -> list[list[float]]:
    return [hash_embed(text) for text in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=True)))
