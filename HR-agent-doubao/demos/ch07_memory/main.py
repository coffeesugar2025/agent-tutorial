"""第 07 章：Memory —— 会话记忆、长期记忆、用户记忆（LangChain 版）。

跑法：python ch07_memory/main.py

LangChain 的三个现成积木：
  · InMemoryChatMessageHistory —— 会话记忆（一会话一份）
  · InMemoryVectorStore + Embeddings —— 语义检索长期记忆
  · RunnableWithMessageHistory —— 把"按 session_id 取历史"接进链里

加上生产必须自己写的三件事：写入前抽取、去重合并、用户可删除。
"""

import sys, pathlib
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.embeddings.fake import DeterministicFakeEmbedding
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from common import ai_text, ai_tool, get_model, practice, section, star, title

EMB = DeterministicFakeEmbedding(size=64)     # 离线向量；真实项目换成 OpenAI/Qwen/BGE 的 Embeddings

# ============================================================
# 1) 会话记忆：按 session_id 隔离
# ============================================================
title("案例 1：会话记忆 —— 同一用户、两个会话，互不串台")

_histories: dict[str, InMemoryChatMessageHistory] = {}


def get_history(session_id: str) -> InMemoryChatMessageHistory:
    if session_id not in _histories:
        _histories[session_id] = InMemoryChatMessageHistory()
    return _histories[session_id]


chain = (
    ChatPromptTemplate.from_messages([("placeholder", "{history}"), ("human", "{input}")])
    | get_model([
        ai_text("张伟在技术中心。"),
        ai_text("你刚问过张伟的部门，还需要别的吗？"),
        ai_text("没有你的工号记录，先告诉我工号。"),
    ])
)
chat = RunnableWithMessageHistory(chain, get_history, input_messages_key="input",
                                  history_messages_key="history")

print(f"  会话 A 第一轮：{chat.invoke({'input': '张伟是哪个部门的？'}, {'configurable': {'session_id': 'A'}}).content}")
print(f"  会话 A 第二轮：{chat.invoke({'input': '刚才问的谁？'}, {'configurable': {'session_id': 'A'}}).content}")
print(f"  会话 B 第一轮：{chat.invoke({'input': '我还有几天年假？'}, {'configurable': {'session_id': 'B'}}).content}")
print(f"\n  会话 A 里的消息数：{len(get_history('A').messages)}，会话 B：{len(get_history('B').messages)}")
star("RunnableWithMessageHistory 只做一件小事：每次调用前按 session_id 捞出历史塞进 prompt")

# ============================================================
# 2) 长期记忆：向量库存"事实"，不是存"聊天记录"
# ============================================================
section("案例 2：长期记忆 —— 存事实，带来源，可去重")

class Fact(BaseModel):
    """一条值得长期记住的事实。"""
    kind: Literal["preference", "constraint", "background"] = Field(
        description="preference=偏好；constraint=硬约束（绝不能违背）；background=背景")
    text: str = Field(description="一句话事实，不超过 40 字")
    source: str = Field(description="从哪句话抽出来的原文片段")


class Facts(BaseModel):
    facts: list[Fact]


EXTRACT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "从对话中抽取值得长期记住的事实。没抽到就返回空列表。"
               "硬约束（如'不能倒班'）必须标 constraint。不许编造。"),
    ("human", "{utterance}"),
])

extractor = EXTRACT_PROMPT | get_model([
    ai_tool("Facts", {"facts": [
        {"kind": "constraint", "text": "不接受倒班与夜班", "source": "我不接受倒班，夜班也不行"},
        {"kind": "preference", "text": "倾向苏州园区内的岗位", "source": "最好在园区这边"},
    ]}, "c1"),
]).with_structured_output(Facts)

store = InMemoryVectorStore(EMB)

def _mine(user_id: str):
    """★ LangChain 1.x 的 InMemoryVectorStore：filter 收的是**函数**，不是 dict。

    传 dict 会报 TypeError: 'dict' object is not callable —— 这是 0.x → 1.x 的高频坑。
    """
    return lambda doc: doc.metadata.get("user_id") == user_id



def remember(user_id: str, utterance: str, max_facts: int = 3) -> list[str]:
    """★ 写入三件事：抽取 → 去重（相似度太高就不重复写）→ 标注来源与时间。"""
    facts = extractor.invoke({"utterance": utterance}).facts[:max_facts]
    added = []
    for f in facts:
        hit = store.similarity_search_with_score(f.text, k=1, filter=_mine(user_id))
        if hit and hit[0][1] > 0.92:            # 太像了，视为同一条
            print(f"    ~ 跳过重复：{f.text}")
            continue
        store.add_texts([f.text], metadatas=[{"user_id": user_id, "kind": f.kind, "source": f.source}])
        added.append(f"{f.kind}: {f.text}")
    return added


def recall(user_id: str, query: str, k: int = 3) -> list[str]:
    """读取：★ constraint 优先 —— 硬约束必须出现在上下文里，不能被相似度排掉。"""
    hits = store.similarity_search_with_score(query, k=k, filter=_mine(user_id))
    rows = [(doc.metadata["kind"], doc.page_content) for doc, _ in hits]
    cons = [t for kd, t in rows if kd == "constraint"]
    others = [t for kd, t in rows if kd != "constraint"]
    return [f"[必须遵守] {c}" for c in cons] + others


print("\n  用户说：'我不接受倒班，夜班也不行，最好在园区这边'")
for line in remember("U1", "我不接受倒班，夜班也不行，最好在园区这边"):
    print(f"    + {line}")

print("\n  再次说一遍同样的约束（应被去重）：")
for line in remember("U1", "我不接受倒班，夜班也不行"):
    print(f"    + {line}")

print("\n  召回（问'能安排夜班岗位吗？'）：")
for line in recall("U1", "能安排夜班岗位吗？"):
    print(f"    · {line}")
star("长期记忆存的是'事实 + 来源 + 类型'，不是聊天原文；类型让硬约束能优先注入")

# ============================================================
# 3) 用户可删除（合规红线）
# ============================================================
section("案例 3：用户说'忘掉我'—— 必须真删")

def delete_by_user(user_id: str) -> int:
    """★ 合规要求：记忆必须可删除。做法是按元数据找到所有条目再逐条删。"""
    # ★ InMemoryVectorStore.store 里存的是 dict（{'id','text','metadata','vector'}），不是 Document
    ids = [key for key, row in store.store.items() if row["metadata"].get("user_id") == user_id]
    for i in ids:
        store.delete([i])
    return len(ids)


before = len(store.store)
n = delete_by_user("U1")
print(f"  删除前 {before} 条，删除 {n} 条，剩余 {len(store.store)} 条")
print(f"  删完再召回：{recall('U1', '夜班')!r}")

for line in [
    "不该记的：身份证号、银行卡、家庭住址、健康诊断、绩效排名、离职倾向",
    "该记的：偏好（班次/城市）、硬约束、已办事项、沟通语言与称呼",
    "必须有的：来源、时间、可删除、按用户隔离（filter 里永远带 user_id）",
]:
    print(f"    · {line}")

practice([
    "把 DeterministicFakeEmbedding 换成真 Embeddings（如 BGE），看去重阈值 0.92 要不要调",
    "给 Fact 加 expired_at 字段，召回时过滤过期事实（记忆衰减）",
    "把会话记忆换成 trim_messages 裁剪版，观察长对话里'早期约束'丢失的后果",
])
