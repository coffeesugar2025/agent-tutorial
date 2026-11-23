"""Generate product-level test-case workbook for the e-commerce LangChain agent."""
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
XL_GREEN_BG = xl_color("#C6EFCE")
XL_GREEN_TXT = xl_color("#006100")
XL_RED_BG = xl_color("#FFC7CE")
XL_RED_TXT = xl_color("#9C0006")
XL_YELLOW_BG = xl_color("#FFEB9C")
XL_YELLOW_TXT = xl_color("#9C6500")
XL_INPUT_BG = xl_color("#FFF9E6")

THIN = Side(style="thin", color=XL_BORDER)
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "Microsoft YaHei"

wb = Workbook()
wb.properties.title = "产品级测试用例"

# ---------------------------------------------------------------------------
# Case data tuple:
# module, role, title, precondition, input, steps, expected, verify,
# primary_kp, related_kp, api, priority, type, automation, automated_case
# ---------------------------------------------------------------------------
cases: list[tuple[str, ...]] = []


def add(module, role, title, pre, inp, steps, expected, verify,
        kp, related, api, priority="中", ctype="功能", automation="已自动化", case=""):
    cases.append((module, role, title, pre, inp, steps, expected, verify,
                  kp, related, api, priority, ctype, automation, case))


# 1. 智能对话
add("智能对话", "customer/张三", "快捷提问推荐降噪耳机",
    "张三已登录，服务使用离线模型", "对话输入：推荐降噪耳机",
    "点击快捷提问或输入问题，等待 SSE 结束",
    "route=shopping；答案含 P001、899 元、库存 12；不出现其他商品",
    "导购只报真实商品与库存", "Agent 与多智能体", "消息与模型 / 工具与调用 / 上下文工程",
    "classify_route / create_agent / search_products", "高", "功能", "已自动化",
    "test_shopping_agent_recommends_real_product")
add("智能对话", "customer/张三", "查询指定商品库存",
    "张三已登录", "对话输入：查一下 P001 库存",
    "输入问题并观察工具 chip 与回答",
    "调用 check_inventory；答案含 P001 与库存 12，提示可以下单",
    "工具调用与自然语言渲染一致", "工具与调用", "消息与模型 / Agent 与多智能体",
    "bind_tools / ToolMessage / check_inventory", "高", "功能", "已自动化",
    "test_bind_tools_emits_tool_call")
add("智能对话", "customer/张三", "查询本人订单列表",
    "张三已登录（U001）", "对话输入：我的订单",
    "输入问题并查看回答",
    "route=order；答案含 O1001、O1003；不含李四的 O1002",
    "会话身份驱动数据隔离", "Agent 与多智能体", "权限与安全 / 工具与调用",
    "list_orders / require_customer_scope", "高", "安全", "已自动化",
    "test_order_agent_lists_scoped_orders")
add("智能对话", "customer/张三", "按订单号查询订单状态",
    "张三已登录，O1001 为本人订单", "对话输入：O1001 订单状态",
    "输入问题并查看回答",
    "route=order；答案含订单 O1001 与状态 shipped、金额 1098",
    "订单号参数抽取正确", "Agent 与多智能体", "工具与调用",
    "get_order / RuleBasedChatModel._args_for", "中", "功能", "手工", "")
add("智能对话", "customer/张三", "对话中发起退款申请",
    "张三已登录，O1003 为本人订单", "对话输入：O1003 想退货退款",
    "输入问题，随后查询订单状态与审计",
    "route=support；答案含退款与 O1003；订单状态变为 refund_requested；审计有 allow 记录",
    "对话可产生真实业务副作用", "Agent 与多智能体", "工具与调用 / 可观测性",
    "initiate_refund / AuditLogger", "高", "功能", "已自动化",
    "test_support_agent_applies_refund")
add("智能对话", "customer/张三", "售后政策知识问答",
    "知识库已 ingest", "对话输入：保修政策是什么",
    "输入问题，观察 RAG 检索与回答",
    "route=support；调用 rag_search；答案含数码 12 个月、家具 36 个月",
    "政策回答有知识来源", "RAG 检索增强", "Agent 与多智能体 / 上下文工程",
    "retrieve / as_context / rag_search", "高", "功能", "已自动化", "test_retrieve_policy_doc")
add("智能对话", "guest/访客", "发票政策问答无需登录",
    "未登录访问聊天页", "对话输入：发票怎么开",
    "直接提问并查看结果",
    "返回知识库中发票条目；答案含电子普通发票、1-2 个工作日",
    "访客可用政策问答能力", "RAG 检索增强", "权限与安全 / 上下文工程",
    "rag_search / guest 权限", "中", "功能", "手工", "")
add("智能对话", "customer/张三", "普通寒暄走通用 Agent",
    "张三已登录", "对话输入：你好",
    "输入问题并查看路由与回答",
    "route=general；返回欢迎语，包含能力清单，不调用业务工具",
    "无明确意图时安全兜底", "消息与模型", "Agent 与多智能体",
    "classify_route / _greeting", "中", "功能", "已自动化", "test_intent_classification")
add("智能对话", "customer/张三", "多轮追问保留上下文",
    "已完成上一轮推荐", "第 1 轮：推荐降噪耳机；第 2 轮：它多少钱",
    "连续两轮对话，查看上下文侧栏历史消息",
    "第 2 轮仍返回商品与价格；上下文快照 kept_messages>0，历史消息进入 SystemMessage 之后",
    "短期记忆跨轮生效", "上下文工程", "消息与模型 / 中间件",
    "ConversationStore / compact / SummarizationMiddleware", "中", "功能", "手工", "")
add("智能对话", "customer/张三", "邮箱输入被自动脱敏",
    "中间件已装配 PIIMiddleware", "对话输入：联系我 abc@example.com 谢谢",
    "输入后检查上下文消息",
    "送入模型的消息含 [REDACTED_EMAIL]；原始邮箱不出现",
    "敏感信息不进入模型", "中间件", "上下文工程 / 权限与安全",
    "PIIMiddleware(strategy=redact)", "高", "安全", "已自动化",
    "test_pii_middleware_redacts_input")
add("智能对话", "customer/张三", "手机号按正则掩码",
    "PIIMiddleware detector=1[3-9]\\d{9}", "对话输入：电话 13812345678",
    "输入后查看上下文消息",
    "手机号被掩码，不以明文出现在模型输入",
    "正则检测器生效", "中间件", "权限与安全",
    "PIIMiddleware(strategy=mask)", "高", "安全", "手工", "")
add("智能对话", "customer/张三", "SSE 实时展示节点与答案",
    "张三已登录", "POST /api/chat/stream {message:我的订单, thread_id:t1}",
    "读取事件流并在前端观察逐段渲染",
    "事件含 node、route、context、tool、token、done；token 拼接等于 done.data",
    "流式协议完整且一致", "流式输出", "LangGraph 状态图 / 前端与可视化",
    "astream(stream_mode=updates) / SSE", "高", "接口", "已自动化",
    "test_stream_emits_node_route_and_answer")
add("智能对话", "customer/张三", "上下文工程侧栏可解释",
    "张三已登录", "GET /api/context/preview?message=我的订单",
    "打开侧栏并展开快照",
    "snapshot.sections 含角色与硬性规则、用户身份、检索增强知识、可用工具清单四块，标注 chars/included",
    "注入内容对用户可见可解释", "上下文工程", "可观测性 / 前端与可视化",
    "ContextEngine.build / ContextSnapshot", "中", "功能", "已自动化",
    "test_context_preview_rag_and_graphs")

# 2. 商品与库存
add("商品与库存", "guest/访客", "按关键词搜索商品",
    "无", "GET /api/products?query=耳机",
    "访问商品页搜索框输入耳机",
    "返回 P001 无线降噪耳机 Pro，价格 899，库存 12；不包含无关商品",
    "中文检索命中", "工具与调用", "RAG 检索增强",
    "search_products / tokenize", "高", "功能", "已自动化", "test_search_and_inventory")
add("商品与库存", "guest/访客", "按品类筛选商品",
    "无", "GET /api/products?category=数码",
    "在商品页选择数码品类",
    "仅返回 category=数码 的商品（P001、P004、P005、P006）",
    "筛选条件生效", "工具与调用", "Agent 与多智能体",
    "list_products(category)", "中", "功能", "手工", "")
add("商品与库存", "customer/张三", "缺货商品如实提示",
    "P007 初始库存 0", "对话输入：P007 有货吗",
    "输入问题查看工具结果与回答",
    "check_inventory 返回 available=false；答案提示暂时缺货，不引导下单",
    "不虚构库存", "工具与调用", "消息与模型",
    "check_inventory / _format_tool_result", "高", "功能", "手工", "")
add("商品与库存", "customer/张三", "商品不存在返回结构化错误",
    "无", "GET /api/products/P999",
    "请求不存在的商品 id",
    "返回 404，detail=商品不存在；前端展示错误提示不崩溃",
    "异常路径闭环", "工具与调用", "前端与可视化",
    "get_product / HTTPException", "中", "异常", "手工", "")
add("商品与库存", "customer/张三", "商品卡一键带入对话",
    "商品页已加载", "点击 P001 卡片的向助手咨询按钮",
    "点击后观察跳转与输入框",
    "跳转到 /chat?q=无线降噪耳机 Pro 相关描述，输入框自动预填该问题",
    "跨页面传参正确", "前端与可视化", "流式输出",
    "router query / chatStream", "中", "功能", "手工", "")
add("商品与库存", "customer/张三", "对话中下单扣减库存",
    "P008 初始库存 100", "对话输入：我要买 P008",
    "输入下单意图并查看新库存",
    "调用 create_order；答案含订单号与合计 129；P008 库存变为 99",
    "对话下单与库存联动", "工具与调用", "Agent 与多智能体 / 可观测性",
    "create_order / decrease_stock / AuditLogger", "高", "功能", "已自动化",
    "test_create_order_decreases_stock_and_audits")
add("商品与库存", "customer/张三", "库存不足时拒绝下单",
    "P007 库存 0", "POST /api/orders {items:[{product_id:P007,quantity:1}]}",
    "提交无货商品订单",
    "返回 400，detail 含库存不足；不生成订单、不写审计 allow",
    "库存校验前置", "工具与调用", "权限与安全",
    "create_order / ValueError", "高", "异常", "手工", "")
add("商品与库存", "guest/访客", "MCP 工具清单对外一致",
    "MCP Server 可启动", "mcp.list_tools() 或 stdio ListTools",
    "枚举工具并核对名称",
    "返回 8 个工具，含 search_products 与 create_order；名称与进程内工具一致",
    "工具单一真源", "MCP 协议", "工具与调用",
    "FastMCP / MultiServerMCPClient", "中", "接口", "已自动化",
    "test_real_mcp_stdio_roundtrip")
add("商品与库存", "customer/张三", "RAG 检索面板返回来源",
    "知识库已 ingest", "GET /api/rag/search?q=退货政策",
    "在管理页打开 RAG 检索面板",
    "结果首条 source=售后政策，content 含七天无理由退货与 1-3 个工作日",
    "来源可追溯", "RAG 检索增强", "上下文工程",
    "RAGPipeline.retrieve / metadata.source", "中", "功能", "已自动化", "test_rag_tool")

# 3. 订单与退款
add("订单与退款", "customer/张三", "订单页只看本人订单",
    "张三已登录", "GET /api/orders",
    "打开订单页查看列表",
    "返回 2 笔订单 O1001、O1003；按创建时间倒序",
    "客户级数据隔离", "权限与安全", "工具与调用",
    "require_customer_scope / list_orders", "高", "安全", "已自动化",
    "test_customer_order_scope")
add("订单与退款", "customer/张三", "带他人客户号查询被拒",
    "张三已登录", "GET /api/orders?customer_id=U002",
    "手工篡改请求参数访问李四订单",
    "返回 403，detail 含无权访问 U002；不返回任何订单",
    "水平越权拦截", "权限与安全", "Agent 与多智能体",
    "require_customer_scope", "高", "安全", "已自动化", "test_customer_order_scope")
add("订单与退款", "service/王客服", "客服跨客户查询订单",
    "王客服已登录（service）", "GET /api/orders?customer_id=U002",
    "客服工作台查询李四订单",
    "返回 200 且含 O1002 明细；审计记录客服访问",
    "垂直授权正确", "权限与安全", "可观测性",
    "can_access_customer / order:manage", "中", "安全", "已自动化",
    "test_service_can_cross_scope_but_not_manage_users")
add("订单与退款", "customer/张三", "API 创建订单",
    "P008 库存 100", "POST /api/orders {items:[{product_id:P008,quantity:2}]}",
    "在订单页选择 P008 数量 2 并提交",
    "返回 201；total=258.00；status=created；P008 库存减为 98；审计写入 allow",
    "金额与库存一致", "工具与调用", "可观测性",
    "create_order / AuditLogger", "高", "功能", "已自动化",
    "test_products_and_order_creation")
add("订单与退款", "customer/张三", "订单详情按归属校验",
    "张三已登录", "GET /api/orders/O1002",
    "直接访问李四订单详情 URL",
    "返回 403，detail 含无权访问；不泄漏金额与地址",
    "详情接口同样隔离", "权限与安全", "工具与调用",
    "get_order / require_customer_scope", "高", "安全", "手工", "")
add("订单与退款", "customer/张三", "申请退款写回状态与审计",
    "O1003 为 delivered 且属张三", "POST /api/orders/O1003/refund {reason:尺码不合适}",
    "在订单页点击退款并填写原因",
    "返回 status=refund_requested；审计 action=api.refund，detail 含原因",
    "退款状态与审计一致", "工具与调用", "可观测性",
    "request_refund / AuditLogger", "高", "功能", "已自动化", "test_order_scope_and_refund")
add("订单与退款", "customer/李四", "跨客户退款被拒并记 deny",
    "李四已登录（U002）", "POST /api/orders/O1001/refund {reason:退款}",
    "李四尝试对张三订单退款",
    "返回 403；审计出现 actor=U002、decision=deny",
    "负向审计可追溯", "权限与安全", "可观测性",
    "require_customer_scope / _deny", "高", "安全", "已自动化",
    "test_tool_enforces_customer_scope")
add("订单与退款", "customer/张三", "重复退款幂等性",
    "O1003 已为 refund_requested", "再次 POST /api/orders/O1003/refund",
    "重复点击退款按钮",
    "产品预期：拒绝重复申请或返回原状态；当前实现会再次置为 refund_requested，属已知限制",
    "幂等缺口，列入生产改造", "工具与调用", "权限与安全",
    "request_refund / 幂等键缺失", "中", "异常", "手工", "")
add("订单与退款", "customer/张三", "非法商品 id 下单被拒",
    "张三已登录", "POST /api/orders {items:[{product_id:NOT_EXIST,quantity:1}]}",
    "构造不存在的商品 id 提交",
    "返回 400，detail 含商品不存在；库存与订单均不变",
    "输入校验", "工具与调用", "Agent 与多智能体",
    "create_order / ValueError", "中", "异常", "手工", "")
add("订单与退款", "customer/张三", "工具层绕过 API 仍做鉴权",
    "ContextVar 当前用户为李四", "以李四身份直接调用 get_order('O1001')",
    "绕过 HTTP 层直接执行工具函数",
    "返回 permission_denied；审计 decision=deny；不抛未捕获异常",
    "纵深防御", "权限与安全", "工具与调用 / MCP 协议",
    "get_current_user / _deny", "高", "安全", "已自动化",
    "test_tool_enforces_customer_scope")
add("订单与退款", "guest/访客", "访客访问订单接口被拒",
    "无 token", "GET /api/orders",
    "匿名调用订单列表",
    "返回 403，detail 提示缺少 order:read",
    "默认拒绝", "权限与安全", "LangGraph 状态图",
    "require('order:read')", "高", "安全", "已自动化", "test_guest_cannot_read_orders")

# 4. 工作流与审批
add("工作流与审批", "admin/管理员", "大额订单触发人工审批",
    "管理员已登录，O1001 金额 1098", "POST /api/workflows/fulfillment/run {order_id:O1001}",
    "在工作流页运行 O1001",
    "status=awaiting_approval；interrupt.amount=1098.0；步骤含校验、库存复核、锁定库存",
    "阈值判断与挂起", "人工审批与检查点", "LangGraph 状态图",
    "interrupt / APPROVAL_THRESHOLD=500", "高", "功能", "已自动化",
    "test_large_order_interrupts_then_completes")
add("工作流与审批", "admin/管理员", "批准后完成履约",
    "O1001 工作流处于 awaiting_approval", "POST /api/workflows/fulfillment/resume {thread_id:..., approved:true}",
    "在工作流页点击批准",
    "status=completed；订单 O1001 状态 shipped；步骤含人工审批通过、已生成发货单、履约完成",
    "恢复后副作用写回", "人工审批与检查点", "LangGraph 状态图",
    "Command(resume=True) / set_order_status", "高", "功能", "已自动化",
    "test_workflow_api_with_approval")
add("工作流与审批", "admin/管理员", "拒绝后订单取消",
    "工作流已挂起", "resume_fulfillment(thread_id, False)",
    "点击拒绝分支",
    "status=cancelled；订单状态 cancelled；步骤含人工审批拒绝、订单已取消",
    "拒绝分支闭环", "人工审批与检查点", "LangGraph 状态图",
    "Command(resume=False) / cancel 节点", "高", "功能", "已自动化", "test_rejected_order_is_cancelled")
add("工作流与审批", "admin/管理员", "小额订单跳过审批",
    "新建 129 元订单", "run_fulfillment(order.id, U001, wf-small)",
    "运行新订单工作流",
    "status=completed；步骤无等待审批；订单状态 shipped",
    "阈值以下自动流转", "人工审批与检查点", "LangGraph 状态图",
    "risk_review 条件分支", "中", "功能", "已自动化", "test_small_order_skips_approval")
add("工作流与审批", "admin/管理员", "不存在订单结束流程",
    "无", "run_fulfillment('O9999', U001, wf-missing)",
    "输入不存在的订单号运行",
    "status=not_found；message=订单不存在；流程直接结束",
    "异常路径不挂起", "人工审批与检查点", "LangGraph 状态图",
    "validate 条件边 / END", "中", "异常", "已自动化", "test_missing_order_ends_with_not_found")
add("工作流与审批", "customer/张三", "客户无权运行履约工作流",
    "张三已登录（customer）", "POST /api/workflows/fulfillment/run {order_id:O1001}",
    "客户手工调用工作流接口",
    "返回 403，提示缺少 order:manage",
    "工作流接口受权限保护", "权限与安全", "人工审批与检查点",
    "require('order:manage')", "高", "安全", "手工", "")
add("工作流与审批", "admin/管理员", "工作流 SVG 图正确渲染",
    "工作流页已加载", "GET /api/graphs 后查看页面图形",
    "打开工作流可视化页",
    "返回 supervisor 与 fulfillment 两张图；SVG 中节点标签齐全，边含审批/拒绝标签",
    "图元数据驱动前端", "前端与可视化", "LangGraph 状态图 / 人工审批与检查点",
    "describe_graphs / GraphFlow", "中", "可视化", "已自动化",
    "frontend/tests/graph.spec.ts")
add("工作流与审批", "admin/管理员", "步骤时间线展示中断详情",
    "已运行 O1001", "查看工作流运行结果面板",
    "运行后观察步骤时间线",
    "展示 steps 列表与 interrupt 对象（kind=approval、amount、reason）",
    "人工审批可解释", "前端与可视化", "人工审批与检查点",
    "_serialize / __interrupt__", "中", "可视化", "手工", "")
add("工作流与审批", "admin/管理员", "检查点可查询挂起状态",
    "thread 已挂起", "get_fulfillment_graph().get_state({configurable:{thread_id:...}})",
    "读取图状态",
    "state.interrupts 非空；state.next=('risk_review',)",
    "中断状态可恢复", "人工审批与检查点", "LangGraph 状态图",
    "InMemorySaver / get_state", "高", "集成", "已自动化",
    "test_interrupt_then_resume")

# 5. 权限与安全
add("权限与安全", "customer/张三", "账号密码登录成功",
    "种子用户存在", "POST /api/auth/login {username:张三, password:123456}",
    "在管理页选择张三登录",
    "返回 token、role=customer、permissions 含 order:create 不含 order:manage",
    "登录与权限下发", "权限与安全", "工具与调用",
    "issue_token / permissions_for", "高", "安全", "已自动化", "test_login_success_and_failure")
add("权限与安全", "guest/访客", "错误密码登录失败",
    "无", "POST /api/auth/login {username:张三, password:wrong}",
    "输入错误密码提交",
    "返回 401；审计写入 action=auth.login、decision=deny",
    "失败也可审计", "权限与安全", "可观测性",
    "authenticate / AuditLogger", "高", "安全", "已自动化", "test_login_success_and_failure")
add("权限与安全", "guest/访客", "访客可浏览商品不可下单",
    "无 token", "GET /api/products 与 POST /api/orders",
    "匿名访问两个接口",
    "商品接口 200；下单接口 403，提示缺少 order:create",
    "最小权限", "权限与安全", "工具与调用",
    "ROLE_PERMISSIONS.guest", "高", "安全", "已自动化", "test_role_permission_matrix")
add("权限与安全", "customer/李四", "伪造他人订单号提问被工具拒绝",
    "李四已登录", "对话输入：查 O1001 订单",
    "李四在聊天框输入张三订单号",
    "工具返回 permission_denied；答案明确告知无权访问；审计写入 deny",
    "对话层不绕过数据隔离", "权限与安全", "Agent 与多智能体 / 可观测性",
    "filter_tools / can_access_customer / _deny", "高", "安全", "手工", "")
add("权限与安全", "admin/管理员", "管理员角色权限矩阵完整",
    "管理页已登录", "查看权限矩阵表",
    "切换管理员账号后打开管理页",
    "role=admin；permissions 含全部 9 项，包括 audit:read、trace:read、user:manage",
    "角色可视化正确", "权限与安全", "前端与可视化",
    "ALL_PERMISSIONS / permissions_for", "中", "功能", "已自动化", "test_role_permission_matrix")
add("权限与安全", "service/王客服", "客服可读 Trace 与审计",
    "王客服已登录", "GET /api/traces 与 GET /api/audit",
    "在管理页打开 Trace 与审计表格",
    "两个接口均 200，返回 ts/trace_id/node/event 与 actor/decision 字段",
    "治理数据对客服开放", "权限与安全", "可观测性",
    "has_permission(trace:read/audit:read)", "中", "安全", "已自动化", "test_api.py")
add("权限与安全", "customer/张三", "客户不可读 Trace",
    "张三已登录", "GET /api/traces",
    "客户手工调用治理接口",
    "返回 403，提示需要 trace:read",
    "治理数据不外泄", "权限与安全", "可观测性",
    "require('trace:read')", "高", "安全", "手工", "")
add("权限与安全", "guest/访客", "Token 篡改检测",
    "已有合法 token", "decode_token(token + 篡改后缀, secret)",
    "修改 token 签名后访问订单接口",
    "解码返回 None；接口按 guest 处理并拒绝订单访问",
    "令牌完整性校验", "权限与安全", "可观测性",
    "hmac.compare_digest / decode_token", "高", "安全", "已自动化",
    "test_token_issue_and_tamper_detection")
add("权限与安全", "guest/访客", "过期 Token 失效",
    "构造 ttl=-1 的 token", "decode_token(expired_token, secret)",
    "携带过期令牌访问接口",
    "返回 None；订单接口 403",
    "时效性校验", "权限与安全", "工具与调用",
    "decode_token exp 校验", "高", "安全", "已自动化", "test_token_signature_and_expiry")
add("权限与安全", "guest/访客", "无 Token 仍可对话的限制",
    "无 token", "POST /api/chat {message:你好}",
    "匿名调用聊天接口",
    "当前返回 200（guest 具备 chat:use）；生产应改为 401，已列入改造清单",
    "记录现状差异", "权限与安全", "Agent 与多智能体",
    "current_user / anonymous_user", "中", "安全", "手工", "")

# 6. 可观测与治理
add("可观测与治理", "admin/管理员", "Trace 记录节点与工具调用",
    "已发起一次导购对话", "run_agent('推荐耳机', CUSTOMER, t-trace) 后查询 tracer",
    "执行对话并在管理页查看 Trace",
    "事件含 node=context、node=route、agent:tool/search_products、finalize",
    "链路可回放", "可观测性", "中间件 / LangGraph 状态图",
    "TraceCollector / wrap_tool_call", "高", "功能", "已自动化",
    "test_tracer_records_tool_calls")
add("可观测与治理", "admin/管理员", "按 trace_id 过滤链路",
    "已有多条 trace", "GET /api/traces?trace_id=t-trace",
    "在管理页按 trace_id 过滤",
    "仅返回该 trace 的事件，字段含 ts、node、event、payload",
    "过滤条件生效", "可观测性", "前端与可视化",
    "TraceCollector.query", "中", "接口", "手工", "")
add("可观测与治理", "admin/管理员", "登录失败写入审计",
    "无", "POST /api/auth/login 错误密码后 GET /api/audit",
    "失败登录后查看审计表",
    "出现 decision=deny、action=auth.login 的记录",
    "安全事件留痕", "可观测性", "权限与安全",
    "AuditLogger.record", "高", "安全", "已自动化", "test_login_success_and_failure")
add("可观测与治理", "admin/管理员", "越权尝试写入审计",
    "李四已登录", "李四调用 get_order('O1001') 后查询审计",
    "制造越权后在管理页查看",
    "审计包含 actor=U002、resource=O1001、decision=deny",
    "拒绝事件可追责", "可观测性", "权限与安全",
    "_deny / AuditLogger", "高", "安全", "已自动化", "test_tool_enforces_customer_scope")
add("可观测与治理", "admin/管理员", "管理页角色切换验证",
    "打开管理页", "选择管理员并登录（密码 123456）",
    "依次切换四个演示账号",
    "顶栏角色与权限矩阵随账号变化；切换后接口使用新 token",
    "演示体验一致", "前端与可视化", "权限与安全",
    "login / Pinia store / TOKEN_KEY", "低", "功能", "手工", "")
add("可观测与治理", "admin/管理员", "图元数据接口可用",
    "无", "GET /api/graphs",
    "调用接口并核对键名",
    "返回 supervisor 与 fulfillment 两张图；节点数分别为 7 与 8",
    "可视化数据源稳定", "可观测性", "LangGraph 状态图 / 前端与可视化",
    "describe_graphs", "中", "接口", "已自动化", "test_context_preview_rag_and_graphs")
add("可观测与治理", "admin/管理员", "审计记录条数上限符合配置",
    "audit_max_entries=500", "连续写入超过 500 条审计后查询",
    "批量制造审计事件",
    "最多返回 500 条；旧记录被环形淘汰",
    "内存上限保护", "可观测性", "权限与安全",
    "deque(maxlen) / AuditLogger", "低", "稳定性", "手工", "")
add("可观测与治理", "admin/管理员", "工具输入输出在 Trace 中脱敏",
    "Trace payload 已配置脱敏", "查看含手机号的对话链路",
    "在管理页检查 Trace 明细",
    "产品预期：手机号与地址不出现在 payload；当前实现会记录工具入参与结果前 400 字符，属已知风险",
    "PII 泄漏风险，列入生产改造", "可观测性", "中间件",
    "wrap_tool_call / PIIMiddleware", "高", "安全", "手工", "")

# 7. 前端交互
add("前端交互", "customer/张三", "登录态持久化",
    "已登录张三", "刷新浏览器页面",
    "登录后刷新页面观察顶栏",
    "localStorage.ecom_token 存在；刷新后自动恢复用户与权限；生产应改 httpOnly Cookie",
    "会话恢复与风险记录", "前端与可视化", "权限与安全",
    "getToken / me()", "中", "功能", "手工", "")
add("前端交互", "customer/张三", "SSE 事件驱动 UI 更新",
    "对话页已打开", "输入推荐降噪耳机",
    "观察消息气泡、路由徽章、工具 chip、节点进度",
    "token 事件逐段追加到助手气泡；done 后徽章与 chip 保留；最终文本等于 done.data",
    "流式渲染一致", "前端与可视化", "流式输出",
    "chatStream / ChatEvent", "高", "功能", "已自动化", "frontend/tests/api.spec.ts")
add("前端交互", "customer/张三", "上下文侧栏展开收起",
    "对话已完成", "点击上下文工程侧栏开关",
    "展开与收起侧栏",
    "展开显示 sections、chars、included 与预算；收起后对话区宽度恢复",
    "面板交互正常", "前端与可视化", "上下文工程",
    "ContextSnapshot / collapsible panel", "低", "功能", "手工", "")
add("前端交互", "customer/张三", "商品页到对话页预填问题",
    "商品页已加载", "点击商品卡向助手咨询",
    "观察路由与输入框",
    "跳转 /chat?q=...；输入框预填商品相关问题",
    "query 参数透传", "前端与可视化", "Agent 与多智能体",
    "router query / ChatView", "中", "功能", "手工", "")
add("前端交互", "customer/张三", "未登录访问受保护页面",
    "本地无 token", "直接访问 /orders",
    "地址栏输入路由",
    "当前显示订单页但接口 403；建议前端增加 401/403 统一拦截跳登录",
    "前端守卫缺口", "前端与可视化", "权限与安全",
    "request() 错误处理", "中", "安全", "手工", "")
add("前端交互", "customer/张三", "切页中断流式请求",
    "对话正在流式输出", "在输出过程中切换到商品页",
    "观察网络请求是否取消",
    "产品预期：应取消 SSE 连接；当前 chatStream 无 AbortController，属已知缺口",
    "资源释放与体验", "前端与可视化", "流式输出",
    "AbortController 缺失", "中", "稳定性", "手工", "")
add("前端交互", "admin/管理员", "生产构建与类型检查",
    "npm install 完成", "npm run build",
    "执行构建命令",
    "vue-tsc --noEmit 通过；Vite 产出 dist/，无类型错误",
    "可交付部署", "前端与可视化", "流式输出 / LangGraph 状态图",
    "vue-tsc / Vite", "高", "构建", "已自动化", "npm run build")
add("前端交互", "customer/张三", "工作流图节点标签渲染",
    "图数据已加载", "mount(GraphFlow, {props:{graph}})",
    "挂载组件并检查 SVG",
    "所有节点 label 与边标签出现；节点按 kind 着色",
    "纯 SVG 无第三方图库", "前端与可视化", "LangGraph 状态图",
    "GraphFlow.vue / viewBox 布局", "中", "可视化", "已自动化",
    "frontend/tests/graph.spec.ts")

# 8. 异常与边界
add("异常与边界", "customer/张三", "空消息输入被拒绝",
    "张三已登录", "POST /api/chat {message:''}",
    "提交空内容",
    "返回 422，detail 提示 message 长度至少 1；不进入 Agent",
    "输入契约校验", "权限与安全", "消息与模型",
    "ChatRequest Field(min_length=1)", "中", "异常", "手工", "")
add("异常与边界", "customer/张三", "超长输入触发上下文压缩",
    "context_max_chars=3200", "输入超过 800 字的长文本",
    "提交超长消息并查看上下文快照",
    "total_chars 不超预算；历史长消息出现压缩标记；服务不崩溃",
    "上下文预算保护", "上下文工程", "中间件",
    "ContextEngine.compact / SummarizationMiddleware", "中", "稳定性", "已自动化",
    "test_long_turn_is_compressed_with_marker")
add("异常与边界", "guest/访客", "健康检查接口可用",
    "服务已启动", "GET /api/health",
    "访问健康检查",
    "返回 status=ok、llm_provider=offline、mcp_mode=local",
    "探针数据源", "权限与安全", "可观测性",
    "health endpoint", "低", "接口", "已自动化", "test_health_and_docs")
add("异常与边界", "guest/访客", "OpenAPI 文档可访问",
    "服务已启动", "GET /docs 与 /openapi.json",
    "打开接口文档",
    "返回 200；包含 /api/chat、/api/orders 等路由；生产环境应关闭或加鉴权",
    "文档暴露面记录", "权限与安全", "前端与可视化",
    "FastAPI docs", "低", "接口", "已自动化", "test_health_and_docs")
add("异常与边界", "admin/管理员", "服务重启恢复种子数据",
    "已产生新订单与退款", "重启 uvicorn 后查询商品与订单",
    "停止并重启服务",
    "P001 库存恢复 12；订单恢复 O1001-O1003；新增订单消失（演示限制）",
    "明确内存数据边界", "权限与安全", "MCP 协议",
    "InMemoryRepository / _seed", "中", "稳定性", "已自动化",
    "test_reset_repository_is_deterministic")
add("异常与边界", "customer/张三", "并发下单超卖风险",
    "P008 库存 100", "100 个并发 POST /api/orders 各买 1 件",
    "并发压测下单接口",
    "产品预期：最多成功 100 单；当前单进程锁可保证，多副本会超卖，列入生产改造",
    "并发一致性缺口", "权限与安全", "工具与调用",
    "RLock / 行锁缺失", "中", "稳定性", "手工", "")
add("异常与边界", "customer/张三", "模型调用上限防死循环",
    "run_limit=6", "触发重试或异常工具调用",
    "执行异常对话观察结束状态",
    "图正常结束；消息数量受限；无无限循环",
    "稳定性兜底", "中间件", "LangGraph 状态图",
    "ModelCallLimitMiddleware", "高", "稳定性", "已自动化",
    "test_model_call_limit_middleware")
add("异常与边界", "customer/张三", "工具瞬时失败自动重试",
    "工具首次抛异常", "ToolRetryMiddleware(max_retries=1) 下执行导购",
    "注入失败工具并执行对话",
    "工具执行 2 次；最终产出 ToolMessage 与答案",
    "瞬态故障自愈", "中间件", "工具与调用",
    "ToolRetryMiddleware", "中", "稳定性", "已自动化", "test_tool_retry_middleware")
add("异常与边界", "customer/张三", "MCP 远程模式身份透传",
    "ECOM_MCP_MODE=http 且 MCP Server 已启动", "配置 Bearer token 后加载远程工具",
    "切换 mcp_mode=http 并调用工具",
    "产品预期：工具按终端用户权限执行；当前服务端未解析 Token，会降级 guest，属生产阻塞项",
    "远程模式权限缺口", "MCP 协议", "权限与安全",
    "MultiServerMCPClient / headers", "高", "安全", "手工", "")

# ---------------------------------------------------------------------------
# Sheet 1: 用例总览
# ---------------------------------------------------------------------------
ws_sum = wb.active
ws_sum.title = "用例总览"
ws_sum.merge_cells("A1:H1")
ws_sum["A1"] = "电商智能体｜产品级测试用例总览"
ws_sum["A1"].font = Font(name=FONT, size=16, bold=True, color=XL_WHITE)
ws_sum["A1"].fill = PatternFill("solid", fgColor=XL_DARK)
ws_sum["A1"].alignment = Alignment(horizontal="center", vertical="center")
ws_sum.row_dimensions[1].height = 30
ws_sum.merge_cells("A2:H2")
ws_sum["A2"] = "从用户场景出发：输入为用户话术或操作，预期输出为产品可观察结果；每条均标注涉及的 LangChain 知识点。"
ws_sum["A2"].font = Font(name=FONT, size=10, color=XL_TEXT)

# KPI anchors: labels A4:A10, values B4:B10
kpis = [
    ("总用例数", "=COUNTA('产品测试用例'!$A$4:$A$200)"),
    ("高优先级", '=COUNTIF(\'产品测试用例\'!$N$4:$N$200,"高")'),
    ("已自动化", '=COUNTIF(\'产品测试用例\'!$P$4:$P$200,"已自动化")'),
    ("手工用例", '=COUNTIF(\'产品测试用例\'!$P$4:$P$200,"手工")'),
    ("覆盖产品模块", "=COUNTA($A$13:$A$30)"),
    ("覆盖知识点", "=COUNTA('知识点映射'!$A$4:$A$30)"),
    ("自动化率", '=IF(OR(B4="",B4=0),"",B6/B4)'),
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
ws_sum["B10"].number_format = "0.0%"

# Module table anchors: header row 12, data 13..(12+M)
for col, name in enumerate(["产品模块", "用例数", "已自动化", "高优先级", "自动化率", "覆盖状态"], start=1):
    cell = ws_sum.cell(row=12, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = BORDER

modules: list[str] = []
for row in cases:
    if row[0] not in modules:
        modules.append(row[0])

for idx, module in enumerate(modules, start=13):
    ws_sum.cell(row=idx, column=1, value=module)
    ws_sum.cell(row=idx, column=2, value=f"=COUNTIF('产品测试用例'!$B$4:$B$200,A{idx})")
    ws_sum.cell(row=idx, column=3,
                value=f'=COUNTIFS(\'产品测试用例\'!$B$4:$B$200,A{idx},\'产品测试用例\'!$P$4:$P$200,"已自动化")')
    ws_sum.cell(row=idx, column=4,
                value=f'=COUNTIFS(\'产品测试用例\'!$B$4:$B$200,A{idx},\'产品测试用例\'!$N$4:$N$200,"高")')
    ws_sum.cell(row=idx, column=5, value=f'=IF(OR(B{idx}="",B{idx}=0),"",C{idx}/B{idx})')
    ws_sum.cell(row=idx, column=6, value=f'=IF(B{idx}=0,"未覆盖",IF(C{idx}=0,"仅手工","已覆盖"))')
    ws_sum.cell(row=idx, column=5).number_format = "0.0%"
    for col in range(1, 7):
        c = ws_sum.cell(row=idx, column=col)
        c.border = BORDER
        c.font = Font(name=FONT, color=XL_TEXT)
        c.alignment = Alignment(horizontal="center" if col > 1 else "left", vertical="center")

sum_last = 12 + len(modules)
for status, bg, fg in (("已覆盖", XL_GREEN_BG, XL_GREEN_TXT), ("未覆盖", XL_RED_BG, XL_RED_TXT),
                       ("仅手工", XL_YELLOW_BG, XL_YELLOW_TXT)):
    ws_sum.conditional_formatting.add(
        f"F13:F{sum_last}",
        FormulaRule(formula=[f'F13="{status}"'], fill=PatternFill("solid", fgColor=bg),
                    font=Font(color=fg)),
    )

chart = BarChart()
chart.type = "bar"
chart.style = 10
chart.title = "各产品模块用例数"
chart.y_axis.title = "产品模块"
chart.x_axis.title = "用例数"
chart.height = 10
chart.width = 18
chart.add_data(Reference(ws_sum, min_col=2, min_row=12, max_row=sum_last), titles_from_data=True)
chart.set_categories(Reference(ws_sum, min_col=1, min_row=13, max_row=sum_last))
chart.series[0].graphicalProperties.solidFill = "4472C4"
ws_sum.add_chart(chart, "H4")

for col, width in {"A": 22, "B": 12, "C": 12, "D": 12, "E": 12, "F": 14, "G": 3, "H": 3}.items():
    ws_sum.column_dimensions[col].width = width
ws_sum.sheet_view.showGridLines = False

# ---------------------------------------------------------------------------
# Sheet 2: 产品测试用例
# ---------------------------------------------------------------------------
ws_detail = wb.create_sheet("产品测试用例")
headers = ["用例编号", "产品模块", "用户角色", "用例标题", "前置条件", "输入（用户话术/操作）",
           "执行步骤", "预期输出", "实际输出（填写）", "验证要点", "主知识点", "关联知识点",
           "关键 API / 机制", "优先级", "用例类型", "自动化状态", "对应自动化用例"]
title_row, header_row, data_start = 1, 3, 4
ws_detail.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
ws_detail.cell(row=1, column=1, value="产品级测试用例明细（场景输入 → 预期输出 → 知识点映射）")
ws_detail.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_detail.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_detail.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_detail.row_dimensions[1].height = 28
ws_detail.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
ws_detail.cell(row=2, column=1,
               value="「实际输出（填写）」列留空；标注为已知限制/生产阻塞项的用例用于记录现状与改造优先级。")
ws_detail.cell(row=2, column=1).font = Font(name=FONT, size=10, color=XL_TEXT)

for col, name in enumerate(headers, start=1):
    cell = ws_detail.cell(row=header_row, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell.border = BORDER
ws_detail.row_dimensions[header_row].height = 32

for r, row in enumerate(cases, start=data_start):
    cid = f"P-TC-{r - data_start + 1:03d}"
    values = [cid, row[0], row[1], row[2], row[3], row[4], row[5], row[6], "",
              row[7], row[8], row[9], row[10], row[11], row[12], row[13], row[14]]
    for col, value in enumerate(values, start=1):
        cell = ws_detail.cell(row=r, column=col, value=value)
        cell.font = Font(name=FONT, size=10, color=XL_TEXT)
        cell.border = BORDER
        cell.alignment = Alignment(vertical="top", wrap_text=True,
                                   horizontal="center" if col in (1, 3, 14, 15, 16) else "left")
        if col == 9:
            cell.fill = PatternFill("solid", fgColor=XL_INPUT_BG)
    ws_detail.row_dimensions[r].height = 64

detail_last = data_start + len(cases) - 1
ws_detail.auto_filter.ref = f"A{header_row}:Q{detail_last}"
ws_detail.freeze_panes = "D4"
ws_detail.sheet_view.showGridLines = False

widths = {"A": 12, "B": 15, "C": 14, "D": 26, "E": 24, "F": 42, "G": 28, "H": 54,
          "I": 22, "J": 24, "K": 18, "L": 30, "M": 36, "N": 9, "O": 10, "P": 12, "Q": 40}
for col, width in widths.items():
    ws_detail.column_dimensions[col].width = width

for col_letter, options in (("N", "高,中,低"),
                            ("O", "功能,安全,异常,接口,集成,稳定性,可视化,构建"),
                            ("P", "已自动化,手工")):
    dv = DataValidation(type="list", formula1=f'"{options}"', allow_blank=False)
    dv.error = "请从下拉列表中选择"
    dv.errorTitle = "无效输入"
    ws_detail.add_data_validation(dv)
    dv.add(f"{col_letter}{data_start}:{col_letter}{detail_last}")

ws_detail.conditional_formatting.add(
    f"N{data_start}:N{detail_last}",
    CellIsRule(operator="equal", formula=['"高"'], fill=PatternFill("solid", fgColor=XL_RED_BG),
               font=Font(color=XL_RED_TXT)),
)
ws_detail.conditional_formatting.add(
    f"P{data_start}:P{detail_last}",
    CellIsRule(operator="equal", formula=['"手工"'], fill=PatternFill("solid", fgColor=XL_YELLOW_BG),
               font=Font(color=XL_YELLOW_TXT)),
)

# ---------------------------------------------------------------------------
# Sheet 3: 知识点映射
# ---------------------------------------------------------------------------
ws_map = wb.create_sheet("知识点映射")
map_headers = ["知识点", "核心 API / 机制", "用例数", "已自动化", "手工", "自动化率", "覆盖状态", "对应产品模块"]
ws_map.merge_cells("A1:H1")
ws_map.cell(row=1, column=1, value="LangChain 知识点 → 产品场景映射")
ws_map.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_map.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_map.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_map.row_dimensions[1].height = 28
ws_map.merge_cells("A2:H2")
ws_map.cell(row=2, column=1,
            value="统计按「主知识点」计数，关联知识点见明细 L 列；LCEL 为底层组合能力，已在源码级用例覆盖，未形成独立产品场景。")
ws_map.cell(row=2, column=1).font = Font(name=FONT, size=10, color=XL_TEXT)
for col, name in enumerate(map_headers, start=1):
    cell = ws_map.cell(row=3, column=col, value=name)
    cell.font = Font(name=FONT, bold=True, color=XL_WHITE)
    cell.fill = PatternFill("solid", fgColor=XL_PRIMARY)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = BORDER

api_map = {
    "消息与模型": "BaseChatModel / AIMessage / ToolMessage",
    "LCEL": "Runnable / Prompt | Model | Parser",
    "工具与调用": "StructuredTool / ainvoke / @tool",
    "Agent 与多智能体": "create_agent / supervisor / specialist",
    "中间件": "PII / Retry / CallLimit / wrap_tool_call",
    "LangGraph 状态图": "StateGraph / conditional_edges / astream",
    "人工审批与检查点": "interrupt / Command(resume) / InMemorySaver",
    "MCP 协议": "FastMCP / MultiServerMCPClient / stdio",
    "RAG 检索增强": "Embeddings / InMemoryVectorStore / retrieve",
    "上下文工程": "ContextEngine / ContextSnapshot / compact",
    "可观测性": "TraceCollector / AuditLogger / ContextVar",
    "流式输出": "astream(updates) / SSE / token",
    "权限与安全": "RBAC / HMAC Token / filter_tools",
    "前端与可视化": "chatStream / GraphFlow / Vitest",
}

kp_order: list[str] = []
for row in cases:
    if row[8] not in kp_order:
        kp_order.append(row[8])
for kp in ["消息与模型"]:
    if kp not in kp_order:
        kp_order.append(kp)

for idx, kp in enumerate(kp_order, start=4):
    ws_map.cell(row=idx, column=1, value=kp)
    ws_map.cell(row=idx, column=2, value=api_map.get(kp, ""))
    ws_map.cell(row=idx, column=3, value=f"=COUNTIF('产品测试用例'!$K$4:$K$200,A{idx})")
    ws_map.cell(row=idx, column=4,
                value=f'=COUNTIFS(\'产品测试用例\'!$K$4:$K$200,A{idx},\'产品测试用例\'!$P$4:$P$200,"已自动化")')
    ws_map.cell(row=idx, column=5,
                value=f'=COUNTIFS(\'产品测试用例\'!$K$4:$K$200,A{idx},\'产品测试用例\'!$P$4:$P$200,"手工")')
    ws_map.cell(row=idx, column=6, value=f'=IF(OR(C{idx}="",C{idx}=0),"",D{idx}/C{idx})')
    ws_map.cell(row=idx, column=7, value=f'=IF(C{idx}=0,"未覆盖",IF(D{idx}=0,"仅手工","已覆盖"))')
    mods = []
    for row in cases:
        if row[8] == kp and row[0] not in mods:
            mods.append(row[0])
    ws_map.cell(row=idx, column=8, value="、".join(mods) if mods else "—")
    ws_map.cell(row=idx, column=6).number_format = "0.0%"
    for col in range(1, 9):
        c = ws_map.cell(row=idx, column=col)
        c.border = BORDER
        c.font = Font(name=FONT, color=XL_TEXT)
        c.alignment = Alignment(horizontal="center" if col in (3, 4, 5, 6, 7) else "left",
                                vertical="center", wrap_text=(col in (2, 8)))

map_last = 3 + len(kp_order)
for status, bg, fg in (("已覆盖", XL_GREEN_BG, XL_GREEN_TXT), ("未覆盖", XL_RED_BG, XL_RED_TXT),
                       ("仅手工", XL_YELLOW_BG, XL_YELLOW_TXT)):
    ws_map.conditional_formatting.add(
        f"G4:G{map_last}",
        FormulaRule(formula=[f'G4="{status}"'], fill=PatternFill("solid", fgColor=bg),
                    font=Font(color=fg)),
    )
for col, width in {"A": 20, "B": 42, "C": 10, "D": 12, "E": 10, "F": 12, "G": 14, "H": 42}.items():
    ws_map.column_dimensions[col].width = width
ws_map.freeze_panes = "A4"
ws_map.auto_filter.ref = f"A3:H{map_last}"
ws_map.sheet_view.showGridLines = False

# ---------------------------------------------------------------------------
# Sheet 4: 角色与测试数据
# ---------------------------------------------------------------------------
ws_data = wb.create_sheet("角色与测试数据")
ws_data.cell(row=1, column=1, value="产品测试用账号、种子商品与订单（输入数据来源）")
ws_data.cell(row=1, column=1).font = Font(name=FONT, size=15, bold=True, color=XL_WHITE)
ws_data.merge_cells("A1:E1")
ws_data.cell(row=1, column=1).fill = PatternFill("solid", fgColor=XL_DARK)
ws_data.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
ws_data.row_dimensions[1].height = 28

sections = [
    ("演示账号（密码统一 123456）", ["用户名", "用户ID", "角色", "关键权限", "用于"], [
        ["张三", "U001", "customer", "order:read/create/refund", "主流程：导购、下单、退款"],
        ["李四", "U002", "customer", "order:read/create/refund", "越权拦截"],
        ["王客服", "S001", "service", "order:manage / audit:read / trace:read", "跨客户查询、治理页"],
        ["管理员", "A001", "admin", "ALL", "工作流审批、管理页"],
        ["访客", "anonymous", "guest", "product:read / chat:use", "商品浏览与政策问答"],
    ]),
    ("种子商品", ["ID", "名称", "价格", "初始库存", "用途"], [
        ["P001", "无线降噪耳机 Pro", 899.0, 12, "导购、库存查询、大额订单"],
        ["P007", "空气循环扇", 299.0, 0, "缺货与库存不足场景"],
        ["P008", "保温杯 500ml", 129.0, 100, "下单与小额订单场景"],
    ]),
    ("种子订单", ["ID", "客户", "金额", "初始状态", "用途"], [
        ["O1001", "U001", 1098.0, "shipped", "大额审批、订单查询"],
        ["O1002", "U002", 1299.0, "created", "李四订单、张三越权目标"],
        ["O1003", "U001", 918.0, "delivered", "退款申请演示"],
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
            if header[col - 1] in ("价格", "金额"):
                c.number_format = '¥#,##0.00'
        row += 1
    row += 1

for col, width in {"A": 18, "B": 24, "C": 22, "D": 36, "E": 30}.items():
    ws_data.column_dimensions[col].width = width
ws_data.sheet_view.showGridLines = False

out_path = Path(r"C:/Users/a1572/WorkBuddy/2026-11-22-16-26-05/docs/产品级测试用例.xlsx")
wb.save(out_path)
print(f"saved {out_path} with {len(cases)} cases, {len(modules)} modules, "
      f"{len(kp_order)} knowledge points, sheets={wb.sheetnames}")
