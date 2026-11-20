import com.aspose.words.DocumentBuilder;
import com.aspose.words.StyleIdentifier;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.WaitUntilState;

import java.awt.*;
import java.nio.file.Paths;
import java.text.SimpleDateFormat;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;

/**
 * people.com 新闻抓取：Playwright 驱动【本地 Chrome】+ 持久化 profile 过 Cloudflare，
 * 页面内 JS 直接抽正文，不用 Jsoup。JDK 17。
 * <p>
 * 三种接法（优先级从高到低）：
 * 1) --cdp=http://127.0.0.1:9222          连接已经打开的本地 Chrome（复用人工过盾的 cookie，最稳）
 * 2) --chrome-path=/path/to/chrome        显式指定本地 Chrome 可执行文件
 * 3) 默认 channel=chrome                   自动定位系统安装的 Chrome stable
 * 4) --channel=chromium                   回退到 Playwright 自带 Chromium
 * <p>
 * 白屏（Just a moment... 且页面空白）专用参数：
 * --proxy=http://127.0.0.1:7890   给 Chrome 挂代理，国内通常需要
 * --manual=true                   质询时停住程序，人工把页面弄过去再回车
 * <p>
 * 运行：
 * mvn -q compile exec:java -Dexec.mainClass=PeopleNewsCrawler -Dexec.args="--limit=8 --wait=90"
 */
public class PeopleNewsCrawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 正文段落格式：每段开头一个制表符、结尾一个换行；整篇正文自然也以 \t 开头、\n 收尾
     */
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";

    /**
     * 种子页：首页 + 主要频道。想抓人民网就整体换成 people.com.cn 的对应入口
     */
    private static final List<String> SEEDS = List.of(
//            "https://people.com/",
//            "https://people.com/news/",
//            "https://people.com/entertainment/",
//            "https://people.com/royals/",
            "https://people.com/human-interest/"
    );
    private static final Map<String, String> linksMap = Map.of(
            "crime", "https://people.com/crime/",
            "entertainment", "https://people.com/entertainment/",
            "lifestyle", "https://people.com/lifestyle/",
            "royals", "https://people.com/royals/",
            "health", "https://people.com/health/",
            "shopping", "https://people.com/shopping/",
            "human-interoest", "https://people.com/human-interest/"
    );
    /**
     * 最小 stealth：抹掉最显眼的自动化标记。UA 不覆盖，保持与真实 Chrome 一致更不容易被指纹识别
     */
    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    /**
     * 在列表页收集文章链接，纯浏览器侧过滤，返回 JSON 字符串数组
     */
    private static final String COLLECT_JS = """
            () => {
              const out = new Set();
              const bad = ['/tag/', '/author/', '/topic/', '/search', '/page/', '/about',
                           '/newsletter', '/privacy', '/terms', '/careers', '/advertise',
                           '/contact', '/rss', '/sitemap', '/apps', '/video', '/photos'];
              const add = (href) => {
                try {
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  if (!u.hostname.endsWith('people.com')) return;
                  let p = u.pathname;
                  while (p.endsWith('/')) p = p.slice(0, -1);
                  if (p.length < 12) return;
                  if (bad.some(b => p.toLowerCase().startsWith(b))) return;
                  if (/\\.(jpg|jpeg|png|webp|gif|mp4|pdf)$/i.test(p)) return;
                  u.hash = ''; u.search = '';
                  out.add(u.href);
                } catch (e) {}
              };
              document.querySelectorAll('a[href]').forEach(a => add(a.getAttribute('href')));
              return JSON.stringify([...out]);
            }
            """;

    /**
     * 文章页抽取：h1 / 时间 / 正文段落 / JSON-LD，返回 JSON 字符串
     */
    private static final String EXTRACT_JS = """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              const title  = clean(document.querySelector('h1')?.innerText) || clean(document.title);
              const time   = document.querySelector('time[datetime]')?.getAttribute('datetime')
                          || document.querySelector('meta[property="article:published_time"]')?.getAttribute('content')
                          || '';
              const author = clean(document.querySelector('[rel="author"], .byline, [data-testid="byline"]')?.innerText);
            
              // people.com（Mntl 模板）正文就是这一串 <p class="... mntl-sc-block-html">，
              // 父容器为 .article-content / .structured-content。广告位是 div.mntl-sc-block-adslot，
              // 不是 p，但 closest 再兜一层，避免把广告/相关阅读/订阅块里的 p 混进正文。
              const AD_SEL = '[class*="adslot"], [class*="-ad-"], [data-sc-ad], ' +
                             'aside, footer, [class*="newsletter"], [class*="related"], [class*="recirc"]';
              const NOISE = /^(Advertisement|Credit:|Subscribe|Sign Up|Read More|More From|Sponsored)/i;
            
              const pick = (sel, minLen) => [...document.querySelectorAll(sel)]
                    .filter(p => !p.closest(AD_SEL))
                    .map(p => clean(p.innerText))
                    .filter(t => t.length > minLen && !NOISE.test(t));
            
              // 只取 p 标签：先按真实正文 class 命中，命中不足再退回全页 p
              let body = pick('p.mntl-sc-block-html, .article-content p, ' +
                              '.structured-content p, article p', 25);
              if (body.length < 2) {
                body = pick('p', 40);
              }
            
              const seen = new Set();
              body = body.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; });
            
              const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => s.textContent.trim())
                    .filter(s => s.length > 0);
            
              return JSON.stringify({
                title: title, url: location.href, time: time, author: author,
                paragraphs: body, lds: lds
              });
            }
            """;

    public static void main(String[] args) throws Exception {
        Config cfg = Config.parse(args);
        AsposeUtil.setWordsLicense();
        try (Playwright pw = Playwright.create()) {
            if (!cfg.cdpUrl.isBlank()) {
                attachToRunningChrome(pw, cfg);
            } else {
                launchLocalChrome(pw, cfg);
            }
        }
    }

    /**
     * 模式 A：Playwright 自己拉起一个【本地 Chrome】进程，使用独立 profile，不干扰你正在用的 Chrome
     */
    private static void launchLocalChrome(Playwright pw, Config cfg) throws Exception {
        List<String> args = new ArrayList<>(List.of(
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check"));
        if (!cfg.proxy.isBlank()) {
            args.add("--proxy-server=" + cfg.proxy);   // Chrome 原生参数，比 Playwright setProxy 更稳
            System.out.println("[驱动] Chrome 挂代理：" + cfg.proxy);
        }

        BrowserType.LaunchPersistentContextOptions opt =
                new BrowserType.LaunchPersistentContextOptions()
                        .setHeadless(cfg.headless)
                        .setArgs(args)
                        .setLocale("en-US")
                        .setTimezoneId("Asia/Shanghai")   // 别用 America/New_York，与国内 IP 不一致容易被 CF 判异常
                        .setViewportSize(1366, 900);

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
            throw new IllegalStateException(
                    "启动本地 Chrome 失败。请依次检查：" +
                            "1) 是否已安装 Chrome stable；" +
                            "2) --profile 指向的目录是否被另一个 Chrome 进程占用（换一个目录即可）；" +
                            "3) 用 --chrome-path=/绝对路径/chrome 显式指定可执行文件；" +
                            "4) 或 --channel=chromium 回退到自带浏览器。" +
                            " 原始信息：" + e.getMessage(), e);
        }

        try {
            Page page = ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0);
            crawl(page, cfg);
        } finally {
            ctx.close();   // 只关我们拉起的实例；cf_clearance 留在 profile 里，下次复用
        }
    }

    /**
     * 模式 B：通过 CDP 连接【你手动启动、已经开着】的本地 Chrome，复用人工过盾拿到的 cf_clearance
     */
    private static void attachToRunningChrome(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 复用该 Chrome 的 cf_clearance；若新标签仍进质询，"
                + "请先在那个窗口里手动打开一次 https://people.com/ 并过盾。");
        Browser browser;
        try {
            browser = pw.chromium().connectOverCDP(cfg.cdpUrl);
        } catch (PlaywrightException e) {
            throw new IllegalStateException(
                    "CDP 连接失败。请确认 Chrome 已带 --remote-debugging-port 启动，且端口可访问：" +
                            cfg.cdpUrl + "。原始信息：" + e.getMessage(), e);
        }
        if (browser.contexts().isEmpty()) {
            throw new IllegalStateException("CDP 已连接但没有可用的 browser context，请检查 Chrome 启动参数。");
        }

        BrowserContext ctx = browser.contexts().get(0);
        Page page = ctx.newPage();   // 只开新标签，绝不复用/改动用户已经打开的页面
        try {
            crawl(page, cfg);
        } finally {
            page.close();            // 只关自己开的新标签
            // 刻意不调用 browser.close()：避免把用户的 Chrome 一起关掉；
            // Playwright 实例关闭时会自动断开 CDP 连接。
        }
    }

    /**
     * 公共抓取流程：与具体用哪种 Chrome 接法无关
     */
    private static void crawl(Page page, Config cfg) throws Exception {
        // CDP 连的是用户手动启动的原生 Chrome，本来就干净；再注入 stealth 反而多一处指纹痕迹
        if (cfg.cdpUrl.isBlank()) {
            page.addInitScript(STEALTH_JS);
        }
        page.setDefaultTimeout(30_000);

        // 抓 Cloudflare 质询资源加载失败：白屏十有八九是它
        List<String> netErrors = new ArrayList<>();
        page.onRequestFailed(req -> {
            String u = req.url();
            if (u.contains("challenges.cloudflare.com") || u.contains("cdn-cgi/challenge-platform")) {
                netErrors.add(String.valueOf(req.failure()) + " -> " + u);
            }
        });

        // 1) 收集候选链接
        Map<String, Set<String>> linksM = new HashMap<>();
        for (Map.Entry<String, String> entry : linksMap.entrySet()) {
            Set<String> links = new LinkedHashSet<>();
            try {
                open(page, entry.getValue(), cfg, netErrors);
                String json = (String) page.evaluate(COLLECT_JS);
                links.addAll(MAPPER.readValue(json, new TypeReference<List<String>>() {
                }));
                System.out.printf("种子页 %s -> 累计候选 %d 条%n", entry.getValue(), links.size());
            } catch (Exception e) {
                System.out.println("种子页失败 " + entry.getValue() + " : " + e.getMessage());
            }
            linksM.put(entry.getKey(), links);
            politeSleep();
        }
        // 2) 逐条抓正文
        for (Map.Entry<String, Set<String>> entry : linksM.entrySet()) {
            List<Map<String, Object>> news = new ArrayList<>();
            List<String> list = entry.getValue().stream()
                    .filter(e -> e.length() >= 8 && e.substring(e.length() - 8).matches("\\d{8}"))
                    .toList();
            int index = 0;
            for (String url : list) {
            if (index > cfg.limit) {
                break;
            }
                try {
                    open(page, url, cfg, netErrors);
                    String raw = (String) page.evaluate(EXTRACT_JS);
                    Map<String, Object> d =
                            MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {
                            });

                    @SuppressWarnings("unchecked")
                    List<String> paras = (List<String>) d.get("paragraphs");
                    @SuppressWarnings("unchecked")
                    List<String> lds = (List<String>) d.get("lds");
                    Map<String, String> ld = readArticleLd(lds);

                    // 判定是否为文章：有 Article 结构化数据，或至少有 2 段有效正文
                    boolean isArticle = !ld.isEmpty() || (paras != null && paras.size() >= 2);
                    if (!isArticle) {
                        System.out.println("跳过（非文章）: " + url);
                        continue;
                    }

                    // 迭代 p 标签数组：每段开头 \t、结尾 \n。
                    // 于是整篇正文以 \t 开头、\n 收尾，段与段之间不留空行。
                    StringBuilder content = new StringBuilder();
                    if (paras != null) {
                        for (String p : paras) {
                            content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);
                        }
                    }

                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("title", firstNonBlank(ld.get("headline"), (String) d.get("title")));
                    item.put("url", d.get("url"));
                    item.put("publishedAt", firstNonBlank(ld.get("datePublished"), (String) d.get("time")));
                    item.put("author", d.get("author"));
                    item.put("description", ld.getOrDefault("description", ""));
                    item.put("paragraphs", paras == null ? List.of() : paras);   // 原始 p 数组，便于核对
                    item.put("content", content.toString());
                    news.add(item);
                    ++index;
                    System.out.printf("[%d/%d] %s%n", news.size(), cfg.limit, item.get("title"));
                } catch (Exception e) {
                    System.out.println("抓取失败 " + url + " -> " + e.getMessage());
                }
                politeSleep();
            }
            int indexP = 0;
            List<List<Map<String, Object>>> lists = CommonStaticUtils.splitList(news, 10);
            for (List<Map<String, Object>> list1 : lists) {
                ++indexP;
                CommonStaticUtils.write("people-com", list1, indexP);
            }
        }

    }


    public static void write(String part, List<Map<String, Object>> news) throws Exception {
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
            String value = item.get("content").toString();
            builder.append("<").append(index).append(">,").append(key);
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(StyleIdentifier.HEADING_2);
            documentBuilderbuilder.getFont().setColor(Color.RED);
            documentBuilderbuilder.writeln(builder.toString());
            documentBuilderbuilder.getParagraphFormat().setStyleIdentifier(0);
            documentBuilderbuilder.getFont().setColor(Color.BLACK);
            documentBuilderbuilder.writeln(value);
        }
        DateTimeFormatter fmt = DateTimeFormatter.ofPattern("yyyyMMdd");
        String date = LocalDate.now().format(fmt);
        String target = "d:\\reading\\peoplecom-" + part + "-" + date + ".docx";
        doc.save(target);
    }


    /**
     * 导航 + 过 Cloudflare + 等内容节点
     */
    private static void open(Page page, String url, Config cfg, List<String> netErrors) {
        page.navigate(url, new Page.NavigateOptions()
                .setWaitUntil(WaitUntilState.DOMCONTENTLOADED)
                .setTimeout(6000_000));
        passCloudflare(page, cfg.waitSeconds, netErrors, cfg.manual);
        try {
            page.waitForSelector("article, main, h1",
                    new Page.WaitForSelectorOptions().setTimeout(15_000));
        } catch (PlaywrightException ignored) {
            // 少数页面结构特殊，后面 evaluate 仍会尝试兜底抽 <p>
        }
    }

    /**
     * Cloudflare 处理：
     * - JS 质询（Just a moment / cf-challenge-running）真实 Chrome 会自动跳转，轮询等待
     * - 白屏：body 空且质询组件没渲染，打印质询资源失败明细 + 自动 reload 2 次
     * - Turnstile 复选框：自动尝试点一次
     * - --manual=true：停住程序，人工在 Chrome 窗口把页面弄过去再回车
     */
    private static void passCloudflare(Page page, int maxSeconds,
                                       List<String> netErrors, boolean manual) {
        int blankTicks = 0, reloads = 0;
        boolean hinted = false;

        for (int i = 0; i < maxSeconds; i++) {
            String html = "";
            try {
                html = page.content();
            } catch (PlaywrightException ignored) {
            }

            // 质询判定改成「标题 + 可见文本」级，别用任意字符串包含：
            // 过盾后的正常页面里仍可能残留 /cdn-cgi/challenge-platform/ 脚本标签，
            // 只靠 html.contains 会把好页面误判成质询页，白白卡满 wait 秒数。
            String pageTitle = "";
            int textLen = 0;
            try {
                pageTitle = page.title();
                textLen = ((Number) page.evaluate(
                        "() => (document.body ? document.body.innerText : '').trim().length"))
                        .intValue();
            } catch (PlaywrightException ignored) {
            }

            boolean challenged = html.contains("cf-challenge-running")
                    || html.contains("Checking your browser")
                    || pageTitle.contains("Just a moment")
                    || pageTitle.contains("Attention Required")
                    || page.url().contains("cdn-cgi/challenge")
                    || (textLen < 200 && html.contains("challenge-platform"));

            boolean hasContent = page.locator("article, main, h1").count() > 0;
            // 已经渲染出实质内容就直接放行 —— CDP 复用 cf_clearance 时必走这条
            if (hasContent && textLen > 200) return;
            if (!challenged && hasContent) return;

            if (challenged) {
                // 1) 尝试自动点 Turnstile（跨源 iframe 由 frameLocator 处理）
                try {
                    Locator cb = page.frameLocator("iframe[src*='challenges.cloudflare.com']")
                            .locator("input[type='checkbox'], .cb-c, #challenge-stage input");
                    if (cb.count() > 0) {
                        cb.first().click(new Locator.ClickOptions().setTimeout(1500));
                    }
                } catch (PlaywrightException ignored) {
                }

                // 2) 白屏判定：复用上面的 body 可见文本长度
                boolean blank = textLen < 20;

                // 3) 一次性诊断：区分「质询资源连不上」和「指纹被拦」
                if (!hinted && i >= 3) {
                    hinted = true;
                    System.out.println("[诊断] 命中 Cloudflare 质询，当前"
                            + (blank ? "白屏（质询组件根本没渲染）" : "已渲染质询组件") + "。");
                    if (!netErrors.isEmpty()) {
                        System.out.println("[诊断] 以下质询资源加载失败 —— 基本可判定为网络/代理问题，再等也不会过：");
                        netErrors.stream().distinct().limit(4).forEach(e -> System.out.println("    " + e));
                        System.out.println("    在 Chrome 里直接访问 https://challenges.cloudflare.com/ 验证连通性，"
                                + "或给程序加 --proxy=http://127.0.0.1:7890。");
                    } else {
                        System.out.println("[诊断] 质询资源加载了却不放行，多半是自动化指纹被识别；"
                                + "建议删掉 .pw-profile 后改用 --cdp 复用人工过盾的 cookie。");
                    }
                }

                // 4) 人工兜底：窗口留着，控制台回车继续
                if (manual && i == 5) {
                    System.out.println("[人工] 请在 Chrome 窗口里手动刷新 / 完成验证（或配好代理），"
                            + "看到 people.com 正文后回到控制台按【回车】继续…");
                    try {
                        System.in.read();
                    } catch (java.io.IOException ignored) {
                    }
                    return;
                }

                // 5) 持续白屏：自动 reload 最多 2 次（CF jsd 偶发首刷失败）
                if (blank && ++blankTicks >= 8 && reloads < 2) {
                    reloads++;
                    blankTicks = 0;
                    System.out.println("[!] 质询页持续白屏，第 " + reloads + " 次自动刷新…");
                    try {
                        page.reload(new Page.ReloadOptions()
                                .setWaitUntil(WaitUntilState.DOMCONTENTLOADED)
                                .setTimeout(30_000));
                    } catch (PlaywrightException ignored) {
                    }
                }
            }
            page.waitForTimeout(1000);
        }
        throw new IllegalStateException(
                "Cloudflare 验证未通过（" + maxSeconds + "s）。按优先级试：\n"
                        + "  1) 手动开 Chrome 访问 https://people.com/ 看是否也白屏 —— 是则网络层问题，需代理；\n"
                        + "  2) 删除 .pw-profile 目录清掉坏 cookie；\n"
                        + "  3) 用 --cdp=http://127.0.0.1:9222 连接人工过盾的 Chrome，复用 cf_clearance；\n"
                        + "  4) 加 --manual=true 让程序停住，人工把页面弄过去再回车。");
    }

    /**
     * 从若干 JSON-LD 片段里找 @type 含 Article 的节点，取标题/时间/摘要
     */
    private static Map<String, String> readArticleLd(List<String> lds) {
        if (lds == null) return Map.of();
        for (String s : lds) {
            try {
                Deque<JsonNode> q = new ArrayDeque<>();
                q.add(MAPPER.readTree(s));
                while (!q.isEmpty()) {
                    JsonNode cur = q.poll();
                    if (cur == null || cur.isNull()) continue;
                    if (cur.isArray()) {
                        cur.forEach(q::add);
                        continue;
                    }
                    if (!cur.isObject()) continue;

                    JsonNode t = cur.get("@type");
                    String type = t == null ? "" : (t.isArray() ? t.toString() : t.asText(""));
                    if (type.contains("Article")) {
                        Map<String, String> m = new HashMap<>();
                        m.put("type", type);
                        m.put("headline", cur.path("headline").asText(""));
                        m.put("datePublished", cur.path("datePublished").asText(""));
                        m.put("description", cur.path("description").asText(""));
                        return m;
                    }
                    if (cur.has("@graph")) {
                        JsonNode g = cur.get("@graph");
                        if (g.isArray()) g.forEach(q::add);
                        else q.add(g);
                    }
                    cur.fields().forEachRemaining(e -> {
                        JsonNode v = e.getValue();
                        if (v.isObject() || v.isArray()) q.add(v);
                    });
                }
            } catch (Exception ignored) {
                // 站点 LD+JSON 偶有残缺，跳过该片段
            }
        }
        return Map.of();
    }

    private static String firstNonBlank(String... xs) {
        for (String x : xs) if (x != null && !x.isBlank()) return x;
        return "";
    }

    /**
     * 礼貌抓取：单线程 + 随机间隔，别把站点打疼
     */
    private static void politeSleep() {
        try {
            Thread.sleep(ThreadLocalRandom.current().nextInt(1500, 3500));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static class Config {
        boolean headless = false;          // 默认有头，过盾率明显更高（CDP 模式下由外部 Chrome 决定，此参数无效）
        int limit = 20;
        int waitSeconds = 45;
        String profileDir = "./.pw-profile";
        String channel = "chrome";        // chrome=本地 Chrome stable；chromium=Playwright 自带
        String chromePath = "";           // 显式指定本地 Chrome 可执行文件
        String cdpUrl = "";               // 连接已运行的 Chrome，如 http://127.0.0.1:9222
        String proxy = "";                // 给 Chrome 挂代理，如 http://127.0.0.1:7890
        boolean manual = false;           // 质询时停住，人工过盾后回车继续

        static Config parse(String[] a) {
            Config c = new Config();
            for (String s : a) {
                if (s.startsWith("--headless=")) c.headless = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--limit=")) c.limit = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--wait=")) c.waitSeconds = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--profile=")) c.profileDir = s.split("=", 2)[1];
                else if (s.startsWith("--channel=")) c.channel = s.split("=", 2)[1];
                else if (s.startsWith("--chrome-path=")) c.chromePath = s.split("=", 2)[1];
                else if (s.startsWith("--cdp=")) c.cdpUrl = s.split("=", 2)[1];
                else if (s.startsWith("--proxy=")) c.proxy = s.split("=", 2)[1];
                else if (s.startsWith("--manual=")) c.manual = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.equals("--help")) {
                    System.out.println("""
                            参数（JDK 17 / Playwright 驱动本地 Chrome）：
                              --headless=false|true        默认 false，有头模式过盾率更高
                              --limit=8                    最多抓取文章数
                              --wait=45                    每页等待 Cloudflare 通过的最长秒数
                              --profile=./.pw-profile      独立持久化 profile，存放 cf_clearance
                              --channel=chrome|chromium    默认 chrome（本机 Chrome stable）；chromium 为回退
                              --chrome-path=/path/chrome   显式指定本地 Chrome 可执行文件（最高优先级）
                              --cdp=http://127.0.0.1:9222 连接已手动启动的本地 Chrome（优先于以上全部）
                              --proxy=http://127.0.0.1:7890 给 Chrome 挂代理，国内过 CF 常用
                              --manual=true                质询时停住，人工在 Chrome 里过盾后回车继续
                              --help                       打印本说明
                            """);
                    System.exit(0);
                }
            }
            return c;
        }
    }
}
