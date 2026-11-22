"""Generate Excel test-case workbook for the LangChain 1.5 e-commerce agent."""
from __future__ import annotations

from pathlib import Path

try:
    import openpyxl
except ImportError:
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl>=3.1.0"])
    import openpyxl

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


def xl_color(css_hex: str) -> str:
    value = css_hex.removeprefix("#").upper()
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB, got: {css_hex}")
    return "FF" + value


XL_PRIMARY = xl_color("#4472C4")
XL_DARK = xl_color("#2F5597")
XL_LIGHT = xl_color("#D9E2F3")
XL_WHITE = xl_color("#FFFFFF")
XL_TEXT = xl_color("#1F2937")
XL_BORDER = xl_color("#BFBFBF")
XL_GREY = xl_color("#F2F2F2")
XL_GREEN_BG = xl_color("#C6EFCE")
XL_GREEN_TXT = xl_color("#006100")
XL_RED_BG = xl_color("#FFC7CE")
XL_RED_TXT = xl_color("#9C0006")
XL_YELLOW_BG = xl_color("#FFEB9C")
XL_YELLOW_TXT = xl_color("#9C6500")

THIN = Side(style="thin", color=XL_BORDER)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "Microsoft YaHei"

wb = Workbook()
wb.properties.title = "LangChain_Agent测试用例"

# ---------------------------------------------------------------------------
# Case data: (knowledge point, sub-point, title, precondition, input, steps,
#             expected output, verification, priority, type, automation, case)
# ---------------------------------------------------------------------------
cases: list[tuple[str, ...]] = []


def add(kp, sub, title, pre, inp, steps, expected, verify,
        priority="中", ctype="功能", automation="已自动化", case=""):
    cases.append((kp, sub, title, pre, inp, steps, expected, verify,
                  priority, ctype, automation, case))


# 1. 消息与 BaseChatModel
add("消息与模型", "消息角色", "四类消息构造与序列化",
    "无", "SystemMessage('你是电商助手'); HumanMessage('推荐耳机'); AIMessage('好的'); ToolMessage('{}', tool_call_id='c1', name='search_products')",
    "构造四类消息并读取字段",
    "类型依次为 SystemMessage/HumanMessage/AIMessage/ToolMessage；ToolMessage.tool_call_id='c1'",
    "消息类型与关键字段正确", "中", "单元", "已自动化", "test_message_roles_and_serialization")
add("消息与模型", "BaseChatModel", "离线模型实现模型契约",
    "默认 ECOM_LLM_PROVIDER=offline", "get_model().invoke('你好')",
    "调用 invoke 并查看返回类型与 _llm_type",
    "返回 AIMessage；_llm_type='ecom-rule-based-offline'；content 含'电商智能助手'",
    "模型契约与零 Key 可运行", "高", "单元", "已自动化", "test_base_chat_model_contract")
add("消息与模型", "工具调用协议", "bind_tools 产出 tool_calls",
    "构造 check_inventory 工具", "RuleBasedChatModel().bind_tools([check_inventory]).invoke([HumanMessage('查一下 P001 库存')])",
    "绑定工具后调用模型",
    "AIMessage.tool_calls[0].name='check_inventory'，args.product_id='P001'，id 非空",
    "工具名与参数抽取正确", "高", "单元", "已自动化", "test_bind_tools_emits_tool_call")
add("消息与模型", "工具结果回灌", "ToolMessage 渲染为自然语言",
    "已有 AIMessage(tool_calls)", "AIMessage(content='', tool_calls=[{'name':'check_inventory','id':'c1'}]); ToolMessage('{\"available\":true,\"stock\":7,\"name\":\"耳机\",\"product_id\":\"P001\"}', tool_call_id='c1')",
    "将工具消息传给模型 invoke",
    "答案含'P001'与'7'，形如'耳机（P001）当前库存 7 件，可以下单。'",
    "工具结果被正确格式化", "高", "单元", "已自动化", "test_tool_message_renders_into_answer")
add("消息与模型", "流式接口", "模型 stream 逐块输出",
    "无", "list(RuleBasedChatModel().stream('你好'))",
    "调用 stream 并拼接所有块",
    "每块均为 AIMessage；拼接内容含'电商智能助手'",
    "流式协议可供 SSE 使用", "中", "单元", "已自动化", "test_model_stream_interface")
add("消息与模型", "结构化输出", "response_format 结构化响应",
    "需真实模型（离线模型不支持）", "create_agent(model=ChatOpenAI(...), response_format=Answer).invoke({'messages':[('user','总结订单')]})",
    "切换 ECOM_LLM_PROVIDER=openai 后调用",
    "返回 structured_response 字段且符合 Answer schema；离线模型此场景会递归超时，属已知限制",
    "结构化输出能力边界", "低", "集成", "手工", "")
add("消息与模型", "多轮消息", "历史消息进入模型输入",
    "history 含两轮", "history=[HumanMessage('旧问题'), AIMessage('旧回答')]",
    "经 Supervisor context 节点构建消息",
    "SystemMessage 在前，历史两条居中，当前 HumanMessage 在最后",
    "消息顺序正确", "中", "集成", "手工", "")
add("消息与模型", "Token 估算", "中文字符预算估算",
    "无", "estimate_tokens('') / estimate_tokens('abc')",
    "调用估算函数",
    "空串返回 1；'abc' 返回 2（约 1.5 字符/token）",
    "估算规则确定", "低", "单元", "已自动化", "test_estimate_tokens_and_doc_formatting")

# 2. LCEL
add("LCEL", "Runnable 管道", "Prompt|Model|Parser 链式调用",
    "无", "ChatPromptTemplate.from_template('用户说：{text}') | get_model() | StrOutputParser(); invoke({'text':'你好'})",
    "构造 LCEL 链并 invoke",
    "返回字符串，含'电商智能助手'",
    "管道组合与输出解析", "高", "单元", "已自动化", "test_prompt_model_parser_pipeline")
add("LCEL", "RunnableLambda", "函数包装为 Runnable",
    "无", "RunnableLambda(lambda x: x*2).invoke(3)",
    "构造 Lambda Runnable 并调用",
    "返回 6",
    "Runnable 协议一致", "中", "单元", "已自动化", "test_runnable_lambda_and_parallel")
add("LCEL", "RunnableParallel", "并行分支聚合",
    "无", "RunnableParallel({'doubled': RunnableLambda(lambda x:x*2), 'text': RunnableLambda(lambda x:f'n={x}')}).invoke(3)",
    "并行执行两支并聚合",
    "返回 {'doubled': 6, 'text': 'n=3'}",
    "并行结果与键名正确", "中", "单元", "已自动化", "test_runnable_lambda_and_parallel")
add("LCEL", "批处理", "batch 批量推理",
    "无", "chain.batch([{'text':'你好'},{'text':'你好'}])",
    "一次 batch 调用两条输入",
    "返回长度为 2 的列表，顺序与输入一致",
    "批量顺序保持", "中", "单元", "已自动化", "test_batch_and_callback_events")
add("LCEL", "回调机制", "CallbackHandler 捕获 LLM 生命周期",
    "自定义 Recorder 继承 BaseCallbackHandler", "chain.batch(..., config={'callbacks':[recorder]})",
    "注入回调并执行批量调用",
    "on_llm_start 与 on_llm_end 各触发 2 次",
    "回调注入与事件计数", "中", "单元", "已自动化", "test_batch_and_callback_events")

# 3. Tools
add("工具与调用", "@tool 装饰器", "装饰器自动生成工具 schema",
    "无", "@tool\ndef add(a:int,b:int)->int:\n    '''Add two integers.'''\n    return a+b; add.invoke({'a':2,'b':3})",
    "定义工具并调用 invoke",
    "name='add'；args 含 a、b；返回 5",
    "签名到 schema 的转换", "中", "单元", "已自动化", "test_tool_decorator_generates_schema")
add("工具与调用", "StructuredTool", "业务函数包装为 LangChain 工具",
    "无", "local_tools()",
    "检查工具数量与元数据",
    "返回 8 个工具；search_products.args 含 query；description 含中文说明",
    "工具注册完整性", "高", "单元", "已自动化", "test_structured_tool_from_function")
add("工具与调用", "异步调用", "工具 ainvoke 返回 JSON",
    "当前用户=张三(U001)", "next(t for t in local_tools() if t.name=='check_inventory').ainvoke({'product_id':'P001'})",
    "异步调用库存工具",
    "JSON: available=true, stock=12",
    "异步协议与数据正确", "中", "单元", "已自动化", "test_tool_ainvoke")
add("工具与调用", "异常结构化", "非法 JSON 参数不抛异常",
    "当前用户=张三", "create_order('U001', 'not-json')",
    "直接调用工具函数",
    "返回含 'error' 的 JSON 字符串，不抛未捕获异常",
    "异常降级为结构化结果", "中", "异常", "手工", "")
add("工具与调用", "工具重试", "瞬态失败自动重试",
    "FlakyTool 第一次抛 RuntimeError", "create_agent(...tools=[FlakyTool], middleware=[ToolRetryMiddleware(max_retries=1, initial_delay=0)]).ainvoke({'messages':[HumanMessage('推荐耳机')]})",
    "执行 agent 并统计调用次数",
    "工具执行 2 次；消息序列含 ToolMessage",
    "重试次数与最终结果", "高", "集成", "已自动化", "test_tool_retry_middleware")
add("工具与调用", "工具 Schema", "MCP 工具参数描述可读",
    "MCP 客户端已连接", "client.get_tools() 后读取 name/description/args_schema",
    "列出工具并读取 schema",
    "8 个工具；description 非空；args 含 query / product_id / items_json 等",
    "工具自描述能力", "中", "接口", "手工", "")

# 4. create_agent / 多智能体
add("Agent 与多智能体", "create_agent", "Agent 编译为状态图",
    "无", "create_agent(model=get_model(), tools=local_tools()[:1], name='demo_agent')",
    "调用 get_graph().nodes",
    "节点含 __start__、model、tools、__end__",
    "Agent 图结构正确", "高", "单元", "已自动化", "test_create_agent_compiles_to_graph")
add("Agent 与多智能体", "工具调用回路", "模型→工具→最终答案",
    "当前用户=张三", "agent.ainvoke({'messages':[HumanMessage('推荐降噪耳机')]})",
    "执行 agent 并检查消息序列",
    "消息含 ToolMessage；其中有内容包含 'P001'",
    "工具调用闭环", "高", "集成", "已自动化", "test_agent_runs_tool_and_finalizes")
add("Agent 与多智能体", "角色工具隔离", "四个 specialist 各持最小工具集",
    "当前用户=张三", "await build_specialists(CUSTOMER)",
    "构建 specialist 并检查工具节点",
    "返回 shopping/order/support/general 四个 agent，均含 tools 节点",
    "多智能体工具边界", "高", "集成", "已自动化", "test_specialists_have_scoped_tools")
add("Agent 与多智能体", "意图路由", "Supervisor 分类五种问法",
    "无", "classify_route('推荐一款耳机'/'我的订单在哪里'/'O1001 申请退款'/'保修政策'/'你好')",
    "逐条调用分类函数",
    "依次返回 shopping / order / support / support / general",
    "路由规则正确", "高", "单元", "已自动化", "test_intent_classification")
add("Agent 与多智能体", "图拓扑", "Supervisor 图节点齐备",
    "无", "await build_supervisor(CUSTOMER)",
    "检查 get_graph().nodes",
    "含 context、route、shopping、order、support、general、finalize 七个关键节点",
    "编排图结构完整", "高", "集成", "已自动化", "test_supervisor_graph_routes_to_specialist")
add("Agent 与多智能体", "导购 Agent", "真实商品推荐含价格库存",
    "当前用户=张三", "run_agent('推荐降噪耳机', CUSTOMER, 't-shopping')",
    "执行多智能体链路",
    "route='shopping'；答案含 'P001' 与 '899'",
    "不编造商品", "高", "集成", "已自动化", "test_shopping_agent_recommends_real_product")
add("Agent 与多智能体", "订单 Agent", "订单数据按客户隔离",
    "当前用户=张三(U001)", "run_agent('我的订单', CUSTOMER, 't-order')",
    "执行多智能体链路",
    "route='order'；答案含 'O1001'；不含 'O1002'",
    "订单越权过滤", "高", "集成", "已自动化", "test_order_agent_lists_scoped_orders")
add("Agent 与多智能体", "售后 Agent", "退款申请写回状态",
    "当前用户=张三，O1003 为本人订单", "run_agent('O1003 想退货退款', CUSTOMER, 't-support')",
    "执行多智能体链路并查订单",
    "route='support'；答案含'退款'；O1003.status='refund_requested'",
    "业务副作用正确", "高", "集成", "已自动化", "test_support_agent_applies_refund")

# 5. Middleware
add("中间件", "中间件栈", "内置与自定义中间件装配",
    "无", "build_middleware()",
    "检查类型与参数",
    "含 Summarization/ToolRetry/ModelCallLimit/2×PII/trace_tool_call；trigger=('messages',14)，keep=('messages',6)",
    "生产中间件齐备", "高", "单元", "已自动化", "test_builtin_middleware_config")
add("中间件", "摘要策略", "超长历史触发摘要",
    "历史 ≥14 条消息", "SummarizationMiddleware(model=get_model(), trigger=('messages',14), keep=('messages',6))",
    "构造并检查配置；真实模型下触发压缩",
    "trigger/keep 参数正确；触发后历史压缩为约 6 条并生成摘要",
    "上下文长度治理", "中", "集成", "已自动化", "test_builtin_middleware_config")
add("中间件", "PII 脱敏", "邮箱输入被替换为占位符",
    "无", "create_agent(model=get_model(), middleware=[PIIMiddleware('email', strategy='redact')]).ainvoke({'messages':[HumanMessage('联系我 abc@example.com 谢谢')]})",
    "执行 agent 并检查首条消息",
    "首条 HumanMessage 含 '[REDACTED_EMAIL]'；不含 'abc@example.com'",
    "敏感信息不进入模型", "高", "安全", "已自动化", "test_pii_middleware_redacts_input")
add("中间件", "PII 掩码", "手机号按正则掩码",
    "中间件 detector=r'1[3-9]\\d{9}', strategy='mask'", "用户输入'电话 13812345678'",
    "执行 agent 并检查消息",
    "原文手机号被掩码，不以明文出现",
    "正则检测器生效", "高", "安全", "手工", "")
add("中间件", "调用上限", "模型调用次数设限",
    "run_limit=1, exit_behavior='end'", "create_agent(...middleware=[ModelCallLimitMiddleware(run_limit=1)]).ainvoke({'messages':[HumanMessage('推荐耳机')]})",
    "执行 agent 并统计消息数",
    "图正常结束；消息数 ≤4；无死循环",
    "防止无限循环", "高", "稳定性", "已自动化", "test_model_call_limit_middleware")
add("中间件", "自定义埋点", "wrap_tool_call 记录 trace",
    "current_trace_id='kp-trace'", "run_agent('推荐耳机', CUSTOMER, 'kp-trace')",
    "执行后查询 tracer",
    "trace 中含 node='agent:tool'、event='search_products'",
    "工具调用可观测", "中", "集成", "已自动化", "test_custom_wrap_tool_call_records_trace")

# 6. LangGraph 状态图
add("LangGraph 状态图", "State Reducer", "Annotated 列表跨轮累积",
    "InMemorySaver 作 checkpointer", "graph.invoke({'values':[]}, {'configurable':{'thread_id':'kp-reducer'}}) 连续两次",
    "同一 thread_id 连续调用",
    "第一次 values=['x']；第二次 values=['x','x']",
    "Reducer 语义正确", "高", "单元", "已自动化", "test_state_reducer_accumulates")
add("LangGraph 状态图", "线程隔离", "不同 thread_id 状态独立",
    "同上图", "分别用 thread-a 与 thread-b 调用",
    "跨线程执行",
    "thread-b 的 values=['x']，不受 thread-a 影响",
    "会话状态不串扰", "高", "单元", "已自动化", "test_thread_isolation")
add("LangGraph 状态图", "条件边", "按状态路由到不同节点",
    "定义 left/right 两节点", "graph.invoke({'path':'go-left'}) / graph.invoke({'path':'go-right'})",
    "分别执行两条分支",
    "返回 'go-left-left' / 'go-right-right'",
    "条件路由正确", "高", "单元", "已自动化", "test_conditional_edges")
add("LangGraph 状态图", "流式更新", "astream 逐节点返回增量",
    "节点 a→b", "[u async for u in graph.astream({'seq':[]}, stream_mode='updates')]",
    "异步流式执行",
    "增量节点顺序为 ['a','b']",
    "SSE 事件来源", "中", "单元", "已自动化", "test_astream_updates")
add("LangGraph 状态图", "START/END", "图入口与出口连通",
    "无", "builder.add_edge(START,'a'); builder.add_edge('b',END)",
    "编译并执行",
    "按 a→b 顺序执行并正常结束",
    "图边界定义", "中", "单元", "已自动化", "test_astream_updates")
add("LangGraph 状态图", "图元数据", "可视化接口返回两张图",
    "无", "GET /api/graphs",
    "调用接口",
    "返回 supervisor 与 fulfillment；节点含 context/route 与 validate/risk_review",
    "前端 SVG 渲染数据源", "中", "接口", "已自动化", "test_api.py")

# 7. 检查点与人工审批
add("人工审批与检查点", "中断", "大额订单触发 interrupt",
    "当前用户=管理员；O1001 金额 1098", "run_fulfillment('O1001','U001','kp-hitl')",
    "首次运行工作流",
    "status='awaiting_approval'；interrupt.amount=1098.0；next=('risk_review',)",
    "阈值判断与挂起", "高", "集成", "已自动化", "test_interrupt_then_resume")
add("人工审批与检查点", "状态查询", "挂起状态可持久化查询",
    "已挂起 thread kp-hitl", "get_fulfillment_graph().get_state({'configurable':{'thread_id':'kp-hitl'}})",
    "读取检查点状态",
    "state.interrupts 非空；state.next=('risk_review',)",
    "检查点可恢复", "高", "集成", "已自动化", "test_interrupt_then_resume")
add("人工审批与检查点", "恢复批准", "Command(resume=True) 完成履约",
    "已挂起 thread kp-hitl", "resume_fulfillment('kp-hitl', True)",
    "恢复工作流",
    "status='completed'；订单 O1001 状态 'shipped'",
    "恢复后副作用写回", "高", "集成", "已自动化", "test_interrupt_then_resume")
add("人工审批与检查点", "恢复拒绝", "resume(False) 取消订单",
    "已挂起 thread kp-reject", "resume_fulfillment('kp-reject', False)",
    "恢复并拒绝",
    "status='cancelled'；订单状态 'cancelled'",
    "拒绝分支正确", "高", "集成", "已自动化", "test_reject_branch")
add("人工审批与检查点", "阈值分支", "小额订单跳过审批",
    "新建 129 元订单", "run_fulfillment(order.id, 'U001', f'wf-{order.id}')",
    "运行工作流",
    "status='completed'，不出现 awaiting_approval",
    "阈值以下自动通过", "中", "集成", "已自动化", "test_small_order_skips_approval")
add("人工审批与检查点", "异常分支", "订单不存在结束",
    "无", "run_fulfillment('O9999','U001','wf-missing')",
    "运行工作流",
    "status='not_found'；message='订单不存在'",
    "异常路径闭环", "中", "集成", "已自动化", "test_missing_order_ends_with_not_found")

# 8. MCP
add("MCP 协议", "FastMCP 注册", "Server 注册 8 个工具",
    "无", "await mcp.list_tools()",
    "枚举 FastMCP 工具",
    "长度 8；包含 search_products",
    "工具注册完整", "高", "接口", "已自动化", "test_fastmcp_registers_tools")
add("MCP 协议", "stdio 往返", "客户端 ListTools + CallTool",
    "PYTHONPATH 指向 backend", "MultiServerMCPClient({'ecommerce':{'transport':'stdio','command':sys.executable,'args':['-m','app.mcp.server']}})",
    "启动子进程并列出/调用工具",
    "get_tools() 返回 8 个工具；search_products.ainvoke({'query':'耳机'}) 含 'P001'",
    "真实 MCP 协议可用", "高", "集成", "已自动化", "test_mcp_stdio_roundtrip")
add("MCP 协议", "本地适配器", "进程内工具包装",
    "mcp_mode=local", "load_agent_tools(CUSTOMER)",
    "加载工具并过滤",
    "返回按角色过滤后的 BaseTool 列表；无网络调用",
    "双模式一致性", "中", "集成", "手工", "")
add("MCP 协议", "HTTP 模式", "streamable-http 远程工具",
    "mcp_mode=http 且服务已启动", "ECOM_MCP_MODE=http; ECOM_MCP_HTTP_URL=http://localhost:8000/mcp",
    "配置后调用 load_agent_tools",
    "经 MultiServerMCPClient 获取远程工具；Bearer token 透传",
    "远程传输配置", "中", "集成", "手工", "")
add("MCP 协议", "工具权限过滤", "guest 仅见只读工具",
    "无", "filter_tools(local_tools(), User(id='g', role='guest'))",
    "按角色过滤工具",
    "guest 不含 create_order/initiate_refund；含 search_products",
    "暴露面最小化", "高", "安全", "已自动化", "test_rbac_filters_exposed_tools")

# 9. RAG
add("RAG 检索增强", "Embeddings 接口", "哈希向量确定性与归一化",
    "无", "HashEmbeddings(dimension=64).embed_query('退货政策')",
    "重复调用并计算模长",
    "两次向量相等；长度 64；L2 范数≈1",
    "向量可复现", "高", "单元", "已自动化", "test_embeddings_interface")
add("RAG 检索增强", "中文分词", "bigram/trigram 切分",
    "无", "tokenize('退货政策 refund')",
    "查看 token 集合",
    "含'退货'、'货政'、'退货政'、'refund'",
    "中文召回基础", "中", "单元", "已自动化", "test_chinese_ngram_tokenizer")
add("RAG 检索增强", "向量库", "add_texts 与 similarity_search",
    "InMemoryVectorStore(HashEmbeddings(64))", "store.add_texts(['七天无理由退货','满199包邮'], metadatas=[{'source':'售后政策'},{'source':'配送规则'}]); store.similarity_search('退货', k=2)",
    "写入后检索",
    "返回 2 个 Document；metadata.source 集合为 {'售后政策','配送规则'}",
    "向量库读写", "中", "单元", "已自动化", "test_in_memory_vector_store")
add("RAG 检索增强", "混合召回", "政策类问题召回正确",
    "RAGPipeline(top_k=2)", "pipeline.retrieve('我想知道退货政策')",
    "检索知识库",
    "首条 source='售后政策'；content 含'退货'",
    "词面重排生效", "高", "单元", "已自动化", "test_retrieve_policy_doc")
add("RAG 检索增强", "分类过滤", "只返回指定知识域",
    "RAGPipeline", "pipeline.retrieve('发票怎么开', category='payment')",
    "带 category 参数检索",
    "结果非空且全部 category='payment'；as_context 含'支付与发票'",
    "过滤条件生效", "中", "单元", "已自动化", "test_hybrid_retrieval_and_category_filter")
add("RAG 检索增强", "上下文格式化", "带来源的知识块",
    "RAGPipeline", "pipeline.as_context('发票怎么开')",
    "格式化检索结果",
    "字符串形如'[支付与发票] 发票：支持电子普通发票…'",
    "来源可追溯", "中", "单元", "已自动化", "test_as_context_contains_source")
add("RAG 检索增强", "兜底策略", "空查询返回种子文档",
    "RAGPipeline", "pipeline.retrieve('')",
    "传入空字符串",
    "返回种子文档列表，不抛异常",
    "空输入健壮性", "低", "异常", "手工", "")

# 10. 上下文工程
add("上下文工程", "优先级装箱", "四区块按优先级纳入",
    "max_chars=2000", "ContextEngine(max_chars=2000).build(persona='你是电商助手', user=CUSTOMER, retrieved_docs=[...], tools=[...], history=[...], user_input='推荐耳机')",
    "构建消息与快照",
    "首条为 SystemMessage 含'[角色与硬性规则]'与'当前用户: U001'；sections 优先级 1-4；total_chars≤2000",
    "可解释上下文", "高", "单元", "已自动化", "test_context_build_prioritises_system_and_user_input")
add("上下文工程", "字符预算", "超预算区块被截断或丢弃",
    "max_chars=1200", "engine.build(..., retrieved_docs=[{'source':'长文','content':'x'*2000}])",
    "构建上下文",
    "snapshot.total_chars≤1200；被截断区块 truncated=true",
    "预算不超限", "高", "单元", "手工", "")
add("上下文工程", "滑窗", "旧轮次被丢弃",
    "recent_messages=3", "history=[HumanMessage(f'历史{i}') for i in range(8)]",
    "构建上下文",
    "kept_messages≤3；dropped_messages≥5",
    "短期记忆治理", "中", "单元", "已自动化", "test_sliding_window_drops_old_turns")
add("上下文工程", "压缩标记", "超长单轮被压缩",
    "max_chars=400", "history=[HumanMessage('很长'*200)]",
    "构建上下文",
    "消息含'已压缩'标记；snapshot.compressed=true",
    "长文本保护", "中", "单元", "已自动化", "test_long_turn_is_compressed_with_marker")
add("上下文工程", "工具清单", "工具描述进入系统提示",
    "tools=[{'name':'search_products','description':'搜索商品'}]", "ContextEngine.format_tools(tools)",
    "格式化工具清单",
    "输出'- search_products: 搜索商品'",
    "模型可见工具目录", "中", "单元", "已自动化", "test_estimate_tokens_and_doc_formatting")
add("上下文工程", "预览接口", "上下文预览可观测",
    "当前用户=张三", "GET /api/context/preview?message=我的订单",
    "调用接口",
    "200；snapshot.sections 含 4 区块；messages 首条为 SystemMessage",
    "前端侧栏数据源", "中", "接口", "已自动化", "test_api.py")

# 11. 可观测性
add("可观测性", "Trace 记录", "节点与工具写 trace",
    "trace_id='t-trace'", "run_agent('推荐耳机', CUSTOMER, 't-trace')",
    "执行后查询 tracer",
    "trace 含 node='context' 与 event='search_products'",
    "链路可追溯", "中", "集成", "已自动化", "test_tracer_records_tool_calls")
add("可观测性", "Trace 查询", "按条件读取 trace",
    "已有 trace 数据", "GET /api/traces?limit=20（管理员）",
    "调用管理接口",
    "200；元素含 ts/trace_id/node/event/payload 字段",
    "管理页数据源", "中", "接口", "已自动化", "test_api.py")
add("可观测性", "审计允许", "合法工具调用写审计",
    "当前用户=张三", "get_order('O1001')",
    "调用工具后查询审计",
    "审计含 action='tool.get_order'、decision='allow'",
    "正向审计", "中", "安全", "已自动化", "test_order_scope_and_refund")
add("可观测性", "审计拒绝", "越权调用写 deny",
    "当前用户=李四(U002)", "get_order('O1001')",
    "调用工具后查询审计",
    "返回 permission_denied；审计含 decision='deny'",
    "负向审计", "高", "安全", "已自动化", "test_tool_enforces_customer_scope")
add("可观测性", "Trace 权限", "guest 无法读取 trace",
    "无 token", "GET /api/traces",
    "匿名调用",
    "403 Forbidden",
    "观测数据受保护", "高", "安全", "已自动化", "test_api.py")

# 12. 流式输出
add("流式输出", "SSE 事件序列", "node/route/token/done 齐备",
    "当前用户=张三", "POST /api/chat/stream {'message':'我的订单','thread_id':'t-stream'}",
    "读取 SSE 流并收集事件",
    "事件类型含 node、route、token、done；done 数据含'O1001'",
    "流式协议完整", "高", "接口", "已自动化", "test_stream_emits_node_route_and_answer")
add("流式输出", "节点事件", "context 节点事件可见",
    "同上", "同上",
    "检查 node 事件",
    "存在 event='node' 且 node='context'",
    "进度可视化", "中", "接口", "已自动化", "test_stream_emits_node_route_and_answer")
add("流式输出", "工具事件", "工具调用以 tool 事件推送",
    "当前用户=张三", "POST /api/chat/stream {'message':'推荐耳机'}",
    "收集 tool 事件",
    "tool 事件 data 含 name 与 content（商品数据）",
    "工具过程透明", "中", "接口", "手工", "")
add("流式输出", "上下文事件", "context 快照随流推送",
    "当前用户=张三", "POST /api/chat/stream {'message':'我的订单'}",
    "收集 context 事件",
    "data 含 sections/max_chars/total_chars",
    "前端上下文面板", "中", "接口", "手工", "")
add("流式输出", "分段 token", "答案按 12 字分块",
    "答案长度 >12", "stream_agent(...) 中 token 生成逻辑",
    "拼接所有 token 事件",
    "拼接结果等于 done.data 完整答案",
    "逐字渲染一致", "中", "单元", "手工", "")

# 13. 权限与安全
add("权限与安全", "角色矩阵", "四级角色权限集合",
    "无", "permissions_for('admin'/'customer'/'service'/'guest')",
    "读取权限集合",
    "admin=ALL；customer 含 order:create 不含 order:manage；service 含 audit:read；unknown=guest",
    "RBAC 矩阵正确", "高", "安全", "已自动化", "test_role_permission_matrix")
add("权限与安全", "权限拒绝", "guest 访问订单被拒",
    "当前用户=guest", "require_permission(anonymous_user(), 'order:read')",
    "调用权限校验",
    "抛 PermissionError，消息含'order:read'",
    "默认拒绝", "高", "安全", "已自动化", "test_require_permission_denies_guest")
add("权限与安全", "Token 签名", "HMAC 篡改检测",
    "secret='test-secret'", "decode_token(issue_token(CUSTOMER,'test-secret',ttl=60)+'tampered','test-secret')",
    "验证签名与错误密钥",
    "篡改或错误密钥均返回 None；正确密钥返回 sub='U001'",
    "令牌完整性", "高", "安全", "已自动化", "test_token_issue_and_tamper_detection")
add("权限与安全", "Token 过期", "过期令牌失效",
    "ttl=-1", "decode_token(issue_token(CUSTOMER,'secret',ttl=-1),'secret')",
    "解码过期令牌",
    "返回 None",
    "时效性校验", "高", "安全", "已自动化", "test_token_signature_and_expiry")
add("权限与安全", "客户数据隔离", "跨客户订单查询被拒",
    "张三登录", "GET /api/orders?customer_id=U002（张三 token）",
    "调用接口",
    "403 Forbidden；访问 /api/orders/O1002 亦为 403",
    "水平越权拦截", "高", "安全", "已自动化", "test_customer_order_scope")
add("权限与安全", "客服跨客户", "客服可处理他人订单",
    "王客服登录", "GET /api/orders?customer_id=U002",
    "调用接口",
    "200；返回 U002 的订单",
    "垂直授权正确", "中", "安全", "已自动化", "test_service_can_cross_scope_but_not_manage_users")
add("权限与安全", "工具二次鉴权", "绕过 API 直接调工具也拒绝",
    "当前用户=李四", "list_orders('U002') 时当前用户为张三",
    "直接调用工具函数",
    "返回 permission_denied；写审计 deny",
    "纵深防御", "高", "安全", "已自动化", "test_tool_enforces_customer_scope")
add("权限与安全", "状态隔离", "测试间仓库状态重置",
    "pytest fixture clean_state", "reset_repository(); get_repository().get_product('P001').stock",
    "新用例开始检查",
    "商品数≥8；P001 库存=12",
    "用例互不污染", "中", "稳定性", "已自动化", "test_reset_repository_is_deterministic")

# 14. 前端与可视化
add("前端与可视化", "SSE 解析", "前端按帧解析事件",
    "token 已写入 localStorage", "chatStream(message, threadId, onEvent)",
    "模拟 fetch 返回 SSE 文本",
    "onEvent 依次收到 node/route/token/done 回调",
    "前后端协议一致", "高", "接口", "已自动化", "frontend/tests/api.spec.ts")
add("前端与可视化", "图渲染", "GraphFlow 渲染节点标签",
    "传入 graph props", "mount(GraphFlow, {props:{graph}})",
    "挂载组件",
    "SVG 中出现所有节点 label 与边",
    "工作流可视化", "中", "单元", "已自动化", "frontend/tests/graph.spec.ts")
add("前端与可视化", "角色切换", "管理页切换演示账号",
    "无", "管理页选择'管理员'并登录（密码 123456）",
    "登录后查看权限矩阵",
    "角色显示 admin；权限矩阵含 user:manage",
    "演示体验", "低", "功能", "手工", "")
add("前端与可视化", "生产构建", "vue-tsc 与 Vite 构建通过",
    "npm install 完成", "npm run build",
    "执行构建",
    "无类型错误；生成 dist/ 产物",
    "交付可部署", "高", "构建", "已自动化", "npm run build")

# ---------------------------------------------------------------------------
# Sheet 1: 用例总览
# ---------------------------------------------------------------------------
ws_sum = wb.active
ws_sum.title = "用例总览"
ws_sum.merge_cells("A1:H1")
ws_sum["A1"] = "LangChain 1.5 电商智能体｜测试用例总览"
ws_sum["A1"].font = Font(name=FONT, size=16, bold=True, color=XL_WHITE)
ws_sum["A1"].fill = PatternFill("solid", fgColor=XL_DARK)
ws_sum["A1"].alignment = Alignment(horizontal="center", vertical="center")
ws_sum.row_dimensions[1].height = 30

ws_sum["A2"] = "说明：明细页填写「实际输出」后，本页指标与覆盖矩阵自动更新。输入/预期输出均为项目实测值。"
ws_sum["A2"].font = Font(name=FONT, size=10, color=XL_TEXT)
ws_sum.merge_cells("A2:H2")

# KPI block anchors: labels A4:A9, values B4:B9
kpis = [
    ("总用例数", "=COUNTA('测试用例明细'!$A$4:$A$200)"),
    ("已自动化", "=COUNTIF('测试用例明细'!$M$4:$M$200,\"已自动化\")"),
    ("手工用例", "=COUNTIF('测试用例明细'!$M$4:$M$200,\"手工\")"),
    ("高优先级", "=COUNTIF('测试用例明细'!$K$4:$K$200,\"高\")"),
    ("覆盖知识点", "=COUNTA('知识点覆盖矩阵'!$A$4:$A$30)"),
    ("自动化率", "=IF(OR(B4=\"\",B4=0),\"\",B5/B4)"),
]
for i, (label, formula) in enumerate(kpis, start=4):
    ws_sum[f"A{i}"] = label
    ws_sum[f"B{i}"] = formula
    ws_sum[f"A{i}"].font = Font(name=FONT, bold=True, color=XL_TEXT)
    ws_sum[f"A{i}"].fill = PatternFill("solid", fgColor=XL_LIGHT)
    ws_sum[f"B{i}"].font = Font(name=FONT, bold=True, color=XL_DARK)
    ws_sum[f"A{i}"].border = ws_sum[f"B{i}"].border = BORDER
    ws_sum[f"A{i}"].alignment = Alignment(horizontal="center", vertical="center")
    ws_sum[f"B{i}"].alignment = Alignment(horizontal="center", vertical="center")
ws_sum["B9"].number_format = "0.0%"

# Coverage table anchors: header row 11, data rows 12..
sum_header = ["知识点", "用例数", "已自动化", "手工", "自动化率", "覆盖状态"]
for col, name in enumerate(sum_header, start=1):
    cell = ws_sum.cell(row=11, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = BORDER

kp_order = []
for row in cases:
    if row[0] not in kp_order:
        kp_order.append(row[0])

for idx, kp in enumerate(kp_order, start=12):
    ws_sum.cell(row=idx, column=1, value=kp)
    ws_sum.cell(row=idx, column=2, value=f"=COUNTIF('测试用例明细'!$B$4:$B$200,A{idx})")
    ws_sum.cell(row=idx, column=3, value=f"=COUNTIFS('测试用例明细'!$B$4:$B$200,A{idx},'测试用例明细'!$M$4:$M$200,\"已自动化\")")
    ws_sum.cell(row=idx, column=4, value=f"=COUNTIFS('测试用例明细'!$B$4:$B$200,A{idx},'测试用例明细'!$M$4:$M$200,\"手工\")")
    ws_sum.cell(row=idx, column=5, value=f'=IF(OR(B{idx}="",B{idx}=0),"",C{idx}/B{idx})')
    ws_sum.cell(row=idx, column=6, value=f'=IF(B{idx}=0,"未覆盖",IF(C{idx}=0,"仅手工","已覆盖"))')
    ws_sum.cell(row=idx, column=5).number_format = "0.0%"
    for col in range(1, 7):
        c = ws_sum.cell(row=idx, column=col)
        c.border = BORDER
        c.font = Font(name=FONT, color=XL_TEXT)
        c.alignment = Alignment(horizontal="center" if col > 1 else "left", vertical="center")

sum_last = 11 + len(kp_order)
ws_sum.conditional_formatting.add(
    f"F12:F{sum_last}",
    FormulaRule(formula=['F12="已覆盖"'], fill=PatternFill("solid", fgColor=XL_GREEN_BG),
                font=Font(color=XL_GREEN_TXT)),
)
ws_sum.conditional_formatting.add(
    f"F12:F{sum_last}",
    FormulaRule(formula=['F12="未覆盖"'], fill=PatternFill("solid", fgColor=XL_RED_BG),
                font=Font(color=XL_RED_TXT)),
)
ws_sum.conditional_formatting.add(
    f"F12:F{sum_last}",
    FormulaRule(formula=['F12="仅手工"'], fill=PatternFill("solid", fgColor=XL_YELLOW_BG),
                font=Font(color=XL_YELLOW_TXT)),
)

# Bar chart of case counts per knowledge point
chart = BarChart()
chart.type = "bar"
chart.style = 10
chart.title = "各知识点用例数"
chart.y_axis.title = "知识点"
chart.x_axis.title = "用例数"
chart.height = 12
chart.width = 18
data_ref = Reference(ws_sum, min_col=2, min_row=11, max_row=sum_last)
cats_ref = Reference(ws_sum, min_col=1, min_row=12, max_row=sum_last)
chart.add_data(data_ref, titles_from_data=True)
chart.set_categories(cats_ref)
chart.series[0].graphicalProperties.solidFill = "4472C4"
ws_sum.add_chart(chart, "H4")

for col, width in {"A": 24, "B": 12, "C": 12, "D": 10, "E": 12, "F": 14, "G": 3, "H": 3}.items():
    ws_sum.column_dimensions[col].width = width
ws_sum.sheet_view.showGridLines = False

# ---------------------------------------------------------------------------
# Sheet 2: 测试用例明细
# ---------------------------------------------------------------------------
ws_detail = wb.create_sheet("测试用例明细")
headers = ["用例编号", "知识点", "子知识点", "用例标题", "前置条件", "输入", "执行步骤/调用",
           "预期输出", "实际输出（填写）", "验证要点", "优先级", "用例类型", "自动化状态", "对应自动化用例"]
title_row, header_row, data_start = 1, 3, 4
ws_detail.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws_detail.cell(row=1, column=1, value="测试用例明细（输入 → 预期输出）")
ws_detail.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_detail.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_detail.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_detail.row_dimensions[1].height = 28
ws_detail.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
ws_detail.cell(row=2, column=1, value="「实际输出（填写）」列留空供执行人填写；输入与预期输出来自项目实测值。")
ws_detail.cell(row=2, column=1).font = Font(name=FONT, size=10, color=XL_TEXT)

for col, name in enumerate(headers, start=1):
    cell = ws_detail.cell(row=header_row, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = BORDER
ws_detail.row_dimensions[header_row].height = 30

for r, row in enumerate(cases, start=data_start):
    cid = f"TC-{r - data_start + 1:03d}"
    values = [cid, *row[:8], "", *row[8:]]
    # row = (kp, sub, title, pre, inp, steps, expected, verify, priority, ctype, automation, case)
    # values: cid, kp, sub, title, pre, inp, steps, expected, verify, "", priority, ctype, automation, case
    values = [cid, row[0], row[1], row[2], row[3], row[4], row[5], row[6],
              "", row[7], row[8], row[9], row[10], row[11]]
    for col, value in enumerate(values, start=1):
        cell = ws_detail.cell(row=r, column=col, value=value)
        cell.font = Font(name=FONT, size=10, color=XL_TEXT)
        cell.border = BORDER
        cell.alignment = Alignment(vertical="top", wrap_text=True,
                                   horizontal="center" if col in (1, 11, 12, 13) else "left")
        if col == 9:
            cell.fill = PatternFill("solid", fgColor=xl_color("#FFF9E6"))
    ws_detail.row_dimensions[r].height = 58

detail_last = data_start + len(cases) - 1
ws_detail.auto_filter.ref = f"A{header_row}:N{detail_last}"
ws_detail.freeze_panes = "D4"
ws_detail.sheet_view.showGridLines = False

widths = {"A": 11, "B": 18, "C": 15, "D": 26, "E": 24, "F": 52, "G": 28,
          "H": 52, "I": 24, "J": 22, "K": 9, "L": 10, "M": 12, "N": 36}
for col, width in widths.items():
    ws_detail.column_dimensions[col].width = width

for col_letter, options in (("K", "高,中,低"), ("L", "功能,单元,集成,接口,安全,稳定性,异常,构建"),
                            ("M", "已自动化,手工")):
    dv = DataValidation(type="list", formula1=f'"{options}"', allow_blank=False)
    dv.error = "请从下拉列表中选择"
    dv.errorTitle = "无效输入"
    ws_detail.add_data_validation(dv)
    dv.add(f"{col_letter}{data_start}:{col_letter}{detail_last}")

ws_detail.conditional_formatting.add(
    f"K{data_start}:K{detail_last}",
    CellIsRule(operator="equal", formula=['"高"'], fill=PatternFill("solid", fgColor=XL_RED_BG),
               font=Font(color=XL_RED_TXT)),
)
ws_detail.conditional_formatting.add(
    f"M{data_start}:M{detail_last}",
    CellIsRule(operator="equal", formula=['"手工"'], fill=PatternFill("solid", fgColor=XL_YELLOW_BG),
               font=Font(color=XL_YELLOW_TXT)),
)

# ---------------------------------------------------------------------------
# Sheet 3: 知识点覆盖矩阵
# ---------------------------------------------------------------------------
ws_cov = wb.create_sheet("知识点覆盖矩阵")
cov_headers = ["知识点", "核心 API / 组件", "用例数", "已自动化", "手工", "自动化率", "覆盖状态"]
for col, name in enumerate(cov_headers, start=1):
    cell = ws_cov.cell(row=3, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = BORDER
ws_cov.cell(row=1, column=1, value="LangChain / Agent 知识点覆盖矩阵")
ws_cov.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_cov.merge_cells("A1:G1")
ws_cov.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_cov.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_cov.row_dimensions[1].height = 28

api_map = {
    "消息与模型": "BaseChatModel / AIMessage / ToolMessage / bind_tools",
    "LCEL": "Runnable / ChatPromptTemplate / StrOutputParser / callbacks",
    "工具与调用": "@tool / StructuredTool / ainvoke / ToolRetryMiddleware",
    "Agent 与多智能体": "create_agent / StateGraph / supervisor / specialist",
    "中间件": "Summarization / PII / ModelCallLimit / wrap_tool_call",
    "LangGraph 状态图": "StateGraph / START / END / conditional_edges / reducer",
    "人工审批与检查点": "interrupt / Command(resume) / InMemorySaver / get_state",
    "MCP 协议": "FastMCP / MultiServerMCPClient / stdio / streamable-http",
    "RAG 检索增强": "Embeddings / InMemoryVectorStore / similarity_search",
    "上下文工程": "ContextEngine / ContextSnapshot / compact / 优先级装箱",
    "可观测性": "tracer / audit logger / ContextVar / trace API",
    "流式输出": "astream / stream_mode=updates / SSE token/done",
    "权限与安全": "RBAC / HMAC Token / filter_tools / 二次鉴权",
    "前端与可视化": "chatStream / GraphFlow / vue-tsc / Vite",
}

for idx, kp in enumerate(kp_order, start=4):
    ws_cov.cell(row=idx, column=1, value=kp)
    ws_cov.cell(row=idx, column=2, value=api_map.get(kp, ""))
    ws_cov.cell(row=idx, column=3, value=f"=COUNTIF('测试用例明细'!$B$4:$B$200,A{idx})")
    ws_cov.cell(row=idx, column=4, value=f"=COUNTIFS('测试用例明细'!$B$4:$B$200,A{idx},'测试用例明细'!$M$4:$M$200,\"已自动化\")")
    ws_cov.cell(row=idx, column=5, value=f"=COUNTIFS('测试用例明细'!$B$4:$B$200,A{idx},'测试用例明细'!$M$4:$M$200,\"手工\")")
    ws_cov.cell(row=idx, column=6, value=f'=IF(OR(C{idx}="",C{idx}=0),"",D{idx}/C{idx})')
    ws_cov.cell(row=idx, column=7, value=f'=IF(C{idx}=0,"未覆盖",IF(D{idx}=0,"仅手工","已覆盖"))')
    ws_cov.cell(row=idx, column=6).number_format = "0.0%"
    for col in range(1, 8):
        c = ws_cov.cell(row=idx, column=col)
        c.border = BORDER
        c.font = Font(name=FONT, color=XL_TEXT)
        c.alignment = Alignment(horizontal="left" if col in (1, 2) else "center", vertical="center",
                                wrap_text=(col == 2))

cov_last = 3 + len(kp_order)
for status, bg, fg in (("已覆盖", XL_GREEN_BG, XL_GREEN_TXT), ("未覆盖", XL_RED_BG, XL_RED_TXT),
                       ("仅手工", XL_YELLOW_BG, XL_YELLOW_TXT)):
    ws_cov.conditional_formatting.add(
        f"G4:G{cov_last}",
        FormulaRule(formula=[f'G4="{status}"'], fill=PatternFill("solid", fgColor=bg),
                    font=Font(color=fg)),
    )
for col, width in {"A": 20, "B": 58, "C": 10, "D": 12, "E": 10, "F": 12, "G": 14}.items():
    ws_cov.column_dimensions[col].width = width
ws_cov.freeze_panes = "A4"
ws_cov.auto_filter.ref = f"A3:G{cov_last}"
ws_cov.sheet_view.showGridLines = False

# ---------------------------------------------------------------------------
# Sheet 4: 测试账号与数据
# ---------------------------------------------------------------------------
ws_data = wb.create_sheet("测试账号与数据")
ws_data.cell(row=1, column=1, value="演示账号、种子商品与订单（输入数据来源）")
ws_data.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_data.merge_cells("A1:E1")
ws_data.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_data.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_data.row_dimensions[1].height = 28

sections = [
    ("演示账号（密码统一 123456）", ["用户名", "用户ID", "角色", "关键权限", "说明"], [
        ["张三", "U001", "customer", "order:read/create/refund", "主要演示账号，含 O1001/O1003"],
        ["李四", "U002", "customer", "order:read/create/refund", "用于越权拦截演示"],
        ["王客服", "S001", "service", "audit:read / order:manage", "客服跨客户查询"],
        ["管理员", "A001", "admin", "ALL", "工作流审批与管理页"],
        ["访客", "anonymous", "guest", "product:read / chat:use", "无下单与订单查询权限"],
    ]),
    ("种子商品（部分）", ["ID", "名称", "价格", "初始库存", "用途"], [
        ["P001", "无线降噪耳机 Pro", 899.0, 12, "导购/库存/大额订单"],
        ["P008", "随行马克杯", 129.0, 100, "下单与小额订单"],
    ]),
    ("种子订单", ["ID", "客户", "金额", "初始状态", "用途"], [
        ["O1001", "U001", 1098.0, "created", "大额审批中断→发货"],
        ["O1002", "U002", 129.0, "created", "李四本人订单/张三越权目标"],
        ["O1003", "U001", 899.0, "created", "退款申请演示"],
    ]),
    ("知识库分类", ["category", "source", "典型问题", "", ""], [
        ["policy", "售后政策", "退货多久到账 / 保修政策", "", ""],
        ["logistics", "配送规则", "满多少包邮 / 何时发货", "", ""],
        ["payment", "支付与发票", "发票怎么开", "", ""],
        ["promotion", "优惠规则", "优惠券规则", "", ""],
    ]),
]

row = 3
for title, header, rows in sections:
    ws_data.cell(row=row, column=1, value=title)
    ws_data.cell(row=row, column=1).font = Font(name=FONT, bold=True, color=XL_DARK)
    ws_data.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    row += 1
    for col, name in enumerate(header, start=1):
        c = ws_data.cell(row=row, column=col, value=name)
        c.font = Font(name=FONT, bold=True, color=XL_WHITE)
        c.fill = PatternFill("solid", fgColor=XL_PRIMARY)
        c.border = BORDER
        c.alignment = Alignment(horizontal="center")
    row += 1
    for values in rows:
        for col, value in enumerate(values, start=1):
            c = ws_data.cell(row=row, column=col, value=value)
            c.border = BORDER
            c.font = Font(name=FONT, color=XL_TEXT)
            c.alignment = Alignment(vertical="center", wrap_text=True)
            if header[col - 1] == "价格" or header[col - 1] == "金额":
                c.number_format = '¥#,##0.00'
        row += 1
    row += 1

for col, width in {"A": 18, "B": 22, "C": 18, "D": 16, "E": 34}.items():
    ws_data.column_dimensions[col].width = width
ws_data.sheet_view.showGridLines = False

out_path = Path(r"C:/Users/a1572/WorkBuddy/2026-11-22-16-26-05/docs/LangChain_Agent测试用例.xlsx")
wb.save(out_path)
print(f"saved {out_path} with {len(cases)} cases, {len(kp_order)} knowledge points, sheets={wb.sheetnames}")
