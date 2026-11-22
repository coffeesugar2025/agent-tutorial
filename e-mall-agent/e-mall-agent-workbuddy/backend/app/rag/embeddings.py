"""Deterministic offline embeddings so RAG works without an API key.

Production: swap with OpenAIEmbeddings / BGE via the same Embeddings interface.
"""
from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

_CJK = re.compile(r"[\u4e00-\u9fff]+")
_LATIN = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens = _LATIN.findall(text)
    for run in _CJK.findall(text):
        tokens.append(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) > 2:
            tokens.extend(run[i:i + 3] for i in range(len(run) - 2))
    return tokens


class HashEmbeddings(Embeddings):
    """Stable hashed bag-of-ngrams embeddings with cosine-ready normalisation."""

    def __init__(self, dimension: int = 128) -> None:
        self.dimension = dimension

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)
