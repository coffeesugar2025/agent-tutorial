import com.aspose.words.DocumentBuilder;
import com.aspose.words.StyleIdentifier;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.WaitUntilState;

import java.awt.*;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.List;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * IELTS Liz（https://ieltsliz.com/）免费备考资料抓取。
 * 技术栈与前面几个主类一致：JDK 17 + Playwright 驱动【本地 Chrome】+ Jackson，无 Jsoup。
 *
 * 站点要点（WordPress）：
 *  - 300+ 页免费 lessons / tips / model answers / speaking 题目 / vocabulary，
 *    顶栏 RED BAR 分 Listening / Reading / Writing Task 1 / Task 2 / Speaking /
 *    Vocabulary / FAQ；核心内容免费，只有 Advanced 视频课与 e-book 收费。
 *  - URL 有两种形态，必须都收：
 *      https://ieltsliz.com/ielts-writing-task-2/                  固定链接
 *      https://ieltsliz.com/?post_type=post&p=5784                  plain permalink（搜索引擎里大量存在）
 *    所以【不能像新闻站那样无脑清掉所有 query】，只清 utm 系列、fbclid、ref、replytocom，
 *    p / page_id / post_type / cat 这些要保留并规范化排序。
 *  - 最稳入口是 WordPress sitemap（/wp-sitemap.xml、/sitemap_index.xml、/sitemap.xml），
 *    一次能拿到全站 <loc>；辅以 /feed/ 和栏目页 DOM。
 *  - 直连 HTTP 实测全站 403（WAF），必须 --cdp 连手动开的原生 Chrome。
 *
 * 输出除了通用正文，还针对备考多抽三类结构化字段：
 *   contentType  自动归类（model-answer / speaking-questions / writing-task-2 / vocabulary ...）
 *   questions    页面里疑似雅思题目的句子（Speaking Part 1/2/3、100 Essay Questions 等）
 *   vocabulary   标题含 Vocabulary / Useful Words / Linking Words 的列表词组
 * 正文格式与前几版一致：只取 p 标签，迭代数组，每段 \t + 文本 + \n。
 *
 * ⚠️ 范文版权归作者所有。本程序只做【本地个人学习索引】，不整篇转载、不转售、
 *    不抓付费 Advanced Lessons / e-book 内容。
 *
 * 运行（IntelliJ Main class 改成 IeltsLizCrawler）：
 *   --source=both --limit=30 --cdp=http://127.0.0.1:9222
 *   --only=model-answer,speaking-questions,vocabulary --limit=60
 */
public class IeltsLizCrawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";

    /** 种子页：只放确定存在、且能带出全站导航的两页，其余靠 sitemap + nav 跟进 */
    private static final List<String> SEEDS = List.of(
            "https://ieltsliz.com/",
            "https://ieltsliz.com/free-ielts-preparation-blog/"
    );

    /** WordPress sitemap 候选：默认按序尝试，命中即解析；index 会再展开一层 */
    private static final List<String> SITEMAP_URLS = List.of(
            "https://ieltsliz.com/wp-sitemap.xml",
            "https://ieltsliz.com/sitemap_index.xml",
            "https://ieltsliz.com/sitemap.xml"
    );

    private static final String RSS_URL = "https://ieltsliz.com/feed/";

    private static final Pattern LOC_TAG = Pattern.compile(
            "<loc>\\s*([^<\\s]+)\\s*</loc>", Pattern.CASE_INSENSITIVE);
    private static final Pattern LIZ_URL = Pattern.compile(
            "https?://(?:www\\.)?ieltsliz\\.com/[^\\s\"'<>]+", Pattern.CASE_INSENSITIVE);

    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    /**
     * 频道页收集内容链接。
     * 关键点：保留 WordPress plain permalink 的 p / page_id / post_type / cat 参数，
     * 只清掉追踪参数；其余同站路径按固定链接收。栏目/分页进 nav 供 Java 跟进。
     */
    private static final String COLLECT_JS = """
            () => {
              const out = new Set();
              const nav = new Set();
              const dropped = new Set();
              const badPath = ['/wp-admin/', '/wp-content/', '/wp-json/', '/wp-includes/',
                               '/feed/', '/comments/', '/trackback/', '/author/', '/tag/',
                               '/attachment/', '/search', '/?s=', '/shop/', '/checkout/',
                               '/cart/', '/my-account/', '/privacy-policy/', '/sitemap',
                               '/category/', '/page/'];
              // 只保留这几个 WordPress 内容参数，且按 key 排序，避免同页多份重复链接
              const KEEP_QS = ['p', 'page_id', 'post_type', 'cat', 'page'];

              const norm = (raw) => {
                try {
                  let href = (raw || '').trim().replace(/&amp;/g, '&');
                  if (!href || href.startsWith('#') || /^javascript:/i.test(href)
                          || /^mailto:/i.test(href)) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  const h = u.hostname.toLowerCase().replace(/^www\\./, '');
                  if (h !== 'ieltsliz.com') {
                    if (/ieltsliz/.test(h)) dropped.add('外域       ' + href.slice(0, 110));
                    return;
                  }
                  let p = u.pathname || '/';
                  if (p.toLowerCase().startsWith('/amp/')) p = p.substring(4);
                  const low = p.toLowerCase();
                  if (badPath.some(b => low.startsWith(b.toLowerCase()))) {
                    // 栏目分类页 / 分页仍然进 nav，让 Java 侧跟进
                    if (low.startsWith('/category/') || /\\/page\\/\\d+\\/?$/.test(low)) collectNav(u);
                    else dropped.add('非内容页   ' + ('https://ieltsliz.com' + p).slice(0, 110));
                    return;
                  }
                  if (/\\.(jpg|jpeg|png|webp|gif|svg|pdf|zip|mp3|mp4|docx?|xlsx?)$/i.test(p)) return;
                  if (/pardon|access-denied|403|error/i.test(p)) return;

                  // 保留内容参数、丢弃追踪参数
                  const qs = [];
                  u.searchParams.forEach((v, k) => {
                    if (KEEP_QS.includes(k) && !/^\\s*$/.test(v)) qs.push([k, v]);
                  });
                  qs.sort((a, b) => a[0].localeCompare(b[0]));
                  const search = qs.length ? '?' + qs.map(x => encodeURIComponent(x[0]) + '=' + encodeURIComponent(x[1])).join('&') : '';

                  // 纯首页（无路径无参数）不算内容页
                  if ((p === '/' || p === '') && !search) return;
                  const finalUrl = 'https://ieltsliz.com' + p + search;
                  out.add(finalUrl);
                } catch (e) {}
              };

              const collectNav = (u) => {
                try {
                  let p = u.pathname || '/';
                  const low = p.toLowerCase();
                  // 只跟进分类页与分页；普通文章链接由 sitemap / 首页覆盖，不进 nav
                  if (!(low.startsWith('/category/') || /\\/page\\/\\d+\\/?$/.test(low))) return;
                  if (low.startsWith('/feed/')) return;
                  const qs = [];
                  u.searchParams.forEach((v, k) => {
                    if (['p','page_id','post_type','cat','page'].includes(k)) qs.push([k, v]);
                  });
                  qs.sort((a, b) => a[0].localeCompare(b[0]));
                  const s = qs.length ? '?' + qs.map(x => x[0] + '=' + x[1]).join('&') : '';
                  nav.add('https://ieltsliz.com' + p + s);
                } catch (e) {}
              };

              document.querySelectorAll('a[href]').forEach(a => {
                const href = a.getAttribute('href');
                norm(href);
                try { collectNav(new URL(href, location.href)); } catch (e) {}
              });

              // 卡片 data-* + 内嵌 JSON / 源码里的绝对 URL
              const keys = ['data-href', 'data-url', 'data-link', 'data-permalink',
                            'data-post-url', 'data-target-url'];
              document.querySelectorAll(keys.map(k => '[' + k + ']').join(', '))
                      .forEach(el => keys.forEach(k => norm(el.getAttribute(k))));
              const sources = [];
              document.querySelectorAll('script[type="application/ld+json"], script#__NEXT_DATA__, ' +
                                        'script[type="application/json"], script[data-module]')
                      .forEach(s => sources.push(s.textContent || ''));
              sources.push(document.documentElement.outerHTML);
              const re = /https?:\\/\\/(?:www\\.)?ieltsliz\\.com\\/[^"'\\s<>]+/gi;
              for (const src of sources) {
                let m;
                while ((m = re.exec(src)) !== null) norm(m[0]);
              }
              return JSON.stringify({
                urls: [...out].slice(0, 400),
                nav: [...nav].slice(0, 60),
                dropped: [...dropped].slice(0, 30)
              });
            }
            """;

    /** 文章/资料页抽取：正文 p、题目句、词汇表、元信息、标题层级、JSON-LD */
    private static final String EXTRACT_JS = """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              const meta = (sel, attr) => clean(document.querySelector(sel)?.getAttribute(attr || 'content'));

              const title = clean(document.querySelector(
                        'h1.entry-title, h1.post-title, h1[class*="entry-title"], h1[itemprop="headline"], h1')?.innerText)
                    || meta('meta[property="og:title"]') || clean(document.title);
              const time = meta('meta[property="article:published_time"]')
                    || clean(document.querySelector('time[datetime]')?.getAttribute('datetime'))
                    || clean(document.querySelector('.entry-date, [class*="post-date"]')?.innerText) || '';
              const modified = meta('meta[property="article:modified_time"]') || '';
              const author = meta('meta[name="author"]')
                    || clean(document.querySelector('[rel="author"], .author, .byline')?.innerText);
              const category = [...document.querySelectorAll('[rel="category tag"], .cat-links a')]
                    .map(a => clean(a.innerText)).filter(Boolean).join(', ')
                    || meta('meta[property="article:section"]');
              const description = meta('meta[name="description"]') || meta('meta[property="og:description"]');
              const headings = [...document.querySelectorAll('h1, h2, h3, h4')]
                    .map(h => clean(h.innerText)).filter(Boolean).slice(0, 40);

              const NOISE_SEL = [
                    'aside', 'footer', 'nav', 'header', 'form',
                    '[class*="advert"]', '[class*="sponsored"]', '[class*="newsletter"]',
                    '[class*="related"]', '[class*="recirc"]', '[class*="promo"]',
                    '[class*="subscribe"]', '[class*="share"]', '[class*="sharedaddy"]',
                    '[class*="comment"]', '[class*="pagination"]', '[class*="navigation"]',
                    '[class*="widget"]', '[class*="menu"]', '[class*="cookie"]',
                    '[class*="banner"]', '[class*="entry-meta"]', '[class*="post-meta"]',
                    '[id*="comment"]', 'script', 'style', 'noscript'
                  ].join(', ');
              const NOISE_TEXT = /^(Share|Related|Posted in|Filed under|Leave a|Comments|Tags:|Subscribe|Sign up|Read more|More from|Previous|Next|Advertisement|Sponsored|Click here|All the best|Hi guys|Follow|Facebook|YouTube|Email:|Comment:)/i;

              const pick = (sel, minLen) => [...document.querySelectorAll(sel)]
                    .filter(p => !p.closest(NOISE_SEL))
                    .map(p => clean(p.innerText))
                    .filter(t => t.length > minLen && !NOISE_TEXT.test(t));

              // 按实际抽到的文本量选容器：WordPress 语义 wrapper 存在但正文是兄弟节点的情况很常见
              const candidates = [
                    '.entry-content p', '[class*="entry-content"] p',
                    '.post-content p', '[class*="post-content"] p',
                    '[itemprop="articleBody"] p', '[class*="article-content"] p',
                    'article .entry-content p', 'article p', 'main p', 'body p'
              ];
              let body = [];
              for (const sel of candidates) {
                const t = pick(sel, 20);
                const chars = t.reduce((n, x) => n + x.length, 0);
                if (t.length >= 2 && chars >= 200) { body = t; break; }
                if (t.length > body.length) body = t;
              }
              const seen = new Set();
              body = body.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; });

              // 题目句：Speaking Part 1/2/3 Questions、100 Essay Questions 等页面
              const Q_START = /^(do|does|did|are|is|was|were|have|has|had|can|could|would|should|will|what|why|how|where|when|who|which|tell me|describe|some people|to what extent|discuss|do you think|in your opinion)/i;
              const questions = [];
              const seenQ = new Set();
              [...document.querySelectorAll('.entry-content li, .entry-content p, article li, article p, main li, main p')]
                    .filter(el => !el.closest(NOISE_SEL))
                    .forEach(el => {
                      let t = clean(el.innerText);
                      if (t.length < 8 || t.length > 260) return;
                      // 正文里常有「Do you often have dreams? Yes, I do...」这种题目+范文，
                      // 只截到第一个问号，避免把整段回答当成一道题
                      if (t.includes('?')) t = t.slice(0, t.indexOf('?') + 1).trim();
                      if (t.length < 8 || t.length > 180) return;
                      if (!t.includes('?') && !Q_START.test(t)) return;
                      if (NOISE_TEXT.test(t)) return;
                      if (seenQ.has(t)) return;
                      seenQ.add(t); questions.push(t);
                    });

              // 词汇表：标题含 Vocabulary / Useful Words / Linking Words / Phrases 时，取其后第一个列表
              const vocabulary = [];
              const seenV = new Set();
              const V_HEAD = /(vocabulary|useful (words|expressions|phrases)|linking words|collocations|transition words|key words|common phrases)/i;
              [...document.querySelectorAll('h2, h3, h4, strong, p[class*="heading"]')].forEach(h => {
                if (!V_HEAD.test(clean(h.innerText))) return;
                let n = h.nextElementSibling;
                for (let i = 0; i < 4 && n; i++, n = n.nextElementSibling) {
                  const list = n.matches('ul, ol') ? n : n.querySelector('ul, ol');
                  if (!list) continue;
                  [...list.querySelectorAll('li')].forEach(li => {
                    const t = clean(li.innerText);
                    if (!t || t.length > 70 || t.includes('?') || t.includes('.')) return;
                    if (seenV.has(t.toLowerCase())) return;
                    seenV.add(t.toLowerCase()); vocabulary.push(t);
                  });
                  break;
                }
              });

              const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => s.textContent.trim()).filter(s => s.length > 0);

              return JSON.stringify({
                title: title, url: location.href, time: time, modified: modified,
                author: author, category: category, description: description,
                headings: headings, paragraphs: body,
                questions: questions.slice(0, 80), vocabulary: vocabulary.slice(0, 120),
                lds: lds
              });
            }
            """;

    private static final String PAGE_STATE_JS = """
            () => {
              const txt = (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim();
              return JSON.stringify({
                ready: document.readyState === 'complete',
                title: document.title.slice(0, 90),
                textLen: txt.length,
                blocked: /Access Denied|Forbidden|Just a moment|Checking your browser|Are you a robot|Pardon Our Interruption|Request unsuccessful|Incident ID|Reference #|403/i.test(txt),
                head: txt.slice(0, 160)
              });
            }
            """;

    public static void main(String[] args) throws Exception {
        Config cfg = Config.parse(args);
        try (Playwright pw = Playwright.create()) {
            if (!cfg.cdpUrl.isBlank()) attach(pw, cfg);
            else launch(pw, cfg);
        }
    }

    private static void launch(Playwright pw, Config cfg) throws Exception {
        List<String> chromeArgs = new ArrayList<>(List.of(
                "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
                "--no-first-run", "--no-default-browser-check"));
        if (!cfg.proxy.isBlank()) {
            chromeArgs.add("--proxy-server=" + cfg.proxy);
            System.out.println("[驱动] Chrome 挂代理：" + cfg.proxy);
        }
        BrowserType.LaunchPersistentContextOptions opt =
                new BrowserType.LaunchPersistentContextOptions()
                        .setHeadless(cfg.headless).setArgs(chromeArgs)
                        .setLocale("en-GB").setTimezoneId("Europe/London")
                        .setViewportSize(1440, 900);
        if (!cfg.chromePath.isBlank()) {
            opt.setExecutablePath(Paths.get(cfg.chromePath).toAbsolutePath());
            System.out.println("[驱动] 本地 Chrome（显式路径）：" + cfg.chromePath);
        } else if ("chrome".equalsIgnoreCase(cfg.channel)) {
            opt.setChannel("chrome");
            System.out.println("[驱动] 本地 Chrome stable（channel=chrome）");
        } else {
            System.out.println("[驱动] Playwright 自带 Chromium（channel=chromium）");
        }
        System.out.println("[驱动] 独立 profile：" + Paths.get(cfg.profileDir).toAbsolutePath());
        System.out.println("[提示] 本站直连 HTTP 全站 403，强烈建议 --cdp 连手动开的 Chrome。");

        BrowserContext ctx;
        try {
            ctx = pw.chromium().launchPersistentContext(
                    Paths.get(cfg.profileDir).toAbsolutePath(), opt);
        } catch (PlaywrightException e) {
            throw new IllegalStateException("启动本地 Chrome 失败：" + e.getMessage(), e);
        }
        try {
            crawl(ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0), cfg);
        } finally {
            ctx.close();
        }
    }

    private static void attach(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 建议先在该 Chrome 里手动打开一次 https://ieltsliz.com/ 确认可见。");
        Browser browser = pw.chromium().connectOverCDP(cfg.cdpUrl);
        if (browser.contexts().isEmpty()) {
            throw new IllegalStateException("CDP 已连接但没有可用的 browser context。");
        }
        Page page = browser.contexts().get(0).newPage();
        try {
            crawl(page, cfg);
        } finally {
            page.close();
        }
    }

    private static void crawl(Page page, Config cfg) throws Exception {
        if (cfg.cdpUrl.isBlank()) page.addInitScript(STEALTH_JS);
        page.setDefaultTimeout(30_000);

        if (cfg.warmup) {
            System.out.println("[预热] 先访问 IELTS Liz 首页…");
            try {
                page.navigate("https://ieltsliz.com/", new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(1500, 2800));
            } catch (PlaywrightException e) {
                System.out.println("[预热] 首页访问异常（继续）：" + e.getMessage());
            }
        }

        Set<String> links = new LinkedHashSet<>();
        Set<String> nav = new LinkedHashSet<>();
        List<String> dropped = new ArrayList<>();

        // 1) sitemap：一次拿全站 <loc>，比硬啃频道页稳一个数量级
        String src = cfg.source.toLowerCase(Locale.ROOT);
        if (src.equals("sitemap") || src.equals("both") || src.equals("all")) {
            links.addAll(collectFromSitemaps(page, cfg));
        }

        // 2) 频道页 DOM：边滚边收 + 栏目/分页跟进
        if (src.equals("channel") || src.equals("both") || src.equals("all")) {
            for (String seed : cfg.seeds) {
                try {
                    open(page, seed, cfg);
                    harvest(page, cfg, links, nav, dropped);
                    System.out.printf("[频道页] %s -> 累计 %d 条%n", seed, links.size());
                } catch (Exception e) {
                    System.out.println("[频道页] 失败 " + seed + " : " + e.getMessage());
                }
                politeSleep();
            }
            int followed = 0;
            for (String n : new ArrayList<>(nav)) {
                if (followed >= cfg.follow) break;
                if (cfg.seeds.contains(n)) continue;
                try {
                    open(page, n, cfg);
                    harvest(page, cfg, links, nav, dropped);
                    followed++;
                    System.out.printf("[栏目/分页 %d/%d] %s -> 累计 %d 条%n",
                            followed, cfg.follow, n, links.size());
                    politeSleep();
                } catch (Exception e) {
                    System.out.println("[栏目/分页] 跳过 " + n + " : " + e.getMessage());
                }
            }
        }

        // 3) RSS 补充
        if (src.equals("rss") || src.equals("all")) {
            links.addAll(collectFromRss(page, cfg));
        }

        if (!dropped.isEmpty()) {
            System.out.println("[诊断] 被丢弃的链接样本（前 8 条）：");
            dropped.stream().limit(8).forEach(d -> System.out.println("    " + d));
        }

        // 硬约束兜底：只留 ieltsliz.com 内容页
        int before = links.size();
        Set<String> filtered = new LinkedHashSet<>();
        for (String u : links) {
            if (cfg.requireLesson && !isContentUrl(u)) continue;
            filtered.add(u);
        }
        links = filtered;
        if (before != links.size()) {
            System.out.printf("[过滤] 排除 %d 条非内容链接，保留 %d 条%n",
                    before - links.size(), links.size());
        }
        System.out.println("[收集] 候选资料页 " + links.size() + " 条（--source=" + cfg.source
                + "，--limit=" + cfg.limit + "，--only=" + (cfg.only.isEmpty() ? "全部" : cfg.only) + "）");
        if (links.isEmpty()) {
            System.out.println("[提示] 0 条：优先看 [警告] 是否 403 / WAF 拦截；"
                    + "用 --cdp 连手动 Chrome，或 --source=channel 先只跑首页。");
        }

        // 4) 逐页抽取
        List<Map<String, Object>> items = new ArrayList<>();
        int skippedByType = 0;
        for (String url : links) {
            if (items.size() >= cfg.limit) break;
            if (cfg.requireLesson && !isContentUrl(url)) continue;
            try {
                open(page, url, cfg);
                String raw = (String) page.evaluate(EXTRACT_JS);
                Map<String, Object> d = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});

                @SuppressWarnings("unchecked") List<String> paras = (List<String>) d.get("paragraphs");
                @SuppressWarnings("unchecked") List<String> lds = (List<String>) d.get("lds");
                @SuppressWarnings("unchecked") List<String> headings = (List<String>) d.get("headings");
                @SuppressWarnings("unchecked") List<String> questions = (List<String>) d.get("questions");
                @SuppressWarnings("unchecked") List<String> vocabulary = (List<String>) d.get("vocabulary");
                Map<String, String> ld = readLd(lds);

                String title = firstNonBlank(ld.get("headline"), (String) d.get("title"));
                String type = classify(title, url, headings);
                if (!cfg.only.isEmpty() && !cfg.only.contains(type)) {
                    skippedByType++;
                    continue;
                }
                if (title.isBlank() || (paras == null || paras.isEmpty()) && questions.isEmpty() && vocabulary.isEmpty()) {
                    System.out.println("跳过（空页/被拦）: " + url);
                    continue;
                }

                StringBuilder content = new StringBuilder();
                if (paras != null) for (String p : paras) content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);

                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title", title);
                item.put("url", d.get("url"));
                item.put("contentType", type);
                item.put("publishedAt", firstNonBlank(ld.get("datePublished"), (String) d.get("time")));
                item.put("modifiedAt", firstNonBlank(ld.get("dateModified"), (String) d.get("modified")));
                item.put("author", firstNonBlank(ld.get("author"), (String) d.get("author")));
                item.put("category", firstNonBlank(ld.get("articleSection"), (String) d.get("category")));
                item.put("description", firstNonBlank(ld.get("description"), (String) d.get("description")));
                item.put("headings", headings == null ? List.of() : headings);
                item.put("questions", questions == null ? List.of() : questions);
                item.put("vocabulary", vocabulary == null ? List.of() : vocabulary);
                item.put("paragraphs", paras == null ? List.of() : paras);
                item.put("content", content.toString());
                item.put("source", "IELTS Liz");
                items.add(item);

                System.out.printf("[%d/%d][%s] %s%n", items.size(), cfg.limit, type, title);
            } catch (Exception e) {
                System.out.println("抓取失败 " + url + " -> " + e.getMessage());
            }
            politeSleep();
        }

        write("leltsliz",items);
        System.out.println("完成：" + cfg.outFile + "，共 " + items.size() + " 页"
                + (skippedByType > 0 ? "（按 --only 跳过 " + skippedByType + " 页）" : ""));
    }


    public static void write(String part, List<Map<String, Object>> news) throws Exception {
        AsposeUtil.setWordsLicense();
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
        String target = "d:\\reading\\leltsliz-" + part + "-" + date + ".docx";
        doc.save(target);
    }





    /** sitemap：先找可用的 index，再展开一层子 sitemap，收集所有 <loc> 里的内容 URL */
    private static List<String> collectFromSitemaps(Page page, Config cfg) {
        Set<String> out = new LinkedHashSet<>();
        Deque<String> queue = new ArrayDeque<>(SITEMAP_URLS);
        int opened = 0;
        while (!queue.isEmpty() && opened < cfg.sitemapPages) {
            String sm = queue.pollFirst();
            try {
                page.navigate(sm, new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(45_000));
                opened++;
                // Chrome 打开 XML 会套一层 viewer，page.content() 可能是 viewer 的 HTML，
                // 原始 <loc> 被转义成文本。所以同时取源码与可见文本，双路抽 URL。
                String raw = page.content();
                try {
                    String visible = (String) page.evaluate(
                            "() => document.body ? document.body.innerText : ''");
                    if (visible != null) raw = raw + "\n" + visible;
                } catch (PlaywrightException ignored) {}

                boolean isIndex = raw.toLowerCase(Locale.ROOT).contains("sitemapindex");
                List<String> children = new ArrayList<>();
                Set<String> found = new LinkedHashSet<>();

                Matcher m = LOC_TAG.matcher(raw);
                while (m.find()) found.add(m.group(1).trim().replace("&amp;", "&"));
                Matcher m2 = LIZ_URL.matcher(raw);
                while (m2.find()) found.add(m2.group().replace("&amp;", "&"));

                int n = 0;
                for (String u : found) {
                    if (u == null || !u.toLowerCase().contains("ieltsliz.com")) continue;
                    String low = u.toLowerCase(Locale.ROOT);
                    if (low.contains(".xml") || low.contains("sitemap")) {
                        if (isIndex && children.size() < 30) children.add(u);
                        continue;
                    }
                    String norm = normalizeContentUrl(u);
                    if (norm.isBlank() || !isContentUrl(norm)) continue;
                    if (out.add(norm)) n++;
                }
                System.out.printf("[sitemap] %s -> %s，新增 %d 条（累计 %d，子 sitemap %d 个）%n",
                        sm, isIndex ? "index" : "urlset", n, out.size(), children.size());

                // 一个候选成功就停用其余候选，把队列换成它的子 sitemap
                if (isIndex || n > 0) {
                    queue.clear();
                    for (String c : children) queue.addLast(c);
                }
            } catch (Exception e) {
                System.out.println("[sitemap] 获取失败 " + sm + " : " + e.getMessage());
            }
        }
        return new ArrayList<>(out);
    }

    private static List<String> collectFromRss(Page page, Config cfg) {
        Set<String> out = new LinkedHashSet<>();
        try {
            page.navigate(RSS_URL, new Page.NavigateOptions()
                    .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(45_000));
            String raw = page.content();
            try {
                String visible = (String) page.evaluate(
                        "() => document.body ? document.body.innerText : ''");
                if (visible != null) raw = raw + "\n" + visible;
            } catch (PlaywrightException ignored) {}
            Matcher m = LIZ_URL.matcher(raw);
            while (m.find()) {
                String u = normalizeContentUrl(m.group().replace("&amp;", "&"));
                if (!u.isBlank() && isContentUrl(u)) out.add(u);
            }
            // 有些 feed 只给 <link> 文本，补一层 <loc>/<link> 标签抽取
            Matcher m2 = Pattern.compile("<(?:loc|link)>\\s*([^<\\s]+)\\s*</(?:loc|link)>",
                    Pattern.CASE_INSENSITIVE).matcher(raw);
            while (m2.find()) {
                String u = normalizeContentUrl(m2.group(1).replace("&amp;", "&"));
                if (!u.isBlank() && isContentUrl(u)) out.add(u);
            }
            System.out.println("[RSS] /feed/ -> " + out.size() + " 条");
        } catch (Exception e) {
            System.out.println("[RSS] 获取失败（不影响主流程）：" + e.getMessage());
        }
        return new ArrayList<>(out);
    }

    private static String normalizeContentUrl(String u) {
        if (u == null || u.isBlank()) return "";
        try {
            java.net.URI uri = java.net.URI.create(u);
            String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase().replaceFirst("^www\\.", "");
            if (!"ieltsliz.com".equals(host)) return "";
            String p = uri.getPath() == null ? "/" : uri.getPath();
            String q = uri.getQuery() == null ? "" : uri.getQuery();
            List<String[]> keep = new ArrayList<>();
            if (!q.isBlank()) {
                for (String kv : q.split("&")) {
                    String[] a = kv.split("=", 2);
                    String k = a[0];
                    if (List.of("p", "page_id", "post_type", "cat", "page").contains(k) && a.length == 2) {
                        keep.add(new String[]{k, a[1]});
                    }
                }
                keep.sort(Comparator.comparing(x -> x[0]));
            }
            String qs = keep.isEmpty() ? "" : "?" + keep.stream()
                    .map(x -> x[0] + "=" + x[1]).reduce((a, b) -> a + "&" + b).orElse("");
            if ((p.equals("/") || p.isEmpty()) && qs.isEmpty()) return "";
            return "https://ieltsliz.com" + p + qs;
        } catch (Exception e) {
            return "";
        }
    }

    /** 内容页判据：固定链接路径，或带 WordPress 内容参数 */
    private static boolean isContentUrl(String u) {
        if (u == null || !u.toLowerCase().startsWith("https://ieltsliz.com")) return false;
        String low = u.toLowerCase(Locale.ROOT);
        String[] bad = {"/wp-admin/", "/wp-content/", "/wp-json/", "/wp-includes/", "/feed/",
                "/comments/", "/trackback/", "/author/", "/tag/", "/attachment/", "/shop/",
                "/checkout/", "/cart/", "/my-account/", "/sitemap", "/?s="};
        for (String b : bad) if (low.contains(b)) return false;
        if (low.matches(".*\\.(jpg|jpeg|png|webp|gif|svg|pdf|zip|mp3|mp4|docx?|xlsx?)$")) return false;
        if (low.contains("?p=") || low.contains("?page_id=") || low.contains("post_type=")) return true;
        String path;
        try { path = java.net.URI.create(u).getPath(); } catch (Exception e) { return false; }
        if (path == null || path.equals("/") || path.isBlank()) return false;
        return path.replaceAll("/+", "/").length() > 2;
    }

    private static void harvest(Page page, Config cfg, Set<String> links,
                                Set<String> nav, List<String> dropped) throws Exception {
        int total = 1 + cfg.scroll;
        collectOnce(page, cfg, links, nav, dropped, 0, total);
        for (int i = 1; i <= cfg.scroll; i++) {
            try {
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight * 0.6)");
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(500, 900));
                page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)");
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(1000, 1800));
            } catch (PlaywrightException ignored) {}
            collectOnce(page, cfg, links, nav, dropped, i, total);
        }
    }

    @SuppressWarnings("unchecked")
    private static void collectOnce(Page page, Config cfg, Set<String> links,
                                    Set<String> nav, List<String> dropped,
                                    int round, int total) throws Exception {
        String raw = (String) page.evaluate(COLLECT_JS);
        Map<String, Object> res = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});
        List<String> got = (List<String>) res.get("urls");
        List<String> navs = (List<String>) res.get("nav");
        List<String> drop = (List<String>) res.get("dropped");
        int before = links.size();
        if (got != null) links.addAll(got);
        if (navs != null) nav.addAll(navs);
        if (drop != null) for (String x : drop) if (!dropped.contains(x)) dropped.add(x);
        System.out.printf("[收集] 第 %d/%d 轮：+%d 条，累计 %d 条%n",
                round + 1, total, links.size() - before, links.size());
    }

    /** 导航 + WAF 检测；超时只警告不抛，避免整批 0 条 */
    private static void open(Page page, String url, Config cfg) {
        page.navigate(url, new Page.NavigateOptions()
                .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
        for (int i = 0; i < cfg.waitSeconds; i++) {
            String state = "";
            try { state = (String) page.evaluate(PAGE_STATE_JS); }
            catch (PlaywrightException ignored) {}
            boolean blocked = state.contains("\"blocked\":true");
            boolean ok = state.contains("\"ready\":true") && !blocked;
            int len = intField(state, "textLen");
            if (ok && len > 150) return;
            if ((blocked || len < 100) && i == 3) {
                System.out.println("[警告] 疑似 WAF 拦截 / 空白页：" + state);
                System.out.println("[警告] 本站直连 HTTP 全站 403：用 --cdp 连手动开的 Chrome、"
                        + "--headless=false；国内网络可加 --proxy。");
            }
            if (cfg.manual && (blocked || len < 100) && i == 6) {
                System.out.println("[人工] 请在 Chrome 窗口里刷新/完成验证，看到页面后"
                        + "回控制台按【回车】继续…");
                try { System.in.read(); } catch (java.io.IOException ignored) {}
                return;
            }
            page.waitForTimeout(1000);
        }
        System.out.println("[警告] " + cfg.waitSeconds + "s 内未达到预期渲染，仍尝试抽取：" + url);
    }

    private static int intField(String json, String key) {
        try {
            Matcher m = Pattern.compile("\"" + key + "\":(\\d+)").matcher(json);
            return m.find() ? Integer.parseInt(m.group(1)) : 0;
        } catch (Exception e) { return 0; }
    }

    /** 按标题 / URL / 小标题给资料归类，方便按用途筛 */
    private static String classify(String title, String url, List<String> headings) {
        String s = ((title == null ? "" : title) + " " + (url == null ? "" : url) + " "
                + (headings == null ? "" : String.join(" ", headings))).toLowerCase(Locale.ROOT);
        if (s.contains("model answer") || s.contains("band 9 essay") || s.contains("sample answer"))
            return "model-answer";
        if (s.contains("speaking part 1") || s.contains("part one topic") || s.contains("speaking-part-1"))
            return "speaking-part-1";
        if (s.contains("speaking part 2") || s.contains("part two topic") || s.contains("cue card")
                || s.contains("speaking-part-2")) return "speaking-part-2";
        if (s.contains("speaking part 3") || s.contains("part three topic") || s.contains("speaking-part-3"))
            return "speaking-part-3";
        if (s.contains("vocabulary") || s.contains("linking words") || s.contains("useful words")
                || s.contains("collocations") || s.contains("phrases")) return "vocabulary";
        if (s.contains("essay question") || s.contains("recent exam question")) return "essay-questions";
        if (s.contains("writing task 2") || s.contains("task-2") || s.contains("ielts essay"))
            return "writing-task-2";
        if (s.contains("writing task 1") || s.contains("task-1") || s.contains("sample chart")
                || s.contains("letter")) return "writing-task-1";
        if (s.contains("reading")) return "reading";
        if (s.contains("listening")) return "listening";
        if (s.contains("band score") || s.contains("marking criteria")) return "band-descriptors";
        if (s.contains("speaking")) return "speaking";
        return "lesson";
    }

    private static Map<String, String> readLd(List<String> lds) {
        if (lds == null) return Map.of();
        for (String s : lds) {
            try {
                Deque<JsonNode> q = new ArrayDeque<>();
                q.add(MAPPER.readTree(s));
                while (!q.isEmpty()) {
                    JsonNode cur = q.poll();
                    if (cur == null || cur.isNull()) continue;
                    if (cur.isArray()) { cur.forEach(q::add); continue; }
                    if (!cur.isObject()) continue;
                    if (cur.has("headline") || cur.has("datePublished") || cur.has("@type")) {
                        Map<String, String> m = new HashMap<>();
                        m.put("headline", cur.path("headline").asText(""));
                        m.put("datePublished", cur.path("datePublished").asText(""));
                        m.put("dateModified", cur.path("dateModified").asText(""));
                        m.put("description", cur.path("description").asText(""));
                        m.put("articleSection", cur.path("articleSection").asText(""));
                        m.put("author", authorOf(cur.get("author")));
                        if (!m.get("headline").isBlank() || !m.get("datePublished").isBlank()) return m;
                    }
                    cur.fields().forEachRemaining(e -> {
                        JsonNode v = e.getValue();
                        if (v.isObject() || v.isArray()) q.add(v);
                    });
                }
            } catch (Exception ignored) {}
        }
        return Map.of();
    }

    private static String authorOf(JsonNode n) {
        if (n == null || n.isNull()) return "";
        if (n.isTextual()) return n.asText("");
        if (n.isArray()) {
            List<String> xs = new ArrayList<>();
            n.forEach(x -> { String s = authorOf(x); if (!s.isBlank()) xs.add(s); });
            return String.join(", ", xs);
        }
        if (n.isObject()) return n.path("name").asText("");
        return "";
    }

    private static String firstNonBlank(String... xs) {
        for (String x : xs) if (x != null && !x.isBlank()) return x;
        return "";
    }

    private static void politeSleep() {
        try { Thread.sleep(ThreadLocalRandom.current().nextInt(1600, 3200)); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    private static class Config {
        int limit = 30000;
        int waitSeconds = 25;
        int scroll = 2;
        int follow = 4;
        int sitemapPages = 12;
        boolean headless = false;
        boolean warmup = true;
        boolean manual = false;
        boolean requireLesson = true;
        String source = "both";        // sitemap | channel | rss | both | all
        String seedsRaw = "";
        List<String> seeds = SEEDS;
        Set<String> only = new LinkedHashSet<>();   // --only=model-answer,speaking-part-1
        String profileDir = "./.pw-profile-ieltsliz";
        String channel = "chrome";
        String chromePath = "";
        String cdpUrl = "";
        String proxy = "";
        String outFile = "ielts-liz.json";

        static Config parse(String[] a) {
            Config c = new Config();
            for (String s : a) {
                if (s.startsWith("--limit=")) c.limit = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--wait=")) c.waitSeconds = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--scroll=")) c.scroll = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--follow=")) c.follow = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--sitemap-pages=")) c.sitemapPages = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--headless=")) c.headless = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--warmup=")) c.warmup = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--manual=")) c.manual = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--require-lesson=")) c.requireLesson = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--source=")) c.source = s.split("=", 2)[1];
                else if (s.startsWith("--seeds=")) c.seedsRaw = s.split("=", 2)[1];
                else if (s.startsWith("--only=")) {
                    for (String t : s.split("=", 2)[1].split(",")) {
                        String v = t.trim().toLowerCase(Locale.ROOT);
                        if (!v.isBlank()) c.only.add(v);
                    }
                }
                else if (s.startsWith("--profile=")) c.profileDir = s.split("=", 2)[1];
                else if (s.startsWith("--channel=")) c.channel = s.split("=", 2)[1];
                else if (s.startsWith("--chrome-path=")) c.chromePath = s.split("=", 2)[1];
                else if (s.startsWith("--cdp=")) c.cdpUrl = s.split("=", 2)[1];
                else if (s.startsWith("--proxy=")) c.proxy = s.split("=", 2)[1];
                else if (s.startsWith("--out=")) c.outFile = s.split("=", 2)[1];
                else if (s.equals("--help")) {
                    System.out.println("""
                            参数（JDK 17 / Playwright / IELTS Liz）：
                              --limit=30                    最多抓取页数
                              --source=both                 sitemap | channel | rss | both | all
                              --sitemap-pages=12            最多展开多少个子 sitemap
                              --scroll=2                    频道页滚动次数
                              --follow=4                    跟进几个栏目/分页页
                              --seeds=url1,url2             自定义种子页
                              --only=model-answer,vocabulary,speaking-part-1
                                                            只保留指定 contentType（逗号分隔）
                              --require-lesson=true|false   默认 true：只留内容页
                              --wait=25                     每页等待渲染秒数
                              --warmup=true                 首页预热
                              --headless=false|true         默认 false
                              --cdp=http://127.0.0.1:9222  连接手动开的 Chrome（推荐，直连 HTTP 全站 403）
                              --channel=chrome|chromium     默认本机 Chrome stable
                              --chrome-path=...             显式指定 Chrome 可执行文件
                              --profile=./.pw-profile-ieltsliz
                              --proxy=... / --manual=true   可选代理；拦截时人工兜底
                              --out=ielts-liz.json
                              --help

                            contentType 取值：model-answer / speaking-part-1 / speaking-part-2 /
                              speaking-part-3 / vocabulary / essay-questions / writing-task-2 /
                              writing-task-1 / reading / listening / band-descriptors / speaking / lesson
                            """);
                    System.exit(0);
                }
            }
            if (!c.seedsRaw.isBlank()) {
                c.seeds = Arrays.stream(c.seedsRaw.split(","))
                        .map(String::trim).filter(x -> !x.isBlank()).toList();
            }
            return c;
        }
    }
}
