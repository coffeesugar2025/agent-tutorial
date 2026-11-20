import com.aspose.words.DocumentBuilder;
import com.aspose.words.StyleIdentifier;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.WaitUntilState;

import java.awt.*;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 前程无忧（51job）岗位抓取：关键字 agent / 地区全国。
 * 技术栈与 PeopleNewsCrawler 一致：JDK 17 + Playwright 驱动【本地 Chrome】+ Jackson，无 Jsoup。
 * <p>
 * 取数双通道：
 * 主：监听 XHR 响应 api/job/search-pc，直接拿 resultbody.job.items（字段最全，含 jobDescribe，
 * 连详情页都不用进，规避 51job 详情页的低可达率和指纹审计）
 * 备：DOM 兜底 .joblist-item + sensorsdata 属性（接口结构改版时不至于全空）
 * <p>
 * 反爬提示：51job 校验浏览器环境指纹，headless 基本必挂。
 * 最稳走 CDP：手动开一个 Chrome 访问一次 https://we.51job.com/pc/search?keyword=agent，
 * 再 --cdp=http://127.0.0.1:9222 连上去；独立 profile 拉起的方式次之。
 * <p>
 * 运行（IntelliJ 把 Main class 改成 Job51Crawler）：
 * --keyword=agent --area=000000 --pages=5 --limit=60
 * --cdp=http://127.0.0.1:9222
 */
public class Job51Crawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 正文/JD 段落格式：与 PeopleNewsCrawler 一致，每段开头 \t、结尾 \n
     */
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";

    /**
     * 列表接口特征串，命中任意一个且能解析出岗位数组就采纳
     */
    private static final List<String> API_HINTS = List.of(
            "api/job/search-pc", "search-pc", "searchproduct", "joblist.json", "/api/job/search");

    /**
     * DOM 兜底：抓 .joblist-item 卡片，排除公司主页链接 /all/co
     */
    private static final String DOM_FALLBACK_JS = """
            () => {
              const t = s => (s || '').replace(/\\s+/g, ' ').trim();
              return JSON.stringify([...document.querySelectorAll('.joblist-item')].map(card => {
                let sd = {};
                try {
                  sd = JSON.parse(card.querySelector('[sensorsdata]')
                        ?.getAttribute('sensorsdata') || '{}');
                } catch (e) {}
            
                // 详情链接：必须落在 jobs.51job.com，且排除 /all/co 公司页
                const href = [...card.querySelectorAll('a[href]')]
                      .map(a => a.href)
                      .find(h => h.includes('jobs.51job.com') && !h.includes('/all/co')) || '';
            
                return {
                  jobName: t(card.querySelector('.jname')?.innerText) || sd.jobTitle || '',
                  provideSalaryString: t(card.querySelector('.sal')?.innerText) || sd.jobSalary || '',
                  companyName: t(card.querySelector('.cname')?.innerText) || '',
                  jobAreaString: sd.jobArea || t(card.querySelector('.shrink-0')?.innerText) || '',
                  jobTags: [...card.querySelectorAll('.tag')]
                        .map(e => t(e.innerText)).filter(Boolean),
                  issueDateString: t(card.querySelector('.time')?.innerText) || '',
                  jobDescribe: '',
                  jobHref: href,
                  _sensorsdata: sd
                };
              }).filter(x => x.jobName));
            }
            """;

    /**
     * 列表页状态检测：是否出现登录墙/安全验证/空结果
     */
    private static final String PAGE_STATE_JS = """
            () => {
              const txt = (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim();
              return JSON.stringify({
                ready: document.readyState === 'complete',
                cards: document.querySelectorAll('.joblist-item').length,
                loginWall: /登录后查看|请先登录|安全验证|滑动验证|验证码/.test(txt),
                noResult: /没有找到|暂无相关|无匹配职位/.test(txt),
                head: txt.slice(0, 120)
              });
            }
            """;

    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    public static void main(String[] args) throws Exception {
        AsposeUtil.setWordsLicense();
        Config cfg = Config.parse(args);
        try (Playwright pw = Playwright.create()) {
            if (!cfg.cdpUrl.isBlank()) attachToRunningChrome(pw, cfg);
            else launchLocalChrome(pw, cfg);
        }
    }

    /**
     * 模式 A：Playwright 拉起独立 profile 的本地 Chrome
     */
    private static void launchLocalChrome(Playwright pw, Config cfg) throws Exception {
        List<String> chromeArgs = new ArrayList<>(List.of(
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check"));
        if (!cfg.proxy.isBlank()) {
            chromeArgs.add("--proxy-server=" + cfg.proxy);
            System.out.println("[驱动] Chrome 挂代理：" + cfg.proxy);
        }

        BrowserType.LaunchPersistentContextOptions opt =
                new BrowserType.LaunchPersistentContextOptions()
                        .setHeadless(cfg.headless)
                        .setArgs(chromeArgs)
                        .setLocale("zh-CN")
                        .setTimezoneId("Asia/Shanghai")
                        .setViewportSize(1440, 900);

        if (!cfg.chromePath.isBlank()) {
            opt.setExecutablePath(Paths.get(cfg.chromePath).toAbsolutePath());
            System.out.println("[驱动] 本地 Chrome（显式路径）：" + cfg.chromePath);
        } else if ("chrome".equalsIgnoreCase(cfg.channel)) {
            opt.setChannel("chrome");
            System.out.println("[驱动] 本地 Chrome stable（channel=chrome，自动定位）");
        } else {
            System.out.println("[驱动] Playwright 自带 Chromium（channel=chromium）");
        }
        System.out.println("[驱动] 独立 profile：" + Paths.get(cfg.profileDir).toAbsolutePath());

        BrowserContext ctx;
        try {
            ctx = pw.chromium().launchPersistentContext(
                    Paths.get(cfg.profileDir).toAbsolutePath(), opt);
        } catch (PlaywrightException e) {
            throw new IllegalStateException("启动本地 Chrome 失败：" + e.getMessage()
                    + "。可换 --profile 目录、用 --chrome-path 指定路径，或 --cdp 连手动开的 Chrome。", e);
        }
        try {
            Page page = ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0);
            crawl(page, cfg);
        } finally {
            ctx.close();
        }
    }

    /**
     * 模式 B：CDP 连接手动启动的原生 Chrome（过指纹最稳）
     */
    private static void attachToRunningChrome(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 建议先在该 Chrome 里手动打开一次搜索页，确认能看到岗位列表。");
        Browser browser;
        try {
            browser = pw.chromium().connectOverCDP(cfg.cdpUrl);
        } catch (PlaywrightException e) {
            throw new IllegalStateException("CDP 连接失败：" + cfg.cdpUrl + " -> " + e.getMessage(), e);
        }
        if (browser.contexts().isEmpty()) {
            throw new IllegalStateException("CDP 已连接但没有可用的 browser context。");
        }
        BrowserContext ctx = browser.contexts().get(0);
        Page page = ctx.newPage();
        try {
            crawl(page, cfg);
        } finally {
            page.close();   // 只关自己开的标签，不动用户的浏览器
        }
    }

    /**
     * 公共抓取流程
     */
    private static void crawl(Page page, Config cfg) throws Exception {
        if (cfg.cdpUrl.isBlank()) page.addInitScript(STEALTH_JS);
        page.setDefaultTimeout(30_000);

        // 响应监听：主通道，直接吃接口 JSON
        List<Map<String, Object>> captured = Collections.synchronizedList(new ArrayList<>());
        page.onResponse(resp -> {
            try {
                if (resp.status() != 200) return;
                String u = resp.url();
                if (API_HINTS.stream().noneMatch(u::contains)) return;
                String body = resp.text();
                if (body == null || !body.trim().startsWith("{")) return;
                List<JsonNode> items = findJobItems(MAPPER.readTree(body));
                if (items.isEmpty()) return;
                for (JsonNode it : items) {
                    captured.add(MAPPER.convertValue(it, new TypeReference<Map<String, Object>>() {
                    }));
                }
                System.out.printf("[接口] 捕获 %d 条 <- %s%n", items.size(), shorten(u, 110));
            } catch (Exception ignored) {
                // 非目标响应 / 响应体尚未就绪，跳过
            }
        });

        String searchUrl = buildSearchUrl(cfg);
        System.out.println("[搜索] " + searchUrl);

        // 结果集，按 jobHref / 公司+岗位 去重
        Map<String, Map<String, Object>> jobs = new LinkedHashMap<>();
        int domFallbackUsed = 0;

        for (int p = 1; p <= cfg.pages && jobs.size() < cfg.limit; p++) {
            int before = captured.size();
            if (p == 1) {
                page.navigate(searchUrl, new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED)
                        .setTimeout(60_000));
                waitFirstScreen(page, cfg);
            } else if (!clickNextPage(page)) {
                System.out.println("[翻页] 没有下一页了，提前结束。");
                break;
            }

            // 等本页接口响应落地（最多 waitSeconds 秒）
            for (int s = 0; s < cfg.waitSeconds && captured.size() == before; s++) {
                page.waitForTimeout(1000);
            }

            List<Map<String, Object>> pageItems;
            synchronized (captured) {
                pageItems = new ArrayList<>(captured.subList(before, captured.size()));
            }

            // 接口没吐数据 → DOM 兜底
            if (pageItems.isEmpty()) {
                List<Map<String, Object>> dom = domFallback(page);
                if (!dom.isEmpty()) {
                    pageItems = dom;
                    domFallbackUsed++;
                    System.out.printf("[兜底] 第 %d 页由 DOM 取出 %d 条%n", p, dom.size());
                }
            }

            int added = 0;
            for (Map<String, Object> raw : pageItems) {
                if (jobs.size() >= cfg.limit) break;
                Map<String, Object> job = normalize(raw, cfg);
                if (job == null) continue;
                String key = (String) job.get("_key");
                if (jobs.putIfAbsent(key, job) == null) added++;
            }
            System.out.printf("[第 %d 页] 新增 %d 条，累计 %d 条%n", p, added, jobs.size());

            if (added == 0 && pageItems.isEmpty()) {
                System.out.println("[提示] 本页无数据。若页面弹了登录/安全验证，请在 Chrome 窗口手动处理后重跑；"
                        + "51job 对 headless 与指纹敏感，建议 --cdp 连手动开的 Chrome。");
                break;
            }
            politeSleep();
        }

        // 去掉内部去重键，落盘
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> j : jobs.values()) {
            Map<String, Object> m = new LinkedHashMap<>(j);
            m.remove("_key");
            out.add(m);
        }
        int indexP = 0;
        List<List<Map<String, Object>>> lists = CommonStaticUtils.splitList(out, 100);
        for (List<Map<String, Object>> list1 : lists) {
            ++indexP;
            write("51job", list1, indexP);
        }
        System.out.printf("完成：%s，共 %d 个岗位（DOM 兜底 %d 页，接口通道 %d 页）%n",
                cfg.outFile, out.size(), domFallbackUsed, cfg.pages - domFallbackUsed);
    }

    public static void write(String part, List<Map<String, Object>> news, int indexP) throws Exception {
        com.aspose.words.Document doc = new com.aspose.words.Document();
        DocumentBuilder documentBuilderbuilder = new DocumentBuilder(doc);
        int index = 0;
        for (Map<String, Object> item : news) {
            // 设置字体格式
            documentBuilderbuilder.getFont().setName("Calibri");
            documentBuilderbuilder.getFont().setSize(12);
            //documentBuilderbuilder.getFont().setBold(true);
            documentBuilderbuilder.getFont().setColor(Color.black);
            StringBuilder builder = new StringBuilder();
            ++index;
            String key = item.get("title").toString();
            String content = item.get("content").toString();
            String company = item.get("company").toString();
            String salary = item.get("salary").toString();
            String companySize = item.get("companySize").toString();
            String companyType = item.get("companyType").toString();
            String updateTime = item.get("updateTime").toString();
            builder.append("<").append(index).append(">,").append(key);
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(StyleIdentifier.HEADING_2);
            documentBuilderbuilder.getFont().setColor(Color.RED);
            documentBuilderbuilder.writeln(builder.toString());
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(0);
            documentBuilderbuilder.getFont().setColor(Color.BLACK);
            documentBuilderbuilder.writeln(companyType);
            documentBuilderbuilder.writeln(updateTime);
            documentBuilderbuilder.writeln(companySize);
            documentBuilderbuilder.writeln(salary);
            documentBuilderbuilder.writeln(company);
            documentBuilderbuilder.writeln(content);
        }
        DateTimeFormatter fmt = DateTimeFormatter.ofPattern("yyyyMMdd");
        String date = LocalDate.now().format(fmt);
        String target = "d:\\reading\\" + part + "-" + indexP + "-" + date + ".docx";
        doc.save(target);
    }


    /**
     * 构造搜索 URL：jobArea=000000 即全国，searchType=2 全文搜
     */
    private static String buildSearchUrl(Config cfg) {
        String kw = URLEncoder.encode(cfg.keyword, StandardCharsets.UTF_8);
        return "https://we.51job.com/pc/search"
                + "?jobArea=" + URLEncoder.encode(cfg.area, StandardCharsets.UTF_8)
                + "&keyword=" + kw
                + "&searchType=2&keywordType=&sortType=0&metro=";
    }

    /**
     * 首屏：SPA 有加载窗口期，readyState 未 complete 时查卡片会是 0 条
     */
    private static void waitFirstScreen(Page page, Config cfg) {
        try {
            page.waitForFunction("() => document.readyState === 'complete'");
        } catch (PlaywrightException ignored) {
        }
        try {
            page.waitForSelector(".joblist-item, .joblist",
                    new Page.WaitForSelectorOptions().setTimeout(20_000));
        } catch (PlaywrightException ignored) {
        }

        String state = (String) page.evaluate(PAGE_STATE_JS);
        System.out.println("[页面] " + state);
        if (cfg.manual && (state.contains("\"loginWall\":true")
                || state.contains("\"cards\":0"))) {
            System.out.println("[人工] 请在 Chrome 窗口里完成登录/验证，看到岗位列表后"
                    + "回控制台按【回车】继续…");
            try {
                System.in.read();
            } catch (java.io.IOException ignored) {
            }
        }
    }

    /**
     * 翻页：el-pagination 下一页，多选择器兜底
     */
    private static boolean clickNextPage(Page page) {
        String[] sels = {".el-icon-arrow-right", ".btn-next", ".el-pager .next",
                "li.next", "[class*='pagination'] [class*='next']"};
        for (String sel : sels) {
            try {
                Locator l = page.locator(sel).last();
                if (l.count() > 0 && l.isVisible() && l.isEnabled()) {
                    l.click(new Locator.ClickOptions().setTimeout(4000));
                    return true;
                }
            } catch (PlaywrightException ignored) {
            }
        }
        // 再兜底：文字按钮（Playwright 扩展伪类）
        try {
            Locator byText = page.locator("button:has-text('下一页'), a:has-text('下一页')");
            if (byText.count() > 0 && byText.first().isVisible()) {
                byText.first().click(new Locator.ClickOptions().setTimeout(4000));
                return true;
            }
        } catch (PlaywrightException ignored) {
        }
        return false;
    }

    /**
     * DOM 兜底抽取
     */
    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> domFallback(Page page) {
        try {
            String json = (String) page.evaluate(DOM_FALLBACK_JS);
            return MAPPER.readValue(json, new TypeReference<List<Map<String, Object>>>() {
            });
        } catch (Exception e) {
            return List.of();
        }
    }

    /**
     * 递归找接口里的岗位数组，兼容 resultbody.job.items 以及改版后的层级
     */
    private static List<JsonNode> findJobItems(JsonNode root) {
        List<JsonNode> out = new ArrayList<>();
        Deque<JsonNode> q = new ArrayDeque<>();
        q.add(root);
        while (!q.isEmpty()) {
            JsonNode n = q.poll();
            if (n == null || n.isNull()) continue;
            if (n.isArray()) {
                if (looksLikeJobs(n)) n.forEach(out::add);
                else n.forEach(q::add);
                continue;
            }
            if (!n.isObject()) continue;
            n.fields().forEachRemaining(e -> {
                JsonNode v = e.getValue();
                if (v.isArray() && looksLikeJobs(v)) v.forEach(out::add);
                else if (v.isObject() || v.isArray()) q.add(v);
            });
        }
        return out;
    }

    private static boolean looksLikeJobs(JsonNode arr) {
        if (arr == null || !arr.isArray() || arr.size() == 0) return false;
        JsonNode f = arr.get(0);
        return f != null && f.isObject()
                && (f.has("jobName") || f.has("jobTitle") || f.has("provideSalaryString"));
    }

    /**
     * 接口/DOM 两种原始结构统一成输出字段；JD 按段落迭代加 \t / \n
     */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> normalize(Map<String, Object> raw, Config cfg) {
        String title = str(raw, "jobName", "jobTitle", "title");
        if (title.isBlank()) return null;

        String jd = str(raw, "jobDescribe", "jobDescription", "description", "jobInfo");
        List<String> paras = splitParagraphs(jd);
        StringBuilder content = new StringBuilder();
        for (String p : paras) content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);

        List<String> tags = strList(raw.get("jobTags"));
        List<String> welfare = welfareList(raw.get("jobWelfareCodeDataList"));
        String href = str(raw, "jobHref", "jobUrl", "url", "href");
        String company = str(raw, "companyName", "company", "fullCompanyName");
        String city = str(raw, "jobAreaString", "jobArea", "city", "areaString");

        String key = !href.isBlank() ? href : title + "|" + company + "|" + city;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("_key", key);
        m.put("keyword", cfg.keyword);
        m.put("area", cfg.area.equals("000000") ? "全国" : cfg.area);
        m.put("title", title);
        m.put("company", company);
        m.put("salary", str(raw, "provideSalaryString", "jobSalary", "salary", "provideSalary"));
        m.put("city", city);
        m.put("experience", str(raw, "workYearString", "workYear", "experience"));
        m.put("degree", str(raw, "degreeString", "degree", "eduLevel"));
        m.put("term", str(raw, "termStr", "term", "jobTerm"));
        m.put("industry", str(raw, "companyIndustryType1Str", "companyIndustryType1", "industry"));
        m.put("companySize", str(raw, "companySizeString", "companySize"));
        m.put("companyType", str(raw, "companyTypeString", "companyType"));
        m.put("tags", tags);
        m.put("welfare", welfare);
        m.put("publishTime", str(raw, "issueDateString", "issueDate", "publishTime", "time"));
        m.put("updateTime", str(raw, "updateDateTime", "updateTime"));
        m.put("url", href);
        m.put("paragraphs", paras);       // JD 原始段落数组，便于核对
        m.put("content", content.toString()); // \t段1\n\t段2\n，与 people.com 版一致
        return m;
    }

    /**
     * JD 去 HTML 标签后按行拆段；没有换行就按中文句号/分号切，避免整坨一行
     */
    private static List<String> splitParagraphs(String jd) {
        if (jd == null || jd.isBlank()) return List.of();
        String s = jd.replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</p>", "\n")
                .replaceAll("<[^>]+>", "")
                .replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("\r", "");
        List<String> parts = new ArrayList<>();
        for (String line : s.split("\n")) {
            String t = line.replaceAll("\\s+", " ").trim();
            if (!t.isBlank()) parts.add(t);
        }
        if (parts.size() <= 1 && s.length() > 120) {
            parts.clear();
            for (String seg : s.split("(?<=[。；;！!])")) {
                String t = seg.replaceAll("\\s+", " ").trim();
                if (t.length() > 2) parts.add(t);
            }
        }
        return parts;
    }

    private static List<String> strList(Object o) {
        if (!(o instanceof List<?>)) return List.of();
        List<?> list = (List<?>) o;
        List<String> out = new ArrayList<>();
        for (Object x : list) {
            if (x == null) continue;
            if (x instanceof String) out.add(((String) x).trim());
            else if (x instanceof Map<?, ?>) {
                Map<?, ?> mm = (Map<?, ?>) x;
                Object v = mm.get("chineseTitle");
                if (v == null) v = mm.get("name");
                if (v == null) v = mm.get("value");
                if (v != null) out.add(String.valueOf(v).trim());
            } else out.add(String.valueOf(x).trim());
        }
        return out.stream().filter(s -> !s.isBlank()).distinct().toList();
    }

    private static List<String> welfareList(Object o) {
        if (!(o instanceof List<?>)) return List.of();
        List<?> list = (List<?>) o;
        List<String> out = new ArrayList<>();
        for (Object x : list) {
            if (x instanceof Map<?, ?>) {
                Map<?, ?> mm = (Map<?, ?>) x;
                Object v = mm.get("chineseTitle");
                if (v == null) v = mm.get("title");
                if (v == null) v = mm.get("name");
                if (v != null) out.add(String.valueOf(v).trim());
            } else if (x instanceof String) out.add(((String) x).trim());
        }
        return out.stream().filter(s -> !s.isBlank()).distinct().toList();
    }

    /**
     * 多候选字段名取第一个非空字符串
     */
    private static String str(Map<String, Object> m, String... keys) {
        for (String k : keys) {
            Object v = m.get(k);
            if (v == null) continue;
            String s = v instanceof String ? (String) v : String.valueOf(v);
            if (!s.isBlank() && !"null".equalsIgnoreCase(s)) return s.trim();
        }
        return "";
    }

    private static String shorten(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    /**
     * 礼貌抓取：单线程 + 随机间隔
     */
    private static void politeSleep() {
        try {
            Thread.sleep(ThreadLocalRandom.current().nextInt(1800, 4000));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static class Config {
        String keyword = "agent";
        String area = "000000";            // 000000 = 全国
        int pages = 50;                     // 最多翻几页，每页约 20 条
        int limit = 6000;                    // 最多岗位数
        int waitSeconds = 20;              // 每页等接口响应的最长秒数
        boolean headless = false;          // 51job 指纹校验严格，默认有头
        String profileDir = "./.pw-profile-51job";
        String channel = "chrome";
        String chromePath = "";
        String cdpUrl = "";
        String proxy = "";
        boolean manual = false;
        String outFile = "jobs-51job.json";

        static Config parse(String[] a) {
            Config c = new Config();
            for (String s : a) {
                if (s.startsWith("--keyword=")) c.keyword = s.split("=", 2)[1];
                else if (s.startsWith("--area=")) c.area = s.split("=", 2)[1];
                else if (s.startsWith("--pages=")) c.pages = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--limit=")) c.limit = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--wait=")) c.waitSeconds = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--headless=")) c.headless = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--profile=")) c.profileDir = s.split("=", 2)[1];
                else if (s.startsWith("--channel=")) c.channel = s.split("=", 2)[1];
                else if (s.startsWith("--chrome-path=")) c.chromePath = s.split("=", 2)[1];
                else if (s.startsWith("--cdp=")) c.cdpUrl = s.split("=", 2)[1];
                else if (s.startsWith("--proxy=")) c.proxy = s.split("=", 2)[1];
                else if (s.startsWith("--manual=")) c.manual = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--out=")) c.outFile = s.split("=", 2)[1];
                else if (s.equals("--help")) {
                    System.out.println("""
                            参数（JDK 17 / Playwright 驱动本地 Chrome / 51job）：
                              --keyword=agent              搜索关键字
                              --area=000000                地区，000000=全国；010000=北京等
                              --pages=5                    最多翻几页（每页约 20 条）
                              --limit=60                   最多岗位数
                              --wait=20                    每页等接口响应的最长秒数
                              --headless=false|true        默认 false，51job 指纹校验严格
                              --profile=./.pw-profile-51job 独立持久化 profile
                              --channel=chrome|chromium    默认本机 Chrome stable
                              --chrome-path=...            显式指定 Chrome 可执行文件
                              --cdp=http://127.0.0.1:9222 连接手动开的 Chrome（最稳，推荐）
                              --proxy=http://127.0.0.1:7890 可选代理
                              --manual=true                遇登录/验证码时停住，人工处理后回车
                              --out=jobs-51job.json        输出文件
                              --help                       打印本说明
                            """);
                    System.exit(0);
                }
            }
            return c;
        }
    }
}
