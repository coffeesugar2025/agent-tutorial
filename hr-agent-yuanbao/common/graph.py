"""轻量图检索：邻接表实现，用来讲清 GraphRAG / Text2Cypher 在解决什么。

生产替换：Neo4j（Cypher）、NebulaGraph、TigerGraph，或用 LlamaIndex 的
KnowledgeGraphIndex / PropertyGraphIndex 做 GraphRAG 社区摘要。

向量检索回答不了「张三的同事里谁参与过同一个项目」这类**多跳关系**问题，
图检索可以：先定位实体，再沿边扩展 N 跳，把子图文本塞进 Prompt。
"""
from __future__ import annotations

from collections import deque


class SimpleGraph:
    def __init__(self, edges: list[tuple[str, str, str]] | None = None):
        self.adj: dict[str, list[tuple[str, str]]] = {}
        for s, r, t in edges or []:
            self.add(s, r, t)

    def add(self, src: str, rel: str, dst: str) -> None:
        self.adj.setdefault(src, []).append((rel, dst))
        self.adj.setdefault(dst, [])

    def neighbors(self, node: str) -> list[tuple[str, str]]:
        return self.adj.get(node, [])

    def expand(self, start: str, hops: int = 2) -> list[tuple[str, str, str]]:
        """从起点做 BFS 多跳扩展，返回子图三元组。"""
        seen_edges: set[tuple[str, str, str]] = set()
        seen_nodes = {start}
        queue = deque([(start, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth >= hops:
                continue
            for rel, dst in self.adj.get(node, []):
                seen_edges.add((node, rel, dst))
                if dst not in seen_nodes:
                    seen_nodes.add(dst)
                    queue.append((dst, depth + 1))
        return sorted(seen_edges)

    def find_by_relation(self, rel: str) -> list[tuple[str, str, str]]:
        return [(s, r, t) for s, edges in self.adj.items() for r, t in edges if r == rel]

    def subgraph_text(self, start: str, hops: int = 2) -> tuple[str, list[tuple[str, str, str]]]:
        edges = self.expand(start, hops)
        lines = [f"{s} --{r}--> {t}" for s, r, t in edges]
        return "\n".join(lines) if lines else f"（图中未找到与「{start}」相关的关系）", edges

    def query(self, start: str, rel: str) -> list[str]:
        """等价于一句极简 Cypher： MATCH (a)-[:rel]->(b) WHERE a.name = start RETURN b """
        return [t for r, t in self.adj.get(start, []) if r == rel]
