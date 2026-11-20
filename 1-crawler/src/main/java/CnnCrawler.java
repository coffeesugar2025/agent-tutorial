import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.microsoft.playwright.*;
import com.microsoft.playwright.options.WaitUntilState;

import java.nio.file.Paths;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * CNN 新闻抓取。技术栈与前面各主类一致：JDK 17 + Playwright 驱动【本地 Chrome】+ Jackson，无 Jsoup。
 *
 * 站点要点（2026 年核实）：
 *  - 文章 URL 是日期路径且【没有 .html 后缀】，例如
 *      https://www.cnn.com/2026/08/19/africa/kenya-helicopter-crash-latam-intl
 *    老文章 / edition 域可能是 .../index.html；/amp/ 与 amp.cnn.com 需还原。
 *  - 官方 RSS（rss.cnn.com）自 2024-08 起已停更，不能当主入口；本类默认走 sitemap + 频道页，
 *    --source=rss 用 Google News 的 site:cnn.com feed 作补充（只有标题与跳转链接）。
 *  - robots.txt 里列了 77 个 AI 爬虫 UA 并统一 Disallow: /（Googlebot 不在列表）。
 *    本类只做个人学习用的小范围索引，不做商业分发、不做模型训练语料。
 *  - CNN 有 All Access 订阅与 "For Subscribers" 内容，部分区域还有计量墙。
 *    本类【只取页面上公开可见的段落】，检测并打标 access / paywall / truncated，绝不绕过。
 *  - 新版正文在 p 标签里（.article__content / [class*="ParagraphMessage"]）；
 *    老版 .zn-body__paragraph 是 div，代码作兜底转成段落数组。元数据优先取 NewsArticle JSON-LD。
 *
 * 视频口径：默认【只抓文章】，/videos/ /live-news/ /video/ /audio/ 等页面一律排除，
 *   绝不下载 mp4/m3u8。--include-video=true 才额外收视频页的【可见元数据】
 *   （标题、描述、时长、缩略图、页面 URL），输出 kind=video、mediaDownloaded=false。
 *
 * 输出 cnn-news.json，格式与前几版一致：只取段落，迭代数组，每段 \t + 文本 + \n。
 *
 * 运行（IntelliJ Main class 改成 CnnCrawler）：
 *   --limit=20 --cdp=http://127.0.0.1:9222 --source=both --warmup=true
 *   --sitemap-month=2026/11 --limit=60 --follow=6
 */
public class CnnCrawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";
    private static final String CAPTURED_AT = Instant.now().toString();

    /** 频道种子页；--seeds= 可覆盖（逗号分隔） */
    private static final List<String> SEEDS = List.of(
            "https://www.cnn.com/",
            "https://www.cnn.com/world",
            "https://www.cnn.com/politics",
            "https://www.cnn.com/business",
            "https://www.cnn.com/health",
            "https://www.cnn.com/entertainment",
            "https://www.cnn.com/science"
    );

    /** 官方 sitemap：news.xml 是 Google News sitemap；/sitemap/article/YYYY/MM 是 HTML 月归档页 */
    private static final List<String> SITEMAPS = List.of(
            "https://www.cnn.com/sitemap/news.xml",
            "https://www.cnn.com/sitemap/section/politics.xml",
            "https://www.cnn.com/sitemap/article/2026/11",
            "https://www.cnn.com/sitemap/article/2026/10"
    );

    /** Google News 的 CNN 限定 feed（rss.cnn.com 已停更，仅作补充，只有标题与跳转链接） */
    private static final String GOOGLE_NEWS_RSS =
            "https://news.google.com/rss/search?q=when:7d+site:cnn.com+-intitle:sitemap&hl=en-US&gl=US&ceid=US:en";

    /** CNN 文章 URL 形态：/YYYY/MM/DD/... 开头；排除视频/直播/图集/互动/计算器等非文章页 */
    private static final Pattern CNN_ARTICLE = Pattern.compile(
            "https://(?:www\\.|edition\\.|us\\.|amp\\.)?cnn\\.com/\\d{4}/\\d{2}/\\d{2}/[^\"<>\\s#'?]+");

    /** 日期路径后第一段若是这些内容类型，就不是文章页（COLLECT_JS 与 Java 侧共用同一份口径） */
    private static final Set<String> NON_ARTICLE_SEG = Set.of(
            "videos", "video", "live-news", "live", "gallery", "interactive",
            "calculators", "specials", "newsletters", "newsletter", "profiles",
            "audio", "podcasts", "collections", "topic", "tag", "author");

    private static final Pattern DATE_PATH =
            Pattern.compile("^/\\d{4}/\\d{2}/\\d{2}/(.+)$");

    /** 视频/直播/音视图集类内容段：仅 --include-video=true 时才收 */
    private static final Set<String> VIDEO_SEG = Set.of(
            "videos", "video", "live-news", "live", "gallery", "audio", "podcasts");

    private static boolean looksLikeCnnVideoUrl(String u) {
        if (u == null || u.isBlank()) return false;
        try {
            java.net.URI uri = java.net.URI.create(u);
            String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
            if (!(host.equals("cnn.com") || host.endsWith(".cnn.com"))) return false;
            String p = uri.getPath() == null ? "" : uri.getPath();
            if (p.toLowerCase(Locale.ROOT).startsWith("/amp/")) p = p.substring(4);
            Matcher m = DATE_PATH.matcher(p);
            if (!m.find()) return false;
            return VIDEO_SEG.contains(m.group(1).split("/")[0].toLowerCase(Locale.ROOT));
        } catch (Exception e) {
            return false;
        }
    }

    /**
     * 统一的文章 URL 硬校验：必须是 /YYYY/MM/DD/ 日期路径，且日期后的第一段不是视频/直播等。
     * 频道页 DOM、sitemap 正则、逐篇抓取前都走这一处，避免各写一份漏掉。
     */
    private static boolean isCnnArticleUrl(String u) {
        if (u == null || u.isBlank()) return false;
        try {
            java.net.URI uri = java.net.URI.create(u);
            String host = uri.getHost() == null ? "" : uri.getHost().toLowerCase(Locale.ROOT);
            if (!(host.equals("cnn.com") || host.endsWith(".cnn.com"))) return false;
            String p = uri.getPath() == null ? "" : uri.getPath();
            if (p.toLowerCase(Locale.ROOT).startsWith("/amp/")) p = p.substring(4);
            Matcher m = DATE_PATH.matcher(p);
            if (!m.find()) return false;
            String first = m.group(1).split("/")[0].toLowerCase(Locale.ROOT);
            return !NON_ARTICLE_SEG.contains(first);
        } catch (Exception e) {
            return false;
        }
    }

    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    /**
     * 频道页收集文章链接：
     * 只收 /YYYY/MM/DD/ 日期路径，统一把 edition/us/amp 子域还原成 www.cnn.com，
     * 去掉 /amp 前缀、index.html 保留（老文章可访问）、清 query 与 hash。
     * 栏目页 / 月度 sitemap 页进 nav 供 --follow 跟进。
     */
    private static final String COLLECT_JS = """
            (includeVideo) => {
              const out = new Set();
              const nav = new Set();
              const dropped = [];
              const bad = ['/videos/', '/video/', '/live-news/', '/live/', '/gallery/',
                           '/interactive/', '/calculators/', '/specials/', '/newsletters/',
                           '/profiles/', '/about/', '/topic/', '/tag/', '/author/', '/search/',
                           '/audio/', '/podcasts/', '/collections/', '/newsletter/', '/sitemap'];

              const add = (raw, label) => {
                try {
                  let href = (raw || '').trim().replace(/&amp;/g, '&');
                  if (!href || href.startsWith('#') || /^javascript:/i.test(href)
                          || /^mailto:/i.test(href)) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:' && u.protocol !== 'http:') return;
                  const h = u.hostname.toLowerCase().replace(/^amp\\./, '');
                  if (!(h === 'cnn.com' || h.endsWith('.cnn.com'))) {
                    if (/cnn\\.com/i.test(u.hostname)) dropped.push('外域       ' + href.slice(0, 110));
                    return;
                  }
                  let p = u.pathname || '/';
                  if (p.toLowerCase().startsWith('/amp/')) p = p.substring(4);
                  const low = p.toLowerCase();

                  // 归档页 / sitemap 索引页 / 栏目页先判，别被 bad 里的 /sitemap 前缀误拦
                  if (/^\\/sitemap(\\/|\\.xml$)/.test(low)
                          || (/^\\/[a-z-]+\\/?$/.test(low) && !/\\/\\d{4}\\//.test(low))) {
                    nav.add('https://www.cnn.com' + p);
                    return;
                  }
                  if (bad.some(b => low.startsWith(b))) {
                    if (/\\/\\d{4}\\/\\d{2}\\/\\d{2}\\//.test(low))
                      dropped.push('非文章类型 ' + (u.origin + p).slice(0, 110));
                    return;
                  }
                  if (/\\.(jpg|jpeg|png|webp|gif|svg|mp4|mp3|pdf|zip)$/i.test(p)) return;

                  // 硬约束：文章必须是 /YYYY/MM/DD/ 日期路径（CNN 新版无 .html 后缀）
                  if (!/^\\/\\d{4}\\/\\d{2}\\/\\d{2}\\//.test(p)) return;
                  // 日期后的第一段是内容类型：videos / live-news / gallery / interactive 等不是文章
                  const badSeg = ['videos', 'video', 'live-news', 'live', 'gallery', 'interactive',
                                  'calculators', 'specials', 'newsletters', 'newsletter', 'profiles',
                                  'topic', 'tag', 'author', 'audio', 'podcasts', 'collections'];
                  const rest = p.replace(/^\\/\\d{4}\\/\\d{2}\\/\\d{2}\\//, '');
                  const firstSeg = rest.split('/')[0].toLowerCase();
                  const videoSeg = ['videos', 'video', 'live-news', 'live', 'gallery', 'audio', 'podcasts'];
                  if (badSeg.includes(firstSeg)) {
                    if (!(includeVideo && videoSeg.includes(firstSeg))) {
                      dropped.push('非文章类型 ' + ('https://www.cnn.com' + p).slice(0, 110));
                      return;
                    }
                  }
                  const finalUrl = 'https://www.cnn.com' + p;

                  if (/for subscribers/i.test(label || '')) {
                    dropped.push('订阅墙标记 ' + finalUrl.slice(0, 110));
                  }
                  out.add(finalUrl);
                } catch (e) {}
              };

              document.querySelectorAll('a[href]').forEach(a =>
                    add(a.getAttribute('href'), (a.innerText || '').trim().slice(0, 60)));

              const keys = ['data-href', 'data-url', 'data-link', 'data-permalink', 'data-analytics'];
              document.querySelectorAll(keys.map(k => '[' + k + ']').join(', '))
                      .forEach(el => keys.forEach(k => add(el.getAttribute(k), '')));

              // SPA 卡片有时不写 href，从内嵌 JSON / outerHTML 里补绝对 URL
              const src = [];
              document.querySelectorAll('script[type="application/ld+json"], script#__NEXT_DATA__, ' +
                                        'script[type="application/json"]')
                      .forEach(s => src.push(s.textContent || ''));
              src.push(document.documentElement.outerHTML);
              const re = /https?:\\/\\/[^"'\\s<>]+/gi;
              for (const s of src) {
                let m;
                while ((m = re.exec(s)) !== null) add(m[0], '');
              }
              return JSON.stringify({
                urls: [...out].slice(0, 300),
                nav: [...nav].slice(0, 60),
                dropped: [...new Set(dropped)].slice(0, 25)
              });
            }
            """;

    /** 正文抽取：优先只取 p；老版 .zn-body__paragraph 是 div，作兜底；JSON-LD 另收 */
    private static final String EXTRACT_JS = """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              const meta = (sel) => clean(document.querySelector(sel)?.getAttribute('content'));
              const title = clean(document.querySelector('h1[data-testid="headline"], h1[class*="headline"], h1')?.innerText)
                          || meta('meta[property="og:title"]') || clean(document.title);
              const time = meta('meta[property="article:published_time"]')
                        || clean(document.querySelector('time[datetime]')?.getAttribute('datetime'))
                        || meta('meta[name="pubdate"]') || '';
              const modified = meta('meta[property="article:modified_time"]')
                            || meta('meta[name="lastmod"]') || '';
              const author = meta('meta[name="author"]')
                          || clean(document.querySelector('[class*="byline"], [rel="author"]')?.innerText);
              const section = meta('meta[property="article:section"]') || meta('meta[name="section"]');
              const description = meta('meta[name="description"]') || meta('meta[property="og:description"]');

              const NOISE_SEL = [
                    '[class*="ad-"]', '[class*="-ad"]', '[class*="Ad-"]', '[data-ad]', '[id^="ad-"]',
                    'aside', 'footer', 'nav', 'header', 'form', '[class*="newsletter"]',
                    '[class*="related"]', '[class*="recirc"]', '[class*="promo"]',
                    '[class*="subscribe"]', '[class*="share"]', '[class*="comment"]',
                    '[class*="newsletter"]', '[class*="pagination"]', '[class*="navigation"]',
                    '[class*="widget"]', '[class*="menu"]', '[class*="cookie"]', '[class*="banner"]'
                  ].join(', ');
              const NOISE_TEXT = /^(Sign up|Subscribe|Subscribe now|Already a subscriber|For Subscribers|Read More|More from|Related|Advertisement|Sponsored|Watch:|Listen:|Follow CNN|Download the CNN|Click here|All Rights Reserved|Terms of Use|Privacy Policy|Ad Feedback|Correction:|Editor's note|CNN Underscored|Up next|Watch CNN|Live Updates|Source:|Credit:)/i;

              const pick = (sel, minLen) => [...document.querySelectorAll(sel)]
                    .filter(el => !el.closest(NOISE_SEL))
                    .map(el => clean(el.innerText))
                    .filter(t => t.length > minLen && !NOISE_TEXT.test(t));

              // 1) 新版 CNN：正文 p 在 .article__content / ParagraphMessage 容器里
              let body = pick('.article__content p, [class*="ParagraphMessage"] p, ' +
                              '[class*="article-body"] p, [itemprop="articleBody"] p, ' +
                              'article p, main p', 25);
              // 2) 老版 CNN：.zn-body__paragraph 是 div 段落（不是 p），转成段落数组
              if (body.length < 2) {
                body = [...document.querySelectorAll('.zn-body__paragraph, ' +
                        '[class*="ParagraphMessage"], [class*="paragraph-message"]')]
                      .filter(el => !el.closest(NOISE_SEL))
                      .map(el => clean(el.innerText))
                      .filter(t => t.length > 25 && !NOISE_TEXT.test(t));
              }
              // 3) 再兜底整页 p
              if (body.length < 2) body = pick('p', 40);

              const seen = new Set();
              body = body.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; })
                         .slice(0, 150);

              // 订阅墙检测：只读公开可见文本，不做任何绕过
              const visible = (document.body ? document.body.innerText : '');
              const head = visible.slice(0, 4000);
              const HINTS = [
                    'For Subscribers', 'Subscribe to read', 'Subscribe to continue reading',
                    'Already a subscriber', 'This story is available exclusively',
                    'Sign in to continue reading', 'Subscribe to CNN All Access',
                    "You've reached your monthly limit", 'You have reached your free article limit',
                    'This article is for subscribers', 'Subscribe for full access'
                  ];
              let paywallHint = '';
              for (const h of HINTS) { if (head.includes(h)) { paywallHint = h; break; } }
              const metaFree = meta('meta[itemprop="isAccessibleForFree"]')
                            || meta('meta[property="isAccessibleForFree"]');
              if (!paywallHint && /^false$/i.test(metaFree)) paywallHint = 'isAccessibleForFree=false';

              const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => s.textContent.trim()).filter(s => s.length > 0);

              // 页面类型只按 URL 段判定。不能因为文章页里嵌了个相关视频播放器（<video> /
              // og:type=video）就把它判成视频，否则会大面积误杀正常文章。
              const pathSeg = (new URL(location.href).pathname
                      .replace(/^\\/\\d{4}\\/\\d{2}\\/\\d{2}\\//, '').split('/')[0] || '').toLowerCase();
              const videoSeg = ['videos', 'video', 'live-news', 'live', 'gallery', 'audio', 'podcasts'];
              const kind = videoSeg.includes(pathSeg) ? 'video' : 'article';
              const ogType = meta('meta[property="og:type"]');
              const hasVideoEl = !!document.querySelector('video, [data-testid*="video"], ' +
                                   '[class*="VideoPlayer"], [class*="video-player"]');
              const duration = meta('meta[property="video:duration"]') || meta('meta[name="duration"]') || '';
              const thumbnail = meta('meta[property="og:image"]') || '';

              return JSON.stringify({
                title: title, url: location.href, time: time, modified: modified,
                author: author, section: section, description: description,
                paragraphs: body, paywallHint: paywallHint, lds: lds,
                kind: kind, duration: duration, thumbnail: thumbnail,
                videoSignal: /video/i.test(ogType) || hasVideoEl
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
                blocked: /Access Denied|Forbidden|Just a moment|Checking your browser|Are you a robot|Pardon Our Interruption|Request unsuccessful|Incident ID|Reference #|403|Something went wrong|Please enable JavaScript/i.test(txt),
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
                        .setLocale("en-US").setTimezoneId("America/New_York")
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
        System.out.println("[提示] 直连可能 403 / 被 WAF 拦，强烈建议 --cdp 连手动开的 Chrome。");

        BrowserContext ctx;
        try {
            ctx = pw.chromium().launchPersistentContext(
                    Paths.get(cfg.profileDir).toAbsolutePath(), opt);
        } catch (PlaywrightException e) {
            throw new IllegalStateException("启动本地 Chrome 失败：" + e.getMessage()
                    + "。可换 --profile 目录、用 --chrome-path 指定路径，或 --cdp 连手动开的 Chrome。", e);
        }
        try {
            crawl(ctx.pages().isEmpty() ? ctx.newPage() : ctx.pages().get(0), cfg);
        } finally {
            ctx.close();
        }
    }

    /** 模式 B：CDP 连接手动启动的原生 Chrome（最稳） */
    private static void attach(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 建议先在该 Chrome 里手动打开一次 https://www.cnn.com/ 确认可见。");
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

    private static void crawl(Page page, Config cfg) throws Exception {
        if (cfg.cdpUrl.isBlank()) page.addInitScript(STEALTH_JS);
        page.setDefaultTimeout(30_000);

        List<String> warnings = new ArrayList<>();
        List<String> wafHits = Collections.synchronizedList(new ArrayList<>());
        page.onResponse(resp -> {
            try {
                String server = resp.headers().getOrDefault("server", "");
                if (server.toLowerCase().contains("akamai")) {
                    wafHits.add("Server: " + server + " <- " + resp.url());
                }
            } catch (Exception ignored) {}
        });

        // 预热：先落首页让 session cookie 成熟，再直接命中高价值 URL 容易被判冷启动
        if (cfg.warmup) {
            System.out.println("[预热] 先访问 CNN 首页…");
            try {
                page.navigate("https://www.cnn.com/", new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(1800, 3400));
            } catch (PlaywrightException e) {
                System.out.println("[预热] 首页访问异常（继续）：" + e.getMessage());
            }
        }

        Set<String> links = new LinkedHashSet<>();
        Set<String> nav = new LinkedHashSet<>();
        List<String> dropped = new ArrayList<>();
        Set<String> seenPage = new LinkedHashSet<>();
        int opened = 0;

        // 1) sitemap 入口（最稳，一次拿大量文章 URL）
        if (cfg.source.equals("sitemap") || cfg.source.equals("both") || cfg.source.equals("all")) {
            List<String> sm = new ArrayList<>(SITEMAPS);
            if (!cfg.sitemapMonth.isBlank()) {
                sm.add(0, "https://www.cnn.com/sitemap/article/" + cfg.sitemapMonth);
            }
            for (String u : sm) {
                if (opened >= cfg.pages) break;
                try {
                    open(page, u, cfg, warnings);
                    opened++;
                    seenPage.add(u);
                    int before = links.size();
                    links.addAll(extractUrlsFromSitemap(page));
                    System.out.printf("[sitemap] %s -> +%d 条，累计 %d 条%n",
                            u, links.size() - before, links.size());
                } catch (Exception e) {
                    System.out.println("[sitemap] 失败 " + u + " : " + e.getMessage());
                    warnings.add("sitemap 失败 " + u);
                }
                politeSleep();
            }
        }

        // 2) Google News 补充（rss.cnn.com 自 2024-08 停更）。
        //    注意该 feed 的 <link> 是 news.google.com 跳转地址，不是 cnn.com 文章 URL，
        //    这里只当作「近期有没有新稿」的线索，不产出可直接抓取的链接；
        //    真要链接请用 --source=both 走官方 sitemap + 频道页。
        if (cfg.source.equals("rss") || cfg.source.equals("all")) {
            try {
                open(page, GOOGLE_NEWS_RSS, cfg, warnings);
                opened++;
                String xml = page.content();
                int items = countMatches(xml, "<item>");
                System.out.printf("[RSS] Google News site:cnn.com 近期条目 %d 条（跳转链接，"
                        + "仅作线索；直接 URL 请用 --source=both）%n", items);
            } catch (Exception e) {
                System.out.println("[RSS] 获取失败（不影响主流程）：" + e.getMessage());
            }
        }

        // 3) 频道页：收集 + 滚动 + 跟进栏目
        if (cfg.source.equals("channel") || cfg.source.equals("both") || cfg.source.equals("all")) {
            List<String> seeds = cfg.seedsRaw.isBlank() ? SEEDS : cfg.seeds;
            for (String seed : seeds) {
                if (opened >= cfg.pages) break;
                try {
                    open(page, seed, cfg, warnings);
                    opened++;
                    seenPage.add(seed);
                    harvest(page, cfg, links, nav, dropped, 0, 1 + cfg.scroll);
                    System.out.printf("[频道页] %s -> 累计 %d 条%n", seed, links.size());
                    for (int i = 1; i <= cfg.scroll; i++) {
                        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight * 0.6)");
                        page.waitForTimeout(ThreadLocalRandom.current().nextInt(500, 900));
                        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)");
                        page.waitForTimeout(ThreadLocalRandom.current().nextInt(900, 1700));
                        harvest(page, cfg, links, nav, dropped, i, 1 + cfg.scroll);
                    }
                } catch (Exception e) {
                    System.out.println("[频道页] 失败 " + seed + " : " + e.getMessage());
                    warnings.add("频道页失败 " + seed);
                }
                politeSleep();
            }

            int followed = 0;
            for (String n : new ArrayList<>(nav)) {
                if (followed >= cfg.follow || opened >= cfg.pages) break;
                if (!seenPage.add(n)) continue;
                try {
                    open(page, n, cfg, warnings);
                    opened++;
                    harvest(page, cfg, links, nav, dropped, 0, 1);
                    // 月度归档 / news.xml 页同时也抽一遍文章 URL
                    links.addAll(extractUrlsFromSitemap(page));
                    followed++;
                    System.out.printf("[栏目/归档 %d/%d] %s -> 累计 %d 条%n",
                            followed, cfg.follow, n, links.size());
                    politeSleep();
                } catch (Exception e) {
                    System.out.println("[栏目/归档] 跳过 " + n + " : " + e.getMessage());
                }
            }
        }

        // 统一分流：默认只留文章页；--include-video=true 才额外保留视频页（仅元数据，不下载文件）。
        // 这一步专门堵住「sitemap 推荐位里的 /live/ /video/ 卡片混进文章结果」。
        Set<String> articleLinks = new LinkedHashSet<>();
        Set<String> videoLinks = new LinkedHashSet<>();
        int droppedByKind = 0;
        for (String u : links) {
            if (isCnnArticleUrl(u)) articleLinks.add(u);
            else if (cfg.includeVideo && looksLikeCnnVideoUrl(u)) videoLinks.add(u);
            else droppedByKind++;
        }
        links = articleLinks;
        if (droppedByKind > 0 || !videoLinks.isEmpty()) {
            System.out.printf("[过滤] 排除非文章链接 %d 条；保留视频页 %d 条（--include-video=%s）%n",
                    droppedByKind, videoLinks.size(), cfg.includeVideo);
        }

        if (!dropped.isEmpty()) {
            System.out.println("[诊断] 被丢弃的链接样本（前 6 条）：");
            dropped.stream().limit(6).forEach(d -> System.out.println("    " + d));
        }
        if (!wafHits.isEmpty()) {
            System.out.println("[诊断] 命中 WAF 响应头：" + wafHits.get(0));
        }
        System.out.printf("[收集] 候选文章 %d 条 + 视频 %d 条（--limit=%d，--pages=%d）%n",
                links.size(), videoLinks.size(), cfg.limit, cfg.pages);
        if (links.isEmpty()) {
            System.out.println("[提示] 0 条。优先排查：1) 首页/文章页是否被 WAF 拦（看 [警告]）；"
                    + "2) --cdp 连手动开的 Chrome；3) --source=both 开 sitemap；"
                    + "4) --sitemap-month=2026/11 指定当月归档。");
        }

        // 4) 逐篇抽正文（文章默认全抓；视频页仅在 --include-video=true 时抓元数据）
        List<String> targets = new ArrayList<>(links);
        targets.addAll(videoLinks);
        List<Map<String, Object>> news = new ArrayList<>();
        for (String url : targets) {
            if (news.size() >= cfg.limit) break;
            if (opened >= cfg.pages) break;
            if (!seenPage.add(url)) continue;
            boolean expectVideo = looksLikeCnnVideoUrl(url);
            if (expectVideo && !cfg.includeVideo) {
                System.out.println("跳过（视频页，未开 --include-video）: " + url);
                continue;
            }
            try {
                open(page, url, cfg, warnings);
                opened++;
                String raw = (String) page.evaluate(EXTRACT_JS);
                Map<String, Object> d = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});

                @SuppressWarnings("unchecked") List<String> paras = (List<String>) d.get("paragraphs");
                @SuppressWarnings("unchecked") List<String> lds = (List<String>) d.get("lds");
                Map<String, String> ld = readNewsArticleLd(lds);
                String hint = firstNonBlank((String) d.get("paywallHint"), "");
                boolean ldPaywalled = "false".equalsIgnoreCase(ld.getOrDefault("isAccessibleForFree", ""));

                String kind = firstNonBlank((String) d.get("kind"), expectVideo ? "video" : "article");
                boolean isVideo = "video".equalsIgnoreCase(kind);
                // 双保险：只要页面被判成视频且没开开关，就丢掉，绝不混进文章结果
                if (isVideo && !cfg.includeVideo) {
                    System.out.println("跳过（页面被识别为视频）: " + url);
                    continue;
                }

                // DOM 没抽到段落时用 JSON-LD 的 articleBody 兜底拆段
                if ((paras == null || paras.isEmpty()) && !ld.getOrDefault("articleBody", "").isBlank()) {
                    paras = splitParagraphs(ld.get("articleBody"));
                }
                // 视频页通常没有正文段落，用 meta description 兜一段；最多留 3 段，避免收进推荐位文字
                if (isVideo && (paras == null || paras.isEmpty())) {
                    String desc = firstNonBlank(ld.get("description"), (String) d.get("description"));
                    if (!desc.isBlank()) paras = new ArrayList<>(List.of(desc));
                }
                if (isVideo && paras != null && paras.size() > 3) {
                    paras = new ArrayList<>(paras.subList(0, 3));
                }
                boolean paywalled = !hint.isBlank() || ldPaywalled;
                if (cfg.skipPaywall && paywalled) {
                    System.out.println("跳过（订阅墙）: " + url);
                    continue;
                }
                if (paras == null || paras.isEmpty()) {
                    System.out.println("跳过（无正文/被拦）: " + url);
                    continue;
                }

                StringBuilder content = new StringBuilder();
                for (String p : paras) content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);

                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title", firstNonBlank(ld.get("headline"), (String) d.get("title")));
                item.put("url", firstNonBlank((String) d.get("url"), url));
                item.put("publishedAt", firstNonBlank(ld.get("datePublished"), (String) d.get("time")));
                item.put("modifiedAt", firstNonBlank(ld.get("dateModified"), (String) d.get("modified")));
                item.put("author", firstNonBlank(ld.get("author"), (String) d.get("author")));
                item.put("section", firstNonBlank(ld.get("articleSection"), (String) d.get("section")));
                item.put("description", firstNonBlank(ld.get("description"), (String) d.get("description")));
                item.put("keywords", ld.getOrDefault("keywords", ""));
                item.put("image", ld.getOrDefault("image", ""));
                item.put("access", paywalled ? "subscriber-only" : "free");
                item.put("paywall", paywalled);
                item.put("truncated", paywalled);   // true 表示 content 只是公开可见部分，不是全文
                item.put("paywallHint", hint);
                item.put("kind", isVideo ? "video" : "article");
                item.put("paragraphs", paras);
                item.put("content", content.toString());
                if (isVideo) {
                    // 注意：只存页面 URL 与可见元数据，不解析、不下载 mp4/m3u8 媒体文件
                    item.put("duration", firstNonBlank((String) d.get("duration"), ""));
                    item.put("thumbnail", firstNonBlank((String) d.get("thumbnail"), ld.get("image")));
                    item.put("mediaPageUrl", url);
                    item.put("mediaDownloaded", false);
                }
                item.put("source", "CNN");
                item.put("capturedAt", CAPTURED_AT);
                news.add(item);

                System.out.printf("[%d/%d]%s%s %s%n", news.size(), cfg.limit,
                        isVideo ? "[视频·仅元数据] " : " ",
                        paywalled ? "[订阅墙·仅公开段] " : " ", item.get("title"));
            } catch (Exception e) {
                System.out.println("抓取失败 " + url + " -> " + e.getMessage());
            }
            politeSleep();
        }

        MAPPER.writerWithDefaultPrettyPrinter()
                .writeValue(Paths.get(cfg.outFile).toFile(), news);
        System.out.println("完成：" + cfg.outFile + "，共 " + news.size() + " 篇"
                + "（实际打开 " + opened + " 页）");
        if (!warnings.isEmpty()) {
            System.out.println("[提醒] " + warnings.size() + " 处拦截/失败，前 3 条：");
            warnings.stream().limit(3).forEach(w -> System.out.println("    " + w));
        }
    }

    /** 频道页收集：把 COLLECT_JS 返回的 urls / nav / dropped 合进总集合 */
    @SuppressWarnings("unchecked")
    private static void harvest(Page page, Config cfg, Set<String> links, Set<String> nav,
                                List<String> dropped, int round, int total) throws Exception {
        String raw = (String) page.evaluate(COLLECT_JS, cfg.includeVideo);
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

    /**
     * sitemap / RSS / 月归档页抽文章 URL。
     * Chrome 打开 XML 会套一层 viewer，page.content() 返回 viewer HTML、<loc> 可能被转义成文本，
     * 所以源码与 document.body.innerText 双路抽；用「日期路径」正则而非依赖 <loc> 标签。
     */
    private static Set<String> extractUrlsFromSitemap(Page page) {
        Set<String> out = new LinkedHashSet<>();
        String all = "";
        try { all = page.content(); } catch (PlaywrightException ignored) {}
        try { all += "\n" + page.evaluate("() => document.body ? document.body.innerText : ''"); }
        catch (PlaywrightException ignored) {}
        Matcher m = CNN_ARTICLE.matcher(all.replace("&amp;", "&"));
        while (m.find()) {
            String u = m.group()
                    .replaceAll("[.\\s,;)\\]]+$", "")       // 清掉正则带上的尾随标点
                    .replace("http://", "https://");
            if (u.contains("?") || u.contains("#")) continue;
            // 子域统一还原到 www.cnn.com
            u = u.replaceAll("^https://(?:edition|us|amp)\\.(?:www\\.)?cnn\\.com",
                    "https://www.cnn.com");
            if (u.startsWith("https://amp.cnn.com")) {
                u = "https://www.cnn.com" + u.substring("https://amp.cnn.com".length());
            }
            if (u.contains("/amp/")) u = u.replace("/amp/", "/");
            // 老文章保留 index.html。这里只收「文章」和「视频」两类日期路径，
            // 其余（calculators / interactive / collections…）一律挡掉；
            // 是否真的抓视频由 --include-video 在 crawl() 里统一分流决定。
            if (!isCnnArticleUrl(u) && !looksLikeCnnVideoUrl(u)) continue;
            out.add(u);
        }
        return out;
    }

    /** 导航 + WAF 拦截检测；超时只警告不抛，避免整批收集 0 条 */
    private static void open(Page page, String url, Config cfg, List<String> warnings) {
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
                System.out.println("[警告] 建议 --cdp 连手动 Chrome、保持 --headless=false、"
                        + "国内加 --proxy；该页仍会尝试抽取。");
                warnings.add(url + " -> " + state.substring(0, Math.min(110, state.length())));
            }
            if (cfg.manual && (blocked || len < 100) && i == 6) {
                System.out.println("[人工] 请在 Chrome 窗口里刷新/完成验证，看到 CNN 页面后"
                        + "回控制台按【回车】继续…");
                try { System.in.read(); } catch (java.io.IOException ignored) {}
                return;
            }
            page.waitForTimeout(1000);
        }
        System.out.println("[警告] " + cfg.waitSeconds + "s 内未达预期渲染，仍尝试抽取：" + url);
    }

    private static int intField(String json, String key) {
        try {
            Matcher m = Pattern.compile("\"" + key + "\":(\\d+)").matcher(json);
            return m.find() ? Integer.parseInt(m.group(1)) : 0;
        } catch (Exception e) { return 0; }
    }

    private static int countMatches(String s, String needle) {
        if (s == null || needle == null || needle.isEmpty()) return 0;
        int n = 0, i = 0;
        while ((i = s.indexOf(needle, i)) >= 0) { n++; i += needle.length(); }
        return n;
    }

    /** 从 JSON-LD 中找 NewsArticle / Article，取元数据、articleBody、isAccessibleForFree */
    private static Map<String, String> readNewsArticleLd(List<String> lds) {
        if (lds == null) return Map.of();
        Set<String> types = Set.of("NewsArticle", "Article", "BlogPosting", "ReportageNewsArticle",
                "AnalysisNewsArticle", "OpinionNewsArticle", "BackgroundNewsArticle",
                "ReviewNewsArticle", "LiveBlogPosting", "TechArticle", "Report");
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
                    m.put("articleSection", flattenLd(cur.get("articleSection")));
                    m.put("keywords", flattenLd(cur.get("keywords")));
                    m.put("author", authorOf(cur.get("author")));
                    m.put("image", imageOf(cur.get("image")));
                    JsonNode free = cur.get("isAccessibleForFree");
                    if (free != null) m.put("isAccessibleForFree", free.asText(""));
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

    /** articleBody 兜底拆段：去标签 + 按行 / 句末切 */
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
            for (String seg : t.split("(?<=[.!?])\\s+")) {
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
        try { Thread.sleep(ThreadLocalRandom.current().nextInt(1700, 3400)); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    private static class Config {
        int limit = 20;
        int pages = 80;                 // 本次最多打开多少页（sitemap + 频道 + 内容页合计）
        int waitSeconds = 25;
        int scroll = 2;
        int follow = 5;
        boolean headless = false;
        boolean warmup = true;
        boolean manual = false;
        boolean skipPaywall = false;    // true 则整篇跳过订阅墙文章
        boolean includeVideo = false;   // true 才收视频/直播页元数据；默认只抓文章，绝不下载媒体文件
        String source = "both";         // channel | sitemap | rss | both | all
        String sitemapMonth = "";       // 如 2026/11，追加到 sitemap 列表最前
        String seedsRaw = "";
        List<String> seeds = SEEDS;
        String profileDir = "./.pw-profile-cnn";
        String channel = "chrome";
        String chromePath = "";
        String cdpUrl = "";
        String proxy = "";
        String outFile = "cnn-news.json";

        static Config parse(String[] a) {
            Config c = new Config();
            for (String s : a) {
                if (s.startsWith("--limit=")) c.limit = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--pages=")) c.pages = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--wait=")) c.waitSeconds = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--scroll=")) c.scroll = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--follow=")) c.follow = Integer.parseInt(s.split("=", 2)[1]);
                else if (s.startsWith("--headless=")) c.headless = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--warmup=")) c.warmup = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--manual=")) c.manual = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--skip-paywall=")) c.skipPaywall = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--include-video=")) c.includeVideo = Boolean.parseBoolean(s.split("=", 2)[1]);
                else if (s.startsWith("--source=")) c.source = s.split("=", 2)[1].toLowerCase(Locale.ROOT);
                else if (s.startsWith("--sitemap-month=")) c.sitemapMonth = s.split("=", 2)[1];
                else if (s.startsWith("--seeds=")) c.seedsRaw = s.split("=", 2)[1];
                else if (s.startsWith("--profile=")) c.profileDir = s.split("=", 2)[1];
                else if (s.startsWith("--channel=")) c.channel = s.split("=", 2)[1];
                else if (s.startsWith("--chrome-path=")) c.chromePath = s.split("=", 2)[1];
                else if (s.startsWith("--cdp=")) c.cdpUrl = s.split("=", 2)[1];
                else if (s.startsWith("--proxy=")) c.proxy = s.split("=", 2)[1];
                else if (s.startsWith("--out=")) c.outFile = s.split("=", 2)[1];
                else if (s.equals("--help")) {
                    System.out.println("""
                            参数（JDK 17 / Playwright 驱动本地 Chrome / CNN 新闻）：
                              --limit=20                    最多抓取篇数
                              --pages=80                    本次最多打开多少页
                              --source=channel|sitemap|rss|both|all
                                                            默认 both（官方 sitemap + 频道页）
                              --sitemap-month=2026/11       追加官方月度归档页到 sitemap 列表最前
                              --seeds=url1,url2             自定义频道种子页
                              --scroll=2 / --follow=5       列表页滚动 / 栏目跟进数
                              --wait=25                     每页等待渲染秒数
                              --warmup=true                 先访问首页让 session cookie 成熟
                              --skip-paywall=false          true 则整篇跳过订阅墙文章
                              --include-video=false         默认 false：视频/直播页一律排除；
                                                            true 才收其元数据（不下载 mp4/m3u8）
                              --headless=false|true         默认 false
                              --cdp=http://127.0.0.1:9222  连接手动开的 Chrome（推荐）
                              --channel=chrome|chromium / --chrome-path=...
                              --profile=./.pw-profile-cnn   独立持久化 profile
                              --proxy=... / --manual=true   代理 / 拦截时人工兜底
                              --out=cnn-news.json           输出文件
                              --help

                            口径：CNN robots.txt 对 77 个 AI 爬虫 UA 明确 Disallow: /，
                            本程序只做个人学习用的小范围索引，不商用、不分发、不做训练语料。
                            订阅墙内容只取公开可见段落并打标 truncated=true，绝不绕过。
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
