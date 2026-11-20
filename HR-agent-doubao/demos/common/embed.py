"""离线可用的本地 Embeddings —— 让"没有 Key"也能看到真实的检索效果。

原理：中文按 2-gram 切，英文按 4-gram 切，做 hashing 投到固定维度再归一化。
它不是 SOTA 向量模型，但**保留字面相关性**，足够把 RAG 的切片/召回/重排讲清楚。

真实项目里换成：
    from langchain_openai import OpenAIEmbeddings
    emb = OpenAIEmbeddings(model="text-embedding-3-small", base_url=..., api_key=...)
"""

import hashlib, math, re

from langchain_core.embeddings import Embeddings


class LocalHashEmbedding(Embeddings):
    def __init__(self, dim: int = 512):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        t = re.sub(r"\s+", "", text.lower())
        grams = []
        cjk = [ch for ch in t if "\u4e00" <= ch <= "\u9fff"]
        for i in range(len(cjk) - 1):
            grams.append(cjk[i] + cjk[i + 1])
        words = re.findall(r"[a-z0-9]+", t)
        for w in words:
            grams += [w[i:i + 4] for i in range(max(1, len(w) - 3))]
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)
