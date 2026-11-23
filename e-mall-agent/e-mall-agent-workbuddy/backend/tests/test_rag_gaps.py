"""RAG 缺口专项测试：查询改写、RAGAS 指标、高级范式、ACL、语义缓存、知识抽取。

每个用例都用中文 docstring 说明「知识点 -> 验证点」，全部离线确定性。
"""
from __future__ import annotations

from app.rag.acl import ACLFilteredRetriever, ACLPolicy, row_level_filter
from app.rag.advanced import AgenticRAG, CorrectiveRAG, SelfRAG
from app.rag.extraction import (
    EntityExtractor,
    EventExtractor,
    RelationExtractor,
    extract_knowledge,
)
from app.rag.query import (
    HyDEGenerator,
    MultiQueryGenerator,
    QueryDecomposer,
    StepBackRewriter,
)
from app.rag.ragas_metrics import ContextPrecision, evaluate_rag
from app.rag.semantic_cache import SemanticCache

CONTEXT = "七天无理由退货：签收后7天内可申请退货，退款1-3个工作日原路退回。"


# ---------------------------------------------------------------------------
# 一、查询理解与改写
# ---------------------------------------------------------------------------
def test_multiquery_uses_injected_generator_and_dedupes():
    """可注入改写：注入函数输出被使用，重复项被去除。"""
    generator = MultiQueryGenerator(
        n=3, generator=lambda q, n: [f"改写:{q}"] * n,
    )
    assert generator.generate("退货政策") == ["改写:退货政策"]


def test_multiquery_default_contains_original_and_variants():
    """默认改写：原查询保留，且产生不同表述。"""
    results = MultiQueryGenerator(n=4).generate("退货政策")
    assert "退货政策" in results
    assert len(set(results)) > 1


def test_hyde_and_stepback_support_injection():
    """假设答案与上位问题：注入函数输出原样返回。"""
    assert HyDEGenerator(generator=lambda q: f"假设文档:{q}").generate("退货") == "假设文档:退货"
    assert StepBackRewriter(generator=lambda q: "上位问题").rewrite("退货") == "上位问题"
    assert "售后服务" in StepBackRewriter().rewrite("退货要多久到账")


def test_decomposer_splits_and_uses_injection():
    """子问题拆分：默认按「分别」拆分，注入函数优先。"""
    parts = QueryDecomposer().decompose("退货政策和配送规则分别是什么？")
    assert parts == ["退货政策是什么？", "配送规则是什么？"]
    assert QueryDecomposer(generator=lambda q: ["子问题"]).decompose("任意") == ["子问题"]


# ---------------------------------------------------------------------------
# 二、RAGAS 评测指标
# ---------------------------------------------------------------------------
def test_evaluate_rag_distinguishes_grounded_and_hallucinated():
    """忠实度：被支撑答案显著高于幻觉答案。"""
    gt = "七天无理由退货，7天内可退货，退款1-3个工作日。"
    good = evaluate_rag("退货政策", CONTEXT, [CONTEXT], ground_truth=gt)
    bad = evaluate_rag("退货政策", "木星即将变成恒星，导致全球气温骤降。",
                       [CONTEXT], ground_truth=gt)
    assert good.faithfulness >= 0.8 and bad.faithfulness < 0.2
    assert good.answer_relevancy > bad.answer_relevancy
    assert good.ground_truth_provided is True


def test_context_precision_is_rank_weighted():
    """上下文精确率：相关文档排第一时得分高于随机列表。"""
    relevant = "七天无理由退货，7天内可申请退货，退款1-3个工作日。"
    irrelevant = "配送时效：满199元包邮，一线城市1-2天"
    assert ContextPrecision().score("退货政策", [relevant, irrelevant]) > 0.5
    assert ContextPrecision().score("退货政策", [irrelevant, relevant]) < 0.5


def test_context_recall_and_report_serialization():
    """召回率与报告：参考答案被覆盖时召回高，as_dict/mean 可用。"""
    report = evaluate_rag("退货政策", CONTEXT, [CONTEXT], ground_truth=CONTEXT)
    assert report.context_recall > 0.9
    assert 0.0 < report.mean() <= 1.0
    payload = report.as_dict()
    assert set(payload) == {"faithfulness", "answer_relevancy", "context_precision",
                            "context_recall", "ground_truth_provided"}


# ---------------------------------------------------------------------------
# 三、高级 RAG 范式
# ---------------------------------------------------------------------------
def test_corrective_rag_discards_unsupported_answer():
    """纠错 RAG：低支撑度答案被丢弃并给出安全回复。"""
    rag = CorrectiveRAG(
        retriever=lambda q: [{"content": CONTEXT}],
        answerer=lambda q, c: "木星变成恒星导致全球气温骤降。",
        threshold=0.45, max_retries=0,
    )
    result = rag.run("退货政策")
    assert result.action == "discard"
    assert "依据不足" in result.answer
    assert result.groundedness < 0.45


def test_corrective_rag_retries_then_returns():
    """纠错 RAG：首次低分触发重检索，第二次高分后原样返回。"""
    calls: list[str] = []

    def retriever(query: str) -> list[dict[str, str]]:
        calls.append(query)
        return [{"content": "配送时效满199元包邮"}] if len(calls) == 1 else [{"content": CONTEXT}]

    answers = ["木星变成恒星导致全球气温骤降。", CONTEXT]
    rag = CorrectiveRAG(
        retriever=retriever,
        answerer=lambda q, c: answers[min(len(calls) - 1, 1)],
        threshold=0.45, max_retries=1,
    )
    result = rag.run("退货政策")
    assert result.action == "return"
    assert len(calls) == 2
    assert any(step.startswith("re_retrieve") for step in result.trace)


def test_self_rag_reflection_tokens_control_flow():
    """Self-RAG：反射 token 决定是否检索、相关与支持。"""
    def reflector(prompt: str) -> str:
        if prompt.startswith("RETRIEVE"):
            return "[No Retrieve]"
        if prompt.startswith("RELEVANT"):
            return "[Irrelevant]"
        return "[Supported]"

    retrieved: list[str] = []
    rag = SelfRAG(
        retriever=lambda q: retrieved.append(q) or [CONTEXT],
        answerer=lambda q, c: "答案。",
        reflector=reflector,
    )
    result = rag.run("退货政策")
    assert result.action == "no_retrieve" and retrieved == []
    assert result.reflection["retrieve"] is False
    assert result.groundedness == 1.0

    def retrieve_reflector(prompt: str) -> str:
        return "[Retrieve]" if prompt.startswith("RETRIEVE") else "[Relevant]"

    rag2 = SelfRAG(retriever=lambda q: [CONTEXT], answerer=lambda q, c: "答案。",
                   reflector=retrieve_reflector)
    assert rag2.run("退货政策").action == "retrieve"


def test_agentic_rag_plans_steps_and_applies_decider():
    """Agentic RAG：规划多步检索，决策器可跳过步骤。"""
    calls: list[str] = []

    def decider(question: str, step: str, contexts: list) -> bool:
        return step != "步骤二"

    rag = AgenticRAG(
        planner=lambda q: ["步骤一", "步骤二", "步骤三"],
        retriever=lambda q: calls.append(q) or [{"content": q}],
        answerer=lambda q, c: "汇总答案",
        decider=decider,
    )
    result = rag.run("复合问题")
    assert calls == ["步骤一", "步骤三"]
    assert "skip:步骤二" in result.trace
    assert result.action == "plan" and result.answer == "汇总答案"


# ---------------------------------------------------------------------------
# 四、权限感知检索
# ---------------------------------------------------------------------------
def test_acl_policy_deny_wins_and_tenant_check():
    """ACL 策略：拒绝优先于允许，owner 显式允许，租户不匹配拒绝。"""
    policy = ACLPolicy(owner="u1", allowed_users={"u1", "u2"}, denied_users={"u1"})
    assert policy.allows("u1") is False
    assert policy.allows("u2") is True
    assert policy.allows("u3") is False
    assert policy.allows("u2", tenant="other") is True  # 策略 tenant 缺省时不阻断
    tenant_policy = ACLPolicy(allowed_users={"u2"}, tenant="t1")
    assert tenant_policy.allows("u2", tenant="t2") is False
    assert tenant_policy.allows("u2", tenant="t1") is True


def test_acl_filtered_retriever_enforces_user_id():
    """ACL 检索器：按 user_id 过滤并拒绝无用户上下文的调用。"""
    records = [
        {"content": "mine", "metadata": {"acl": {"owner": "u1"}}},
        {"content": "denied", "metadata": {"acl": {"allowed_users": ["u1"],
                                                   "denied_users": ["u1"]}}},
        {"content": "public", "metadata": {}},
    ]
    retriever = ACLFilteredRetriever(lambda q, **k: records)
    assert [r["content"] for r in retriever.retrieve("x", "u1")] == ["mine", "public"]
    assert retriever.retrieve("x", "") == []


def test_row_level_filter_deny_by_default():
    """行级过滤：deny_by_default 时无策略记录也被过滤。"""
    records = [{"content": "public"}, {"content": "private", "acl": {"owner": "u1"}}]
    assert len(row_level_filter(records, "u1")) == 2
    assert [r["content"] for r in row_level_filter(records, "u1", deny_by_default=True)] == ["private"]


# ---------------------------------------------------------------------------
# 五、语义缓存
# ---------------------------------------------------------------------------
def test_semantic_cache_hit_and_miss():
    """语义缓存：相同查询命中，低相似查询未命中并累计统计。"""
    cache = SemanticCache(threshold=0.9)
    cache.put("退货政策", CONTEXT)
    assert cache.get("退货政策").answer == CONTEXT
    assert cache.get("量子力学黑洞蒸发") is None
    assert cache.stats() == {"size": 1, "hits": 1, "misses": 1}


def test_semantic_cache_ttl_and_capacity():
    """TTL 与容量：过期条目被清理，超出容量淘汰最早条目。"""
    now = [0.0]
    cache = SemanticCache(threshold=0.9, ttl_seconds=5, max_size=2, clock=lambda: now[0])
    cache.put("a", "A")
    cache.put("b", "B")
    cache.put("c", "C")
    assert len(cache) == 2
    now[0] = 6.0
    assert cache.get("a") is None


# ---------------------------------------------------------------------------
# 六、知识抽取
# ---------------------------------------------------------------------------
def test_extract_knowledge_rules_produce_entities_relations_events():
    """规则抽取：商品/订单/类目实体、CONTAINS 关系与退货事件被识别。"""
    text = "订单O1001包含商品P001，无线降噪耳机属于数码。签收后7天内可退货，退款1-3个工作日原路退回。"
    draft = extract_knowledge(text)
    names = {e.name for e in draft.entities}
    assert {"O1001", "数码", "无线降噪耳机"}.issubset(names)
    assert any(r.predicate == "CONTAINS" for r in draft.relations)
    assert any(e.trigger == "退货" and "时限" in e.arguments for e in draft.events)
    assert len(draft.to_graph()) >= len(draft.entities)


def test_extractors_prefer_injected_llm():
    """可注入 LLM：三类抽取器均优先返回注入结果。"""
    entity = EntityExtractor(llm=lambda t: [{"id": "e1", "type": "Product", "name": "注入商品"}])
    relation = RelationExtractor(llm=lambda t: [{"source": "A", "predicate": "REL", "target": "B"}])
    event = EventExtractor(llm=lambda t: [{"id": "ev1", "trigger": "退货", "type": "ReturnEvent"}])
    assert entity.extract("任意")[0].name == "注入商品"
    assert relation.extract("任意")[0].predicate == "REL"
    assert event.extract("任意")[0].trigger == "退货"
