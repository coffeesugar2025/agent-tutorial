"""上下文工程测试：优先级装箱、滑窗、截断标记、快照可解释性。"""
from langchain_core.messages import AIMessage, HumanMessage

from app.context.engine import ContextEngine, estimate_tokens
from app.domain.models import User


def test_context_build_prioritises_system_and_user_input():
    engine = ContextEngine(max_chars=2000, recent_messages=6)
    messages, snapshot = engine.build(
        persona="你是电商助手，只依据事实回答。",
        user=User(id="U001", name="张三", role="customer"),
        retrieved_docs=[{"source": "售后政策", "content": "七天无理由退货。"}],
        tools=[{"name": "search_products", "description": "搜索商品"}],
        history=[HumanMessage(content="之前的问题"), AIMessage(content="之前的回答")],
        user_input="推荐耳机",
    )
    assert messages[0].content.startswith("[角色与硬性规则]")
    assert "当前用户: U001" in messages[0].content
    assert "七天无理由退货" in messages[0].content
    assert messages[-1].content == "推荐耳机"
    assert snapshot.total_chars <= 2000
    assert snapshot.kept_messages == 2
    assert all(section["included"] for section in snapshot.sections)


def test_sliding_window_drops_old_turns():
    engine = ContextEngine(max_chars=400, recent_messages=3)
    history = [HumanMessage(content=f"历史问题{i}") for i in range(8)]
    _, snapshot = engine.build(persona="角色", user=User(id="U001", role="customer"),
                               history=history, user_input="新问题")
    assert snapshot.kept_messages <= 3
    assert snapshot.dropped_messages >= 5


def test_long_turn_is_compressed_with_marker():
    engine = ContextEngine(max_chars=500, recent_messages=2)
    messages, snapshot = engine.build(
        persona="角色", user=User(id="U001", role="customer"),
        history=[HumanMessage(content="很长的内容" * 200)], user_input="继续",
    )
    assert any("已压缩" in str(m.content) for m in messages)
    assert snapshot.compressed


def test_estimate_tokens_and_doc_formatting():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abc") == 2
    formatted = ContextEngine.format_docs([{"source": "配送", "content": "满199包邮"}])
    assert "[配送] 满199包邮" in formatted
