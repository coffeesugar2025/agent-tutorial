"""中文极简 BM25 + 倒数排名融合。

生产里这一层换成 Elasticsearch / OpenSearch（自带分词器、倒排索引、向量检索）；
这里自己写 60 行，是为了让你看清「全文检索为什么能补上向量检索的短板」：
向量擅长语义（"休假"≈"年假"），BM25 擅长精确词（制度编号、条款号、人名、金额）。
"""
from __future__ import annotations

import math
import re
from collections import Counter


def tokenize(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text)
    # 中文单字 + 相邻双字，兼顾精确匹配与一点点语义
    bigrams = [text[i:i + 2] for i in range(len(text) - 1)
               if all("\u4e00" <= c <= "\u9fff" for c in text[i:i + 2])]
    return words + bigrams


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[dict] = []
        self.tfs: list[Counter] = []
        self.df: Counter = Counter()
        self.avg_len = 0.0

    def add(self, id_: str, text: str, metadata: dict | None = None) -> None:
        toks = tokenize(text)
        self.docs.append({"id": id_, "text": text, "metadata": metadata or {}})
        self.tfs.append(Counter(toks))
        for t in set(toks):
            self.df[t] += 1
        lens = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = sum(lens) / len(lens)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        n = len(self.docs) or 1
        q = tokenize(query)
        out = []
        for i, tf in enumerate(self.tfs):
            dl = sum(tf.values()) or 1
            score = 0.0
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1)))
            if score > 0:
                out.append({"id": self.docs[i]["id"], "text": self.docs[i]["text"],
                            "metadata": self.docs[i]["metadata"], "score": round(score, 4),
                            "source": "bm25"})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]
