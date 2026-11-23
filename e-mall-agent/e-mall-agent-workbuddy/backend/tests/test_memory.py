"""记忆系统测试：会话隔离、淘汰压缩、TTL、用户隔离、融合召回与并发安全。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.context.engine import estimate_tokens
from app.memory import (
    EpisodicMemory,
    InMemoryMemoryStore,
    MemoryManager,
    MemoryStore,
    UserMemory,
    WorkingMemory,
)


@pytest.fixture
def store() -> InMemoryMemoryStore:
    """每个用例使用独立的内存存储。"""
    return InMemoryMemoryStore()


# ---------- WorkingMemory ----------

def test_working_memory_thread_isolation(store: InMemoryMemoryStore) -> None:
    wm = WorkingMemory(store, max_turns=8)
    wm.add("thread-A", "A的问题", "A的回答")
    assert [t.user for t in wm.get("thread-A")] == ["A的问题"]
    assert wm.get("thread-B") == []
    wm.clear("thread-A")
    assert wm.get("thread-A") == []
    assert wm.get("thread-B") == []


def test_working_memory_evicts_low_importance_and_summarises(store: InMemoryMemoryStore) -> None:
    wm = WorkingMemory(store, max_turns=4)
    for i in range(6):
        wm.add("t", f"问题{i}", f"回答{i}", importance=0.1 if i < 2 else 1.0)
    turns = wm.get("t")
    assert len(turns) == 4
    assert [t.user for t in turns] == ["问题2", "问题3", "问题4", "问题5"]
    summary = wm.get_summary("t")
    assert "历史摘要" in summary
    assert "问题0" in summary and "问题1" in summary
    assert wm.stats()["evicted"] == 2


def test_working_memory_char_budget_triggers_compression(store: InMemoryMemoryStore) -> None:
    wm = WorkingMemory(store, max_turns=20, max_chars=12)
    wm.add("t", "很长的问题内容", "很长的回答内容")
    wm.add("t", "短问", "短答")
    assert sum(t.chars for t in wm.get("t")) <= 12
    assert wm.get_summary("t")


def test_working_memory_stats_and_defensive_copy(store: InMemoryMemoryStore) -> None:
    wm = WorkingMemory(store, max_turns=8)
    wm.add("t1", "q1", "a1")
    wm.add("t2", "q2", "a2")
    turns = wm.get("t1")
    turns.clear()
    assert len(wm.get("t1")) == 1
    snapshot = wm.snapshot("t1")
    assert snapshot["evicted_count"] == 0
    stats = wm.stats()
    assert stats["threads"] == 2
    assert stats["turns"] == 2


# ---------- EpisodicMemory ----------

def test_episode_record_get_list_and_filter(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=10)
    first = em.record("U001", "T1", "退款处理", ["核对订单", "提交申请"], "已退款", ["退款"])
    second = em.record("U001", "T2", "耳机推荐", ["检索商品"], "推荐P001", ["商品"])
    assert em.get("U001", first.id).goal == "退款处理"
    assert em.get("U001", "not-exist") is None
    assert {e.id for e in em.list("U001")} == {first.id, second.id}
    assert [e.id for e in em.list("U001", thread_id="T1")] == [first.id]


def test_episode_search_by_relevance_and_tags(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=10)
    em.record("U001", "T1", "耳机推荐", ["搜索"], "推荐P001", ["商品"])
    refund = em.record("U001", "T2", "退款订单处理", ["核对订单"], "退款成功", ["退款"])
    hits = em.search("U001", "退款 订单", limit=5)
    assert hits and hits[0].id == refund.id
    assert em.search("U001", "退款", tags=["退款"])[0].id == refund.id
    assert em.search("U001", "", tags=["不存在"]) == []


def test_episode_delete_and_clear(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=10)
    ep = em.record("U001", "T1", "任务", outcome="完成")
    assert em.delete("U001", ep.id) is True
    assert em.delete("U001", ep.id) is False
    em.record("U001", "T1", "另一个任务")
    em.clear("U001")
    assert em.list("U001") == []


def test_episode_ttl_expiry(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=10)
    expired = em.record("U001", "T1", "临时任务", ttl_seconds=0)
    alive = em.record("U001", "T1", "长期任务", ttl_seconds=3600)
    assert em.get("U001", expired.id) is None
    assert em.get("U001", alive.id) is not None
    assert [e.id for e in em.list("U001")] == [alive.id]


def test_episode_rolling_eviction(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=3)
    records = [em.record("U001", "T1", f"任务{i}") for i in range(5)]
    remaining = em.list("U001")
    assert len(remaining) == 3
    assert {e.id for e in remaining} == {r.id for r in records[-3:]}


def test_episodic_cross_user_isolation(store: InMemoryMemoryStore) -> None:
    em = EpisodicMemory(store, max_episodes=10)
    alice = em.record("U001", "T1", "爱丽丝的私密任务", ["步骤"], "完成", ["私密"])
    em.record("U002", "T1", "鲍勃的任务", outcome="完成")
    assert em.get("U002", alice.id) is None
    assert all(e.user_id == "U002" for e in em.list("U002"))
    assert all(e.user_id == "U001" for e in em.list("U001"))
    assert em.search("U002", "私密") == []
    em.clear("U001")
    assert len(em.list("U002")) == 1


# ---------- UserMemory ----------

def test_preference_confidence_reinforcement_and_override(store: InMemoryMemoryStore) -> None:
    um = UserMemory(store)
    first = um.upsert_preference("U001", "语言", "中文", confidence=0.6)
    assert first.confidence == 0.6
    reinforced = um.upsert_preference("U001", "语言", "中文", confidence=0.6)
    assert reinforced.confidence == 0.7
    overridden = um.upsert_preference("U001", "语言", "英文", confidence=0.9)
    assert overridden.value == "英文"
    assert overridden.confidence == 0.9
    assert um.get_preference("U001", "语言").value == "英文"


def test_fact_source_and_expiry(store: InMemoryMemoryStore) -> None:
    um = UserMemory(store)
    permanent = um.add_fact("U001", "会员等级为金卡", "订单系统")
    temporary = um.add_fact("U001", "临时优惠券已失效", "营销系统", ttl_seconds=0)
    assert permanent.source == "订单系统"
    assert [f.id for f in um.list_facts("U001")] == [permanent.id]
    summary = um.get_profile_summary("U001")
    assert "会员等级为金卡" in summary and "订单系统" in summary
    assert "临时优惠券" not in summary


def test_profile_summary_is_prompt_ready(store: InMemoryMemoryStore) -> None:
    um = UserMemory(store)
    assert um.get_profile_summary("U001") == ""
    um.set_profile("U001", {"name": "张三", "role": "customer"})
    um.upsert_preference("U001", "语言", "中文", confidence=0.8)
    um.add_fact("U001", "居住城市为杭州", "收货地址")
    text = um.get_profile_summary("U001")
    assert "用户画像" in text and "张三" in text
    assert "用户偏好" in text and "置信度 0.80" in text
    assert "已知事实" in text and "杭州" in text
    assert um.stats("U001") == {"profile_fields": 2, "preferences": 1, "facts": 1}


def test_forget_by_target(store: InMemoryMemoryStore) -> None:
    um = UserMemory(store)
    um.set_profile("U001", {"name": "张三"})
    pref = um.upsert_preference("U001", "语言", "中文")
    fact = um.add_fact("U001", "金卡会员", "订单系统")
    assert um.forget("U001", "preference", key=pref.name) == 1
    assert um.forget("U001", "fact", key=fact.id) == 1
    assert um.forget("U001", "profile") == 1
    assert um.get_profile_summary("U001") == ""
    um.add_fact("U001", "新事实", "客服")
    assert um.forget("U001", "all") == 1
    assert um.list_facts("U001") == []


def test_user_cross_user_isolation_critical(store: InMemoryMemoryStore) -> None:
    """关键安全断言：A 用户永远读不到 B 用户的记忆。"""
    um = UserMemory(store)
    um.set_profile("U001", {"name": "爱丽丝", "secret": "A的隐私"})
    um.upsert_preference("U001", "语言", "中文", confidence=0.9)
    um.add_fact("U001", "A的身份证尾号1234", "实名认证")

    assert um.get_profile_summary("U002") == ""
    assert um.get_preference("U002", "语言") is None
    assert um.list_facts("U002") == []
    assert um.forget("U002", "all") == 0
    assert "爱丽丝" not in um.get_profile_summary("U002")
    assert "A的隐私" not in um.get_profile_summary("U002")
    # 删除 B 的用户数据不得影响 A
    um.forget("U002", "all")
    assert "爱丽丝" in um.get_profile_summary("U001")


# ---------- MemoryManager ----------

def test_recall_fusion_order_and_token_estimate(store: InMemoryMemoryStore) -> None:
    mgr = MemoryManager(store)
    mgr.user.set_profile("U001", {"name": "张三", "role": "customer"})
    mgr.user.upsert_preference("U001", "语言", "中文", confidence=0.8)
    mgr.user.add_fact("U001", "会员等级为金卡", "订单系统")
    mgr.remember("U001", "T1", "推荐耳机吗", "有货", goal="耳机推荐", outcome="推荐P001")
    mgr.remember("U001", "T1", "旧请求", "旧回答", goal="耳机推荐过期任务",
                 outcome="已过期", ttl_seconds=0)

    result = mgr.recall("U001", "T1", "耳机 推荐")
    text = result.injected_context
    assert text.index("[用户长期记忆]") < text.index("[相关经历]") < text.index("[近期会话]")
    assert "张三" in result.user_summary
    assert len(result.working) == 2
    assert len(result.episodes) == 1 and result.episodes[0].goal == "耳机推荐"
    assert "过期任务" not in text
    assert result.token_estimate == estimate_tokens(text)
    assert result.as_dict()["token_estimate"] == result.token_estimate


def test_remember_writes_working_and_optional_episode(store: InMemoryMemoryStore) -> None:
    mgr = MemoryManager(store)
    assert mgr.remember("U001", "T1", "你好", "你好呀") is None
    episode = mgr.remember("U001", "T1", "查订单", "已查询", goal="订单查询",
                           steps=["定位订单"], outcome="查询成功", tags=["订单"])
    assert episode is not None and episode.steps == ["定位订单"]
    assert len(mgr.working.get("U001::T1")) == 2
    assert len(mgr.episodic.list("U001")) == 1


def test_forget_user_clears_every_layer(store: InMemoryMemoryStore) -> None:
    mgr = MemoryManager(store)
    mgr.user.set_profile("U001", {"name": "张三"})
    mgr.user.add_fact("U001", "金卡会员", "订单系统")
    mgr.remember("U001", "T1", "q", "a", goal="任务")
    mgr.remember("U002", "T1", "别人的问题", "别人的回答", goal="他人任务")
    mgr.user.set_profile("U002", {"name": "李四"})

    counts = mgr.forget_user("U001")
    assert counts == {"working": 1, "episodes": 1, "user": 1}
    assert mgr.working.get("U001::T1") == []
    assert mgr.episodic.list("U001") == []
    assert mgr.user.get_profile_summary("U001") == ""
    assert mgr.working.get("U002::T1")[0].user == "别人的问题"
    assert len(mgr.episodic.list("U002")) == 1
    assert "李四" in mgr.user.get_profile_summary("U002")


def test_manager_enforces_cross_user_thread_isolation(store: InMemoryMemoryStore) -> None:
    mgr = MemoryManager(store)
    mgr.remember("U001", "shared-thread", "A的秘密", "A的回答")
    mgr.remember("U002", "shared-thread", "B的问题", "B的回答")
    assert mgr.working.get("U001::shared-thread")[0].user == "A的秘密"
    assert "A的秘密" not in mgr.recall("U002", "shared-thread", "秘密").injected_context
    assert mgr.recall("U002", "shared-thread", "秘密").working[0].user == "B的问题"


def test_concurrent_writes_are_safe(store: InMemoryMemoryStore) -> None:
    """并发写入同一会话与同一用户时不得丢失数据或抛异常。"""
    wm = WorkingMemory(store, max_turns=1000)
    em = EpisodicMemory(store, max_episodes=1000)

    def writer(index: int) -> None:
        for j in range(50):
            wm.add("hot-thread", f"q-{index}-{j}", f"a-{index}-{j}")
            em.record("U001", "hot-thread", f"任务-{index}-{j}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(writer, range(8)))

    assert len(wm.get("hot-thread")) == 400
    assert len(em.list("U001")) == 400
    assert wm.stats()["turns"] == 400


def test_store_implements_memory_store_protocol(store: InMemoryMemoryStore) -> None:
    assert isinstance(store, MemoryStore)
    store.set("ns", "k", {"a": 1})
    value = store.get("ns", "k")
    value["a"] = 2
    assert store.get("ns", "k")["a"] == 1
    assert store.keys("ns") == ["k"]
    assert store.delete("ns", "k") is True
    assert store.delete_namespace("ns") is True
