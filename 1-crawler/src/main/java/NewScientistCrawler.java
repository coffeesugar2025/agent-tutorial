import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.WaitUntilState;

import java.nio.file.Paths;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * New Scientist（https://www.newscientist.com/）文章抓取。
 * 技术栈与前面几个主类一致：JDK 17 + Playwright 驱动【本地 Chrome】+ Jackson，无 Jsoup。
 *
 * 站点要点：
 *  - 文章 URL：https://www.newscientist.com/article/2592450-xxx/  （/article/<数字ID>-<slug>/）
 *  - 栏目页：/section/news/、/section/features/、/section/comment/、/section/regulars/，
 *            分页 /section/features/page/2/
 *  - RSS：/section/news/feed/、/feed/home/
 *  - freemium：部分文章是 subscriber-only，页面只放出前几段。
 *    代码【只取公开可见的段落】，检测并标记 access / paywall / truncated，不登录、不绕过、
 *    不移除付费墙 DOM、不请求隐藏接口。--skip-paywall=true 可整篇跳过订阅墙文章。
 *  - 直连 HTTP 会 403（站点 WAF），所以必须 --cdp 连手动开的原生 Chrome；
 *    --warmup=true 先访问首页再进栏目页，--manual=true 遇拦截页停住人工处理。
 *
 * 运行（IntelliJ Main class 改成 NewScientistCrawler）：
 *   --limit=20 --cdp=http://127.0.0.1:9222 --scroll=3 --follow=4 --warmup=true
 *   --source=both --limit=60
 */
public class NewScientistCrawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /** 正文段落格式：与前几个主类一致，每段开头 \t、结尾 \n */
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";

    /** 频道种子页；可用 --seeds= 覆盖（逗号分隔） */
    private static final List<String> SEEDS = List.of(
            "https://www.newscientist.com/",
            "https://www.newscientist.com/section/news/",
            "https://www.newscientist.com/section/features/"
    );

    private static final List<String> RSS_URLS = List.of(
            "https://www.newscientist.com/section/news/feed/",
            "https://www.newscientist.com/feed/home/"
    );

    private static final Pattern NS_ARTICLE_URL = Pattern.compile(
            "https?://(?:www\\.)?newscientist\\.com/article/[^\"'<>\\s]+");

    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    /**
     * 频道页收集文章链接。
     * 三路来源：a[href]、卡片 data-*、内嵌 JSON / outerHTML 里的绝对 URL。
     * 硬约束：路径必须以 /article/ 开头；栏目/分页链接单独返回给 Java 侧跟进。
     * 返回 {urls, dropped, nav}，dropped 是被规则丢弃的样本，用于诊断误杀。
     */
    private static final String COLLECT_JS = """
            (needArticle) => {
              const out = new Set();
              const nav = new Set();
              const droppedArticle = new Set();
              const droppedOther = new Set();
              const bad = ['/video/', '/podcast/', '/events/', '/subscribe/', '/shop/',
                           '/courses/', '/newsletter/', '/search', '/author/', '/tag/',
                           '/topic/', '/about/', '/privacy/', '/terms/', '/contact/',
                           '/press/', '/advertising/', '/sitemap', '/round-up/', '/page/'];

              const norm = (raw) => {
                try {
                  let href = (raw || '').trim().replace(/&amp;/g, '&');
                  if (!href || href.startsWith('#') || /^javascript:/i.test(href)) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  const h = u.hostname.toLowerCase();
                  if (!(h === 'newscientist.com' || h.endsWith('.newscientist.com'))) return;
                  let p = u.pathname;
                  if (p.toLowerCase().startsWith('/amp/')) p = p.substring(4);
                  if (/\\/feed\\/?$/i.test(p)) return;              // RSS 不是文章页
                  if (!p.endsWith('/') && !/\\.html?$/i.test(p)) p += '/';
                  // 清掉 ?ref= / ?dcmpotc-rss / #fragment，统一 host，避免同文多链接
                  const finalUrl = 'https://www.newscientist.com' + p;
                  if (needArticle && !p.toLowerCase().startsWith('/article/')) {
                    // /section/、/video/ 等是正常导航，不算「被丢弃的文章」；
                    // 只有既非 /article/ 又非已知栏目页的才进诊断样本
                    if (!p.toLowerCase().startsWith('/section/')
                            && !bad.some(b => p.toLowerCase().startsWith(b))) {
                      droppedArticle.add('非/article/    ' + finalUrl.slice(0, 120));
                    }
                    return;
                  }
                  if (bad.some(b => p.toLowerCase().startsWith(b))) {
                    droppedOther.add('栏目页       ' + finalUrl.slice(0, 120));
                    return;
                  }
                  if (/pardon|access-denied|403|error/i.test(p)) {
                    droppedOther.add('拦截页       ' + finalUrl.slice(0, 120));
                    return;
                  }
                  out.add(finalUrl);
                } catch (e) {}
              };

              // 栏目 Tab / 分页：/section/... 路径，保留 /page/N/ 结构
              const collectNav = (href) => {
                try {
                  if (!href) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  const h = u.hostname.toLowerCase();
                  if (!(h === 'newscientist.com' || h.endsWith('.newscientist.com'))) return;
                  const p = u.pathname.toLowerCase();
                  if (!p.startsWith('/section/')) return;
                  if (p.includes('/feed/')) return;
                  if (p.startsWith('/article/')) return;
                  nav.add('https://www.newscientist.com' + u.pathname + (u.search || ''));
                } catch (e) {}
              };

              // 1) 常规锚点
              document.querySelectorAll('a[href]').forEach(a => {
                const href = a.getAttribute('href');
                norm(href);
                collectNav(href);
              });

              // 2) 部分 React 卡片不写 href，把链接放在 data-* 上
              const keys = ['data-href', 'data-url', 'data-link', 'data-target-url',
                            'data-analytics-url', 'data-card-url', 'data-story-url'];
              document.querySelectorAll(keys.map(k => '[' + k + ']').join(', '))
                      .forEach(el => keys.forEach(k => norm(el.getAttribute(k))));

              // 3) 首屏状态 / ld+json / __NEXT_DATA__ / 页面源码里散落的绝对 URL
              const sources = [];
              document.querySelectorAll('script[type="application/ld+json"], script#__NEXT_DATA__, ' +
                                        'script[id*="data"], script[data-module], script[type="application/json"]')
                      .forEach(s => sources.push(s.textContent || ''));
              sources.push(document.documentElement.outerHTML);
              const re = /https?:\\/\\/(?:www\\.)?newscientist\\.com\\/article\\/[^"'\\s<>]+/gi;
              for (const src of sources) {
                let m;
                while ((m = re.exec(src)) !== null) norm(m[0]);
              }
              return JSON.stringify({
                urls: [...out],
                dropped: [...droppedArticle, ...droppedOther].slice(0, 40),
                nav: [...nav].slice(0, 40)
              });
            }
            """;

    /** 文章页抽取：正文只取 p 标签；按「文本量」挑容器；检测付费墙；收集 JSON-LD */
    private static final String EXTRACT_JS = """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              const meta = (sel, attr) => clean(document.querySelector(sel)?.getAttribute(attr || 'content'));

              const title = clean(document.querySelector(
                        'h1[class*="headline"], h1[class*="title"], h1[itemprop="headline"], h1')?.innerText)
                    || meta('meta[property="og:title"]') || clean(document.title);

              const time = meta('meta[property="article:published_time"]')
                    || clean(document.querySelector('time[datetime]')?.getAttribute('datetime'))
                    || meta('meta[name="date"]') || meta('meta[name="parsely-pub-date"]') || '';
              const modified = meta('meta[property="article:modified_time"]')
                    || meta('meta[name="last-modified"]') || '';
              const author = meta('meta[name="author"]')
                    || clean(document.querySelector('[rel="author"], [class*="byline"], [class*="author"]')?.innerText);
              const section = meta('meta[property="article:section"]')
                    || meta('meta[name="parsely-section"]')
                    || clean(document.querySelector('[class*="category"], [class*="section-label"]')?.innerText);
              const description = meta('meta[name="description"]') || meta('meta[property="og:description"]');
              const keywords = meta('meta[name="keywords"]') || meta('meta[name="news_keywords"]');
              const image = meta('meta[property="og:image"]');

              // 付费墙检测：只识别、不绕过
              const bodyText = (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ');
              const paywallRe = /Subscribe to (read|continue|access)|subscriber[- ]?only|This article is for subscribers|Unlock this (article|story)|You've reached your (free )?article limit|Already a subscriber\\?|Get unlimited access|Subscribe now to continue reading/i;
              const paywallEl = document.querySelector(
                    '[class*="paywall"], [data-component*="paywall"], [data-testid*="paywall"], ' +
                    '[id*="paywall"], [class*="subscribe-wall"], [class*="meter"]');
              const paywallHint = clean((bodyText.match(paywallRe) || [''])[0])
                    || (paywallEl ? clean(paywallEl.innerText).slice(0, 160) : '');
              const paywall = paywallHint.length > 0 || !!paywallEl;

              const NOISE_SEL = [
                    'aside', 'footer', 'nav', 'header',
                    '[class*="advert"]', '[class*="sponsored"]', '[class*="newsletter"]',
                    '[class*="related"]', '[class*="recirc"]', '[class*="promo"]',
                    '[class*="subscribe"]', '[class*="share"]', '[class*="comments"]',
                    '[class*="paywall"]', '[data-component*="paywall"]', '[data-testid*="paywall"]',
                    '[class*="cookie"]', '[class*="banner"]'
                  ].join(', ');
              const NOISE_TEXT = /^(Advertisement|Sponsored|Sign up|Subscribe|Read more|More from|Related|Share|Follow us|Newsletter|Get the|Watch|Listen|Credit:|Image credit|Photograph:|Illustration:|Already a subscriber|Subscribe to continue|Read next|Most popular|Explore more)/i;

              const pick = (sel, minLen) => [...document.querySelectorAll(sel)]
                    .filter(p => !p.closest(NOISE_SEL))
                    .map(p => clean(p.innerText))
                    .filter(t => t.length > minLen && !NOISE_TEXT.test(t));

              // 按「实际抽到的文本量」挑容器，而不是第一个存在的容器：
              // 很多站点语义 wrapper 存在但正文是它的兄弟节点，停第一个会静默得到空串
              const candidates = [
                    '[itemprop="articleBody"] p',
                    '[class*="article-body"] p', '[class*="ArticleBody"] p',
                    '[class*="articleBody"] p',
                    '[class*="article-content"] p', '[class*="ArticleContent"] p',
                    '[class*="story-body"] p', '[class*="StoryBody"] p',
                    '[data-component*="article-body"] p', '[data-testid*="article-body"] p',
                    '[class*="article"] p',
                    'article p', 'main p', 'body p'
              ];
              let body = [];
              for (const sel of candidates) {
                const t = pick(sel, 25);
                const chars = t.reduce((n, x) => n + x.length, 0);
                if (t.length >= 2 && chars >= 300) { body = t; break; }
                if (t.length > body.length) body = t;   // 保留最好的一次，全不达标也有兜底
              }
              const seen = new Set();
              body = body.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; });

              const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => s.textContent.trim()).filter(s => s.length > 0);

              return JSON.stringify({
                title: title, url: location.href, time: time, modified: modified,
                author: author, section: section, description: description,
                keywords: keywords, image: image,
                paywall: paywall, paywallHint: paywallHint,
                paragraphs: body, lds: lds
              });
            }
            """;

    /** 页面状态：WAF 拦截 / 空页 / 正常渲染 */
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

    /** 模式 A：Playwright 拉起独立 profile 的本地 Chrome */
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
        System.out.println("[提示] 本站直连 HTTP 会 403，强烈建议 --cdp 连手动开的 Chrome。");

        BrowserContext ctx;
        try {
            ctx = pw.chromium().launchPersistentContext(
                    Paths.get(cfg.profileDir).toAbsolutePath(), opt);
        } catch (PlaywrightException e) {
            throw new IllegalStateException("启动本地 Chrome 失败：" + e.getMessage()
                    + "。可换 --profile 目录、用 --chrome-path 指定，或 --cdp 连手动开的 Chrome。", e);
        }
        try {
            crawl(ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0), cfg);
        } finally {
            ctx.close();
        }
    }

    /** 模式 B：CDP 连接手动启动的原生 Chrome（WAF 下最稳） */
    private static void attach(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 建议先在该 Chrome 里手动打开一次 "
                + "https://www.newscientist.com/ 确认能看到首页文章列表。");
        Browser browser = pw.chromium().connectOverCDP(cfg.cdpUrl);
        if (browser.contexts().isEmpty()) {
            throw new IllegalStateException("CDP 已连接但没有可用的 browser context。");
        }
        Page page = browser.contexts().get(0).newPage();
        try {
            crawl(page, cfg);
        } finally {
            page.close();   // 只关自己开的标签，不动用户的浏览器
        }
    }

    /** 公共抓取流程 */
    private static void crawl(Page page, Config cfg) throws Exception {
        if (cfg.cdpUrl.isBlank()) page.addInitScript(STEALTH_JS);
        page.setDefaultTimeout(30_000);

        // Session 预热：首页 → 栏目页，避免全新 session 直接命中高价值 URL 被判低分
        if (cfg.warmup) {
            System.out.println("[预热] 先访问 New Scientist 首页…");
            try {
                page.navigate("https://www.newscientist.com/", new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(1800, 3200));
            } catch (PlaywrightException e) {
                System.out.println("[预热] 首页访问异常（继续）：" + e.getMessage());
            }
        }

        // 1) 收集文章链接：边滚边收，避免懒加载把前面卡片换掉
        Set<String> links = new LinkedHashSet<>();
        List<String> droppedSamples = new ArrayList<>();
        Set<String> navLinks = new LinkedHashSet<>();
        if (!cfg.source.equalsIgnoreCase("rss")) {
            for (String seed : cfg.seeds) {
                try {
                    open(page, seed, cfg);   // 超时只警告不抛
                    harvestChannel(page, cfg, links, droppedSamples, navLinks);
                    System.out.printf("[频道页] %s -> 累计 %d 条%n", seed, links.size());
                } catch (Exception e) {
                    System.out.println("[频道页] 失败 " + seed + " : " + e.getMessage());
                    try { collectOnce(page, cfg, links, droppedSamples, navLinks, -1); }
                    catch (Exception ignored) {}
                }
                politeSleep();
                if (links.size() >= cfg.limit * 3) break;
            }

            // 1b) 跟进栏目 Tab / 分页（/section/.../page/N/），否则只有首屏那几张卡片
            List<String> toFollow = new ArrayList<>(navLinks);
            int followed = 0;
            for (String nav : toFollow) {
                if (followed >= cfg.follow || links.size() >= cfg.limit * 3) break;
                if (cfg.seeds.contains(nav)) continue;
                try {
                    open(page, nav, cfg);
                    harvestChannel(page, cfg, links, droppedSamples, navLinks);
                    followed++;
                    System.out.printf("[栏目/分页 %d/%d] %s -> 累计 %d 条%n",
                            followed, cfg.follow, nav, links.size());
                    politeSleep();
                } catch (Exception e) {
                    System.out.println("[栏目/分页] 跳过 " + nav + " : " + e.getMessage());
                }
            }
        }
        if (!cfg.source.equalsIgnoreCase("channel") && links.size() < cfg.limit * 2) {
            links.addAll(collectFromRss(page, cfg));
        }

        // 诊断：被丢弃的链接样本，一眼看清是不是规则误杀
        if (!droppedSamples.isEmpty()) {
            System.out.println("[诊断] 频道页里被丢弃的链接样本（前 10 条）：");
            droppedSamples.stream().limit(10).forEach(d -> System.out.println("    " + d));
        }

        // 硬约束兜底：无论 DOM / RSS / 自定义种子页，最终待抓链接一律必须是 /article/
        int before = links.size();
        Set<String> filtered = new LinkedHashSet<>();
        for (String u : links) {
            if (cfg.requireArticle && !u.toLowerCase(Locale.ROOT).contains("/article/")) continue;
            filtered.add(u);
        }
        links = filtered;
        if (before != links.size()) {
            System.out.printf("[过滤] 排除 %d 条非 /article/ 链接，保留 %d 条%n",
                    before - links.size(), links.size());
        }
        System.out.println("[收集] 候选文章 " + links.size() + " 条（--require-article="
                + cfg.requireArticle + "，--limit=" + cfg.limit + "）");
        if (links.isEmpty()) {
            System.out.println("[提示] 0 条：优先看 [警告] 是否 403 / 拦截页；"
                    + "加大 --scroll / --follow，或 --source=both 补 RSS。");
        }

        // 2) 逐篇抓正文
        List<Map<String, Object>> news = new ArrayList<>();
        for (String url : links) {
            if (news.size() >= cfg.limit) break;
            if (cfg.requireArticle && !url.toLowerCase(Locale.ROOT).contains("/article/")) {
                System.out.println("跳过（非 /article/）: " + url);
                continue;
            }
            try {
                open(page, url, cfg);
                String raw = (String) page.evaluate(EXTRACT_JS);
                Map<String, Object> d = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});

                @SuppressWarnings("unchecked")
                List<String> paras = (List<String>) d.get("paragraphs");
                @SuppressWarnings("unchecked")
                List<String> lds = (List<String>) d.get("lds");
                Map<String, String> ld = readNewsArticleLd(lds);

                // 段落兜底：DOM 没抽到就用 JSON-LD 的 articleBody（很多站点不填，属正常）
                if ((paras == null || paras.isEmpty()) && !ld.getOrDefault("articleBody", "").isBlank()) {
                    paras = splitParagraphs(ld.get("articleBody"));
                }
                boolean paywall = Boolean.TRUE.equals(d.get("paywall"));
                if (cfg.skipPaywall && paywall) {
                    System.out.println("跳过（订阅墙）: " + url);
                    continue;
                }
                String title = firstNonBlank(ld.get("headline"), (String) d.get("title"));
                boolean isArticle = !title.isBlank()
                        && (!ld.isEmpty() || (paras != null && paras.size() >= 2) || paywall);
                if (!isArticle) {
                    System.out.println("跳过（非文章/被拦）: " + url);
                    continue;
                }

                StringBuilder content = new StringBuilder();
                if (paras != null) {
                    for (String p : paras) content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);
                }

                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title", title);
                item.put("url", d.get("url"));
                item.put("publishedAt", firstNonBlank(ld.get("datePublished"), (String) d.get("time")));
                item.put("modifiedAt", firstNonBlank(ld.get("dateModified"), (String) d.get("modified")));
                item.put("author", firstNonBlank(ld.get("author"), (String) d.get("author")));
                item.put("section", firstNonBlank(ld.get("articleSection"), (String) d.get("section")));
                item.put("description", firstNonBlank(ld.get("description"), (String) d.get("description")));
                item.put("keywords", firstNonBlank(ld.get("keywords"), (String) d.get("keywords")));
                item.put("image", firstNonBlank(ld.get("image"), (String) d.get("image")));
                item.put("access", paywall ? "subscriber-only" : "free");
                item.put("paywall", paywall);
                item.put("truncated", paywall);          // 付费墙文章只拿到公开可见部分
                item.put("paywallHint", d.get("paywallHint"));
                item.put("paragraphs", paras == null ? List.of() : paras);
                item.put("content", content.toString());
                news.add(item);

                System.out.printf("[%d/%d]%s %s%n", news.size(), cfg.limit,
                        paywall ? "[订阅墙·仅公开段]" : "", title);
            } catch (Exception e) {
                System.out.println("抓取失败 " + url + " -> " + e.getMessage());
            }
            politeSleep();
        }

        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(Paths.get(cfg.outFile).toFile(), news);
        System.out.println("完成：" + cfg.outFile + "，共 " + news.size() + " 篇（其中订阅墙 "
                + news.stream().filter(x -> Boolean.TRUE.equals(x.get("paywall"))).count() + " 篇）");
    }

    /** 频道页：首屏收一次，每滚一次收一次；--loadmore 点一次收一次 */
    private static void harvestChannel(Page page, Config cfg, Set<String> links,
                                       List<String> dropped, Set<String> nav) throws Exception {
        int total = 1 + cfg.scroll + cfg.loadMore;
        collectOnce(page, cfg, links, dropped, nav, 0, total);
        for (int i = 1; i <= cfg.scroll; i++) {
            scrollBottom(page);
            collectOnce(page, cfg, links, dropped, nav, i, total);
        }
        for (int j = 1; j <= cfg.loadMore; j++) {
            if (!clickLoadMore(page)) break;
            collectOnce(page, cfg, links, dropped, nav, cfg.scroll + j, total);
        }
    }

    @SuppressWarnings("unchecked")
    private static void collectOnce(Page page, Config cfg, Set<String> links,
                                    List<String> dropped, Set<String> nav,
                                    int round, int total) throws Exception {
        String raw = (String) page.evaluate(COLLECT_JS, cfg.requireArticle);
        Map<String, Object> res = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});
        List<String> got = (List<String>) res.get("urls");
        List<String> drop = (List<String>) res.get("dropped");
        List<String> navs = (List<String>) res.get("nav");
        int before = links.size();
        if (got != null) links.addAll(got);
        if (drop != null) for (String x : drop) if (!dropped.contains(x)) dropped.add(x);
        if (navs != null) nav.addAll(navs);
        String tag = round < 0 ? "兜底" : (round + 1) + "/" + total;
        System.out.printf("[收集] 第 %s 轮：+%d 条，累计 %d 条%n", tag, links.size() - before, links.size());
    }

    private static void collectOnce(Page page, Config cfg, Set<String> links,
                                    List<String> dropped, Set<String> nav, int round) throws Exception {
        collectOnce(page, cfg, links, dropped, nav, round, 1);
    }

    private static void scrollBottom(Page page) {
        try {
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight * 0.6)");
            page.waitForTimeout(ThreadLocalRandom.current().nextInt(500, 1000));
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)");
            page.waitForTimeout(ThreadLocalRandom.current().nextInt(1200, 2200));
        } catch (PlaywrightException ignored) {}
    }

    private static boolean clickLoadMore(Page page) {
        String[] sels = {"button:has-text('Load More')", "button:has-text('More')",
                "a:has-text('See more')", "[class*='loadMore']", "[class*='LoadMore']",
                "[data-testid*='load-more']"};
        for (String sel : sels) {
            try {
                Locator l = page.locator(sel).last();
                if (l.count() > 0 && l.isVisible() && l.isEnabled()) {
                    l.click(new Locator.ClickOptions().setTimeout(4000));
                    page.waitForTimeout(ThreadLocalRandom.current().nextInt(1500, 2600));
                    return true;
                }
            } catch (PlaywrightException ignored) {}
        }
        return false;
    }

    /** RSS 补充：Playwright 打开官方 feed，从 XML / 渲染文本里抽 /article/ URL */
    private static List<String> collectFromRss(Page page, Config cfg) {
        Set<String> out = new LinkedHashSet<>();
        for (String feed : RSS_URLS) {
            try {
                page.navigate(feed, new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(45_000));
                String xml = page.content();
                Matcher m = NS_ARTICLE_URL.matcher(xml);
                while (m.find()) {
                    String u = m.group().replace("http://", "https://")
                            .replace("&amp;", "&").split("[?#]")[0];
                    if (!u.contains("/article/")) continue;
                    if (!u.startsWith("https://www.newscientist.com")) {
                        u = u.replaceFirst("https?://(?:www\\.)?newscientist\\.com",
                                "https://www.newscientist.com");
                    }
                    if (!u.endsWith("/")) u += "/";
                    out.add(u);
                }
                System.out.println("[RSS] " + feed + " -> 累计 " + out.size() + " 条");
            } catch (Exception e) {
                System.out.println("[RSS] 获取失败（不影响主流程）：" + feed + " : " + e.getMessage());
            }
        }
        return new ArrayList<>(out);
    }

    /** 导航 + WAF 拦截检测 + 人工兜底；超时只警告不抛，避免整批 0 条 */
    private static void open(Page page, String url, Config cfg) {
        page.navigate(url, new Page.NavigateOptions()
                .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
        for (int i = 0; i < cfg.waitSeconds; i++) {
            String state = "";
            try { state = (String) page.evaluate(PAGE_STATE_JS); }
            catch (PlaywrightException ignored) {}
            boolean blocked = state.contains("\"blocked\":true");
            boolean ok = state.contains("\"ready\":true") && !blocked;
            int textLen = intField(state, "textLen");
            if (ok && textLen > 200) return;

            if ((blocked || textLen < 120) && i == 3) {
                System.out.println("[警告] 疑似 WAF 拦截 / 空白页：" + state);
                System.out.println("[警告] 本站直连 HTTP 会 403：用 --cdp 连手动开的 Chrome、"
                        + "--headless=false、--warmup=true；国内网络可加 --proxy。");
            }
            if (cfg.manual && (blocked || textLen < 120) && i == 6) {
                System.out.println("[人工] 请在 Chrome 窗口里刷新/完成验证，看到正文后"
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

    /** 从 JSON-LD 中找 NewsArticle / Article，取元数据与 articleBody */
    private static Map<String, String> readNewsArticleLd(List<String> lds) {
        if (lds == null) return Map.of();
        Set<String> types = Set.of("NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle",
                "AnalysisNewsArticle", "OpinionNewsArticle", "TechArticle", "Report",
                "LiveBlogPosting", "ScholarlyArticle");
        for (String s : lds) {
            try {
                Deque<JsonNode> q = new ArrayDeque<>();
                q.add(MAPPER.readTree(s));
                while (!q.isEmpty()) {
                    JsonNode cur = q.poll();
                    if (cur == null || cur.isNull()) continue;
                    if (cur.isArray()) { cur.forEach(q::add); continue; }
                    if (!cur.isObject()) continue;

                    JsonNode t = cur.get("@type");
                    Set<String> ts = new HashSet<>();
                    if (t != null) {
                        if (t.isArray()) t.forEach(x -> ts.add(x.asText("")));
                        else ts.add(t.asText(""));
                    }
                    boolean isArticle = ts.stream().anyMatch(types::contains)
                            || ts.stream().anyMatch(x -> x.contains("Article"));
                    if (!isArticle) {
                        cur.fields().forEachRemaining(e -> {
                            JsonNode v = e.getValue();
                            if (v.isObject() || v.isArray()) q.add(v);
                        });
                        continue;
                    }
                    Map<String, String> m = new HashMap<>();
                    m.put("headline", cur.path("headline").asText(""));
                    m.put("datePublished", cur.path("datePublished").asText(""));
                    m.put("dateModified", cur.path("dateModified").asText(""));
                    m.put("description", cur.path("description").asText(""));
                    m.put("articleBody", cur.path("articleBody").asText(""));
                    m.put("articleSection", cur.path("articleSection").asText(""));
                    m.put("keywords", flattenLd(cur.get("keywords")));
                    m.put("author", authorOf(cur.get("author")));
                    m.put("image", imageOf(cur.get("image")));
                    return m;
                }
            } catch (Exception ignored) {
                // LD+JSON 偶有残缺，跳过该片段
            }
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

    private static String imageOf(JsonNode n) {
        if (n == null || n.isNull()) return "";
        if (n.isTextual()) return n.asText("");
        if (n.isArray()) return n.isEmpty() ? "" : imageOf(n.get(0));
        if (n.isObject()) return firstNonBlank(n.path("url").asText(""), n.path("contentUrl").asText(""));
        return "";
    }

    private static String flattenLd(JsonNode n) {
        if (n == null || n.isNull()) return "";
        if (n.isTextual()) return n.asText("");
        if (n.isArray()) {
            List<String> xs = new ArrayList<>();
            n.forEach(x -> { String s = flattenLd(x); if (!s.isBlank()) xs.add(s); });
            return String.join(", ", xs);
        }
        return "";
    }

    /** articleBody 兜底拆段：去标签 + 按行 / 句末标点切 */
    private static List<String> splitParagraphs(String s) {
        if (s == null || s.isBlank()) return List.of();
        String t = s.replaceAll("(?i)<br\\s*/?>", "\n")
                .replaceAll("(?i)</p>", "\n")
                .replaceAll("<[^>]+>", "")
                .replace("&nbsp;", " ").replace("&amp;", "&").replace("\r", "");
        List<String> out = new ArrayList<>();
        for (String line : t.split("\n")) {
            String c = line.replaceAll("\\s+", " ").trim();
            if (c.length() > 2) out.add(c);
        }
        if (out.size() <= 1 && t.length() > 200) {
            out.clear();
            for (String seg : t.split("(?<=[.!?。；;])\\s+")) {
                String c = seg.replaceAll("\\s+", " ").trim();
                if (c.length() > 2) out.add(c);
            }
        }
        return out;
    }

    private static String firstNonBlank(String... xs) {
        for (String x : xs) if (x != null && !x.isBlank()) return x;
        return "";
    }

    private static void politeSleep() {
        try { Thread.sleep(ThreadLocalRandom.current().nextInt(1800, 3800)); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    private static class Config {
        int limit = 20;                // 默认比 8 大，避免「只抓到首屏几篇」的误会
        int waitSeconds = 30;
        int scroll = 3;
        int loadMore = 0;
        int follow = 4;                // 跟进几个栏目 Tab / 分页页
        boolean headless = false;
        boolean warmup = true;
        boolean manual = false;
        boolean requireArticle = true; // 硬约束：URL 必须含 /article/
        boolean skipPaywall = false;   // 默认保留订阅墙文章的公开可见段落并标记
        String source = "channel";     // channel | rss | both
        String seedsRaw = "";
        List<String> seeds = SEEDS;
        String profileDir = "./.pw-profile-newscientist";
        String channel = "chrome";
        String chromePath = "";
        String cdpUrl = "";
        String proxy = "";
        String outFile = "newscientist.json";

        static Config parse(String[] a) {
            Config c = new Config();
            for (String s : a) {
                if (s.startsWith("--limit=")) c.limit = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--wait=")) c.waitSeconds = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--scroll=")) c.scroll = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--loadmore=")) c.loadMore = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--follow=")) c.follow = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--headless=")) c.headless = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--warmup=")) c.warmup = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--manual=")) c.manual = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--require-article="))
                    c.requireArticle = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--skip-paywall="))
                    c.skipPaywall = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--source=")) c.source = s.split("=", 2)[1];
                else if (s.startsWith("--seeds=")) c.seedsRaw = s.split("=", 2)[1];
                else if (s.startsWith("--profile=")) c.profileDir = s.split("=", 2)[1];
                else if (s.startsWith("--channel=")) c.channel = s.split("=", 2)[1];
                else if (s.startsWith("--chrome-path=")) c.chromePath = s.split("=", 2)[1];
                else if (s.startsWith("--cdp=")) c.cdpUrl = s.split("=", 2)[1];
                else if (s.startsWith("--proxy=")) c.proxy = s.split("=", 2)[1];
                else if (s.startsWith("--out=")) c.outFile = s.split("=", 2)[1];
                else if (s.equals("--help")) {
                    System.out.println("""
                            参数（JDK 17 / Playwright / New Scientist）：
                              --limit=20                   最多抓取篇数
                              --wait=30                    每页等待渲染秒数
                              --scroll=3                   频道页滚动次数
                              --loadmore=0                 点 Load More / See more 次数
                              --follow=4                   跟进几个栏目 Tab / 分页页（0=不跟进）
                              --source=channel|rss|both    链接来源；rss 走 /section/news/feed/
                              --seeds=url1,url2            自定义种子页
                              --require-article=true|false 默认 true：URL 必须含 /article/
                              --skip-paywall=true|false    默认 false：保留订阅墙文章并标记，true=整篇跳过
                              --warmup=true                先访问首页预热 session
                              --headless=false|true        默认 false
                              --cdp=http://127.0.0.1:9222 连接手动开的 Chrome（强烈推荐，直连 HTTP 会 403）
                              --channel=chrome|chromium    默认本机 Chrome stable
                              --chrome-path=...            显式指定 Chrome 可执行文件
                              --profile=./.pw-profile-newscientist
                              --proxy=... / --manual=true  可选代理；拦截时停住人工处理
                              --out=newscientist.json
                              --help
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
