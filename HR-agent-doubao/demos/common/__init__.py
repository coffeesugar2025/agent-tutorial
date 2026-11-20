"""全书共用的 LangChain 基础设施。

用法：

    from common import get_model, ai_tool, ai_text, title, section, star, practice

    model = get_model([ai_tool("get_employee", {"emp_id": "E10086"}), ai_text("张伟在技术中心")])
"""

from common.llm import (  # noqa: F401
    BAR,
    ScriptedChatModel,
    ai_text,
    ai_tool,
    get_model,
    has_real_model,
    load_env,
    practice,
    section,
    star,
    title,
)

# 离线向量（第 09、10 章）：没有 Embedding API Key 时也能看到真实的字面相关性
from common.embed import LocalHashEmbedding  # noqa: F401
