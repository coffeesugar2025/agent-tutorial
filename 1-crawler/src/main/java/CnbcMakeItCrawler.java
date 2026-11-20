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
 * CNBC「Make It」频道文章抓取。
 * 技术栈与 PeopleNewsCrawler / Job51Crawler 一致：JDK 17 + Playwright 驱动【本地 Chrome】+ Jackson，无 Jsoup。
 * <p>
 * 站点要点：
 * - 频道页 https://www.cnbc.com/make-it/，文章 URL 自带 make-it
 * （/make-it/YYYY/MM/DD/slug.html、/amp/make-it/... 或 slug 含 cnbc-make-it）
 * - 正文容器 div.ArticleBody-articleBody，内部是一组 .group 里的 <p>；JSON-LD 为 NewsArticle
 * - CNBC 前置 Akamai Bot Manager（_abck / bm_sz / sensor_data），校验 TLS 指纹、JS 遥测、
 * 行为与 session 连续性；无头浏览器命中率很低。
 * => 最稳走 --cdp 连手动启动的原生 Chrome，并做「首页 → 频道页」的 session 预热。
 * <p>
 * 链接来源：
 * --source=channel（默认）频道页 DOM；--source=rss 官方 Make It RSS；--source=both 两者合并
 * 注意：CNBC 的 robots.txt 对 search.cnbc.com 的 RSS 有限制，是否使用请自行判断。
 * <p>
 * 运行（IntelliJ Main class 改成 CnbcMakeItCrawler）：
 * --limit=8 --cdp=http://127.0.0.1:9222
 * --source=both --scroll=3 --loadmore=2 --limit=20
 */
public class CnbcMakeItCrawler {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    /**
     * 正文段落格式：与前两个主类一致，每段开头 \t、结尾 \n
     */
    private static final String PARA_PREFIX = "\t";
    private static final String PARA_SUFFIX = "\n";

    /**
     * 频道种子页；可用 --seeds= 覆盖（逗号分隔）
     */
    private static final List<String> SEEDS = List.of(
            "https://www.cnbc.com/make-it/"
    );

    /**
     * CNBC 官方 Make It RSS（id=103395579），--source=rss|both 时作为补充入口
     */
    private static final String RSS_URL =
            "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=103395579";

    private static final Pattern CNBC_ARTICLE_URL = Pattern.compile(
            "https://(?:www\\.)?cnbc\\.com/[^\"<>\\s#'\"]+?\\.html");

    private static final String STEALTH_JS = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """;

    /**
     * 频道页收集文章链接。
     * 三路来源：a[href]、卡片 data-*、内嵌 JSON / 页面源码里的绝对 URL。
     * 硬约束：URL 必须包含 make-it；AMP 前缀还原；query/hash 清掉。
     * 返回 {urls, dropped}：dropped 是「被哪条规则丢弃」的样本，用于诊断是否误杀。
     */
    private static final String COLLECT_JS = """
            (needMakeIt) => {
              const out = new Set();
              const nav = new Set();             // 栏目 Tab / 分页链接，交给 Java 侧继续跟进
              const droppedMakeIt = new Set();   // 被硬约束丢掉的，诊断时优先展示
              const droppedOther = new Set();
              const bad = ['/video/', '/newsletter/', '/select/', '/pro/', '/id/', '/about/',
                           '/privacy/', '/terms/', '/sitemap', '/search', '/audio/', '/watch/',
                           '/livestream', '/topic/', '/tag/', '/author/', '/page/', '/press/'];
            
              const norm = (raw) => {
                try {
                  let href = (raw || '').trim().replace(/&amp;/g, '&');
                  if (!href || href.startsWith('#') || /^javascript:/i.test(href)) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  const h = u.hostname.toLowerCase();
                  if (!(h === 'cnbc.com' || h.endsWith('.cnbc.com'))) return;
                  // AMP 版没有 .ArticleBody-articleBody，去掉 /amp 前缀还原标准文章页
                  let p = u.pathname;
                  if (p.toLowerCase().startsWith('/amp/')) p = p.substring(4);
                  p = p.replace(/\\/+$/, '');
                  if (!/\\.html?$/i.test(p)) {
                    // /make-it 开头的非文章页是栏目 Tab / 分页，collectNav 已收，不算「被丢弃的文章」
                    if (!p.toLowerCase().startsWith('/make-it')) {
                      droppedOther.add('非.html      ' + href.slice(0, 110));
                    }
                    return;
                  }
                  if (/pardon|access-denied|error/i.test(p)) { droppedOther.add('拦截页       ' + href.slice(0, 110)); return; }
                  if (bad.some(b => p.toLowerCase().startsWith(b))) { droppedOther.add('栏目页       ' + href.slice(0, 110)); return; }
                  // 统一 host，清掉 ?forYou=true / #fragment，避免同文多链接
                  const finalUrl = 'https://www.cnbc.com' + p;
                  if (needMakeIt && !finalUrl.toLowerCase().includes('make-it')) {
                    droppedMakeIt.add('不含make-it  ' + finalUrl.slice(0, 110));
                    return;
                  }
                  out.add(finalUrl);
                } catch (e) {}
              };
            
              // 栏目 Tab / 分页：同域、/make-it 开头、非 .html 文章页，保留 query（分页参数）
              const collectNav = (href) => {
                try {
                  if (!href) return;
                  const u = new URL(href, location.href);
                  if (u.protocol !== 'https:') return;
                  const h = u.hostname.toLowerCase();
                  if (!(h === 'cnbc.com' || h.endsWith('.cnbc.com'))) return;
                  const p = u.pathname.toLowerCase();
                  if (!p.startsWith('/make-it')) return;
                  if (/\\.html?$/i.test(p)) return;
                  if (bad.some(b => p.startsWith(b))) return;
                  nav.add(u.href.split('#')[0]);
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
              const re = /https?:\\/\\/(?:www\\.)?cnbc\\.com\\/[^"'\\s<>]+?\\.html/gi;
              for (const src of sources) {
                let m;
                while ((m = re.exec(src)) !== null) norm(m[0]);
              }
              return JSON.stringify({
                urls: [...out],
                dropped: [...droppedMakeIt, ...droppedOther].slice(0, 40),
                nav: [...nav].slice(0, 40)
              });
            }
            """;

    /**
     * 文章页抽取：正文只取 p 标签，带 Akamai/CNBC 噪声过滤，并收集 JSON-LD
     */
    private static final String EXTRACT_JS = """
            () => {
              const clean = s => (s || '').replace(/\\s+/g, ' ').trim();
              const title = clean(document.querySelector('h1.ArticleHeader-headline, h1[class*="headline"], h1')?.innerText)
                          || clean(document.title);
              const time = document.querySelector('time[data-testid="published-timestamp"][datetime]')?.getAttribute('datetime')
                        || document.querySelector('time[datetime]')?.getAttribute('datetime')
                        || document.querySelector('meta[property="article:published_time"]')?.getAttribute('content')
                        || '';
              const modified = document.querySelector('meta[property="article:modified_time"]')?.getAttribute('content')
                            || document.querySelector('time[data-testid="lastpublished-timestamp"][datetime]')?.getAttribute('datetime')
                            || '';
              const author = clean(document.querySelector('meta[name="author"]')?.getAttribute('content'))
                          || clean(document.querySelector('[class*="byline"], [rel="author"]')?.innerText);
              const section = clean(document.querySelector('meta[property="article:section"]')?.getAttribute('content'));
            
              // 正文容器：CNBC 为 .ArticleBody-articleBody（内部 .group 包 p）；多组兜底防改版
              const NOISE_SEL = [
                    '[class*="ad-"]', '[class*="-ad"]', '[class*="Ad-"]', '[data-ad]', '[id^="ad-"]',
                    'aside', 'footer', 'nav', '[class*="newsletter"]', '[class*="related"]',
                    '[class*="recirc"]', '[class*="promo"]', '[class*="subscribe"]',
                    '[class*="disclaimer"]', '[data-testid*="Related"]'
                  ].join(', ');
              const NOISE_TEXT = /^(Sign up now|Subscribe|Get this delivered|Watch:|Read more|More from|Related|Advertisement|Sponsored|Correction:|Editor's note|Click here|Download the CNBC)/i;
            
              const pick = (sel, minLen) => [...document.querySelectorAll(sel)]
                    .filter(p => !p.closest(NOISE_SEL))
                    .map(p => clean(p.innerText))
                    .filter(t => t.length > minLen && !NOISE_TEXT.test(t));
            
              // 只取 p 标签
              let body = pick('.ArticleBody-articleBody p, [class*="ArticleBody"] p, ' +
                              '[data-testid*="ArticleBody"] p, article p, main p', 25);
              if (body.length < 2) body = pick('p', 40);
            
              const seen = new Set();
              body = body.filter(t => { if (seen.has(t)) return false; seen.add(t); return true; });
            
              const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => s.textContent.trim()).filter(s => s.length > 0);
            
              return JSON.stringify({
                title: title, url: location.href, time: time, modified: modified,
                author: author, section: section, paragraphs: body, lds: lds
              });
            }
            """;

    /**
     * 页面状态：用于判断 Akamai 拦截页 / 空页 / 正常渲染
     */
    private static final String PAGE_STATE_JS = """
            () => {
              const txt = (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').trim();
              return JSON.stringify({
                ready: document.readyState === 'complete',
                title: document.title.slice(0, 90),
                textLen: txt.length,
                blocked: /Pardon Our Interruption|Access Denied|You don't have permission|Request unsuccessful|Incident ID|Reference #/i.test(txt),
                head: txt.slice(0, 140)
              });
            }
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
                        .setLocale("en-US")
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
     * 模式 B：CDP 连接手动启动的原生 Chrome（Akamai 下最稳）
     */
    private static void attachToRunningChrome(Playwright pw, Config cfg) throws Exception {
        System.out.println("[驱动] CDP 连接已运行的本地 Chrome：" + cfg.cdpUrl);
        System.out.println("[驱动] 建议先在该 Chrome 里手动打开一次 https://www.cnbc.com/make-it/ "
                + "确认能看到文章列表（必要时完成一次人机验证）。");
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

        // Akamai 痕迹诊断：响应头 + cookie
        List<String> akamaiHits = Collections.synchronizedList(new ArrayList<>());
        page.onResponse(resp -> {
            try {
                String server = resp.headers().getOrDefault("server", "");
                if (server.toLowerCase().contains("akamai")) {
                    akamaiHits.add("Server: " + server + " <- " + resp.url());
                }
            } catch (Exception ignored) {
            }
        });

        // Session 预热：Akamai 会给「直接命中高价值 URL 的全新 session」打低分，
        // 先落首页、停留一会儿再进频道页，让 _abck / bm_sz 成熟。
        if (cfg.warmup) {
            System.out.println("[预热] 先访问 CNBC 首页，让 Akamai session cookie 成熟…");
            try {
                page.navigate("https://www.cnbc.com/", new Page.NavigateOptions()
                        .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(60_000));
                page.waitForTimeout(ThreadLocalRandom.current().nextInt(1800, 3600));
            } catch (PlaywrightException e) {
                System.out.println("[预热] 首页访问异常（继续）：" + e.getMessage());
            }
        }

        // 1) 收集文章链接：边滚边收，避免懒加载/虚拟列表把前面卡片换掉
        Set<String> links = new LinkedHashSet<>();
        List<String> droppedSamples = new ArrayList<>();
        Set<String> navLinks = new LinkedHashSet<>();
        if (!cfg.source.equalsIgnoreCase("rss")) {
            for (String seed : cfg.seeds) {
                try {
                    open(page, seed, cfg, akamaiHits);   // 现在只警告、不抛异常
                    harvestChannel(page, cfg, links, droppedSamples, navLinks);
                    System.out.printf("[频道页] %s -> 累计 %d 条%n", seed, links.size());
                } catch (Exception e) {
                    System.out.println("[频道页] 失败 " + seed + " : " + e.getMessage());
                    // 即使上面整段挂了，也再抽一次，避免整批 0 条
                    try {
                        collectOnce(page, cfg, links, droppedSamples, navLinks, -1);
                    } catch (Exception ignored) {
                    }
                }
                politeSleep();
                if (links.size() >= cfg.limit * 3) break;
            }

            // 1b) 频道页有分页(1 2 3 4 5)和栏目 Tab(Success/Money/Work/Life)，
            //     自动跟进若干个，否则只能拿到首屏那几张卡片
            List<String> toFollow = new ArrayList<>(navLinks);
            int followed = 0;
            for (String nav : toFollow) {
                if (followed >= cfg.follow || links.size() >= cfg.limit * 3) break;
                if (cfg.seeds.contains(nav) || nav.equals(SEEDS.get(0))) continue;
                try {
                    open(page, nav, cfg, akamaiHits);
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

        // 诊断：把频道页里被规则丢弃的链接样本打出来，一眼看清是不是硬约束误杀
        if (!droppedSamples.isEmpty()) {
            System.out.println("[诊断] 频道页里被丢弃的链接样本（前 10 条）：");
            droppedSamples.stream().limit(10).forEach(d -> System.out.println("    " + d));
        }

        // 硬约束兜底：无论 DOM / RSS / 自定义种子页，最终待抓链接一律必须含 make-it
        int beforeFilter = links.size();
        Set<String> filtered = new LinkedHashSet<>();
        for (String u : links) {
            if (cfg.requireMakeIt && !u.toLowerCase(Locale.ROOT).contains("make-it")) continue;
            filtered.add(u);
        }
        links = filtered;
        if (beforeFilter != links.size()) {
            System.out.printf("[过滤] 排除 %d 条不含 make-it 的链接，保留 %d 条%n",
                    beforeFilter - links.size(), links.size());
        }
        System.out.println("[收集] 候选文章 " + links.size() + " 条（--require-makeit="
                + cfg.requireMakeIt + "，--limit=" + cfg.limit + "）");
        if (links.isEmpty()) {
            System.out.println("[提示] 过滤后 0 条。Make It 文章 URL 本身就带 make-it"
                    + "（/make-it/YYYY/MM/DD/... 或 slug 含 cnbc-make-it），"
                    + "所以 0 条基本不是过滤误杀，请依次排查："
                    + "1) 频道页是否被 Akamai 拦/空白（看上面的 [诊断] 行）；"
                    + "2) 链接是否还没懒加载出来（加大 --scroll / --loadmore）；"
                    + "3) 用 --source=both 补官方 RSS。");
        }

        // 2) 逐篇抓正文
        List<Map<String, Object>> news = new ArrayList<>();
        for (String url : links) {
            if (news.size() >= cfg.limit) break;
            // 双保险：抓之前再校验一次，杜绝任何来源绕过过滤
            if (cfg.requireMakeIt && !url.toLowerCase(Locale.ROOT).contains("make-it")) {
                System.out.println("跳过（链接不含 make-it）: " + url);
                continue;
            }
            try {
                open(page, url, cfg, akamaiHits);
                String raw = (String) page.evaluate(EXTRACT_JS);
                Map<String, Object> d = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {
                });

                @SuppressWarnings("unchecked")
                List<String> paras = (List<String>) d.get("paragraphs");
                @SuppressWarnings("unchecked")
                List<String> lds = (List<String>) d.get("lds");
                Map<String, String> ld = readNewsArticleLd(lds);

                // 段落兜底：DOM 没抽到就用 JSON-LD 的 articleBody
                if ((paras == null || paras.isEmpty()) && !ld.getOrDefault("articleBody", "").isBlank()) {
                    paras = splitParagraphs(ld.get("articleBody"));
                }
                boolean isArticle = !ld.isEmpty() || (paras != null && paras.size() >= 2);
                if (!isArticle) {
                    System.out.println("跳过（非文章/被拦）: " + url);
                    continue;
                }

                StringBuilder content = new StringBuilder();
                if (paras != null) {
                    for (String p : paras) content.append(PARA_PREFIX).append(p).append(PARA_SUFFIX);
                }

                Map<String, Object> item = new LinkedHashMap<>();
                item.put("title", firstNonBlank(ld.get("headline"), (String) d.get("title")));
                item.put("url", d.get("url"));
                item.put("publishedAt", firstNonBlank(ld.get("datePublished"), (String) d.get("time")));
                item.put("modifiedAt", firstNonBlank(ld.get("dateModified"), (String) d.get("modified")));
                item.put("author", firstNonBlank(ld.get("author"), (String) d.get("author")));
                item.put("section", firstNonBlank(ld.get("articleSection"), (String) d.get("section")));
                item.put("description", ld.getOrDefault("description", ""));
                item.put("keywords", ld.getOrDefault("keywords", ""));
                item.put("image", ld.getOrDefault("image", ""));
                item.put("paragraphs", paras == null ? List.of() : paras);
                item.put("content", content.toString());
                news.add(item);

                System.out.printf("[%d/%d] %s%n", news.size(), cfg.limit, item.get("title"));
            } catch (Exception e) {
                System.out.println("抓取失败 " + url + " -> " + e.getMessage());
            }
            politeSleep();
        }

//        MAPPER.writerWithDefaultPrettyPrinter()
//                .writeValue(Paths.get(cfg.outFile).toFile(), news);
        int index = 0;
        List<List<Map<String, Object>>> lists = CommonStaticUtils.splitList(news, 10);
        for (List<Map<String, Object>> list : lists) {
            ++index;
            CommonStaticUtils.write("cnbc-make-it", list, index);
        }
        System.out.println("完成：" + cfg.outFile + "，共 " + news.size() + " 篇");
    }



    /**
     * 频道页：首屏先收一次，每滚一次收一次，每点一次 Load More 再收一次
     */
    private static void harvestChannel(Page page, Config cfg, Set<String> links,
                                       List<String> dropped, Set<String> navLinks) throws Exception {
        int total = 1 + cfg.scroll + cfg.loadMore;
        collectOnce(page, cfg, links, dropped, navLinks, 0, total);
        for (int i = 1; i <= cfg.scroll; i++) {
            scrollBottom(page);
            collectOnce(page, cfg, links, dropped, navLinks, i, total);
        }
        for (int j = 1; j <= cfg.loadMore; j++) {
            if (!clickLoadMore(page)) break;
            collectOnce(page, cfg, links, dropped, navLinks, cfg.scroll + j, total);
        }
    }

    /**
     * 单轮收集：evaluate 一次 COLLECT_JS，合并 urls / dropped / nav
     */
    @SuppressWarnings("unchecked")
    private static void collectOnce(Page page, Config cfg, Set<String> links,
                                    List<String> dropped, Set<String> navLinks,
                                    int round, int total) throws Exception {
        String raw = (String) page.evaluate(COLLECT_JS, cfg.requireMakeIt);
        Map<String, Object> res = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {
        });
        List<String> got = (List<String>) res.get("urls");
        List<String> drop = (List<String>) res.get("dropped");
        List<String> nav = (List<String>) res.get("nav");
        int before = links.size();
        if (got != null) links.addAll(got);
        if (drop != null) {
            for (String d : drop) if (!dropped.contains(d)) dropped.add(d);
        }
        if (nav != null) navLinks.addAll(nav);
        String tag = round < 0 ? "兜底" : (round + 1) + "/" + total;
        System.out.printf("[收集] 第 %s 轮：+%d 条，累计 %d 条%n",
                tag, links.size() - before, links.size());
    }

    /**
     * crawl 里 catch 分支的简化调用
     */
    private static void collectOnce(Page page, Config cfg, Set<String> links,
                                    List<String> dropped, Set<String> navLinks,
                                    int round) throws Exception {
        collectOnce(page, cfg, links, dropped, navLinks, round, 1);
    }

    private static void scrollBottom(Page page) {
        try {
            // 先滚到中部再到底部，比一步到底更容易触发懒加载
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight * 0.6)");
            page.waitForTimeout(ThreadLocalRandom.current().nextInt(500, 1000));
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)");
            page.waitForTimeout(ThreadLocalRandom.current().nextInt(1200, 2200));
        } catch (PlaywrightException ignored) {
        }
    }

    private static boolean clickLoadMore(Page page) {
        String[] sels = {"button:has-text('Load More')", "button:has-text('More')",
                "[class*='loadMore']", "[class*='LoadMore']", "[data-testid*='load-more']"};
        for (String sel : sels) {
            try {
                Locator l = page.locator(sel).last();
                if (l.count() > 0 && l.isVisible() && l.isEnabled()) {
                    l.click(new Locator.ClickOptions().setTimeout(4000));
                    page.waitForTimeout(ThreadLocalRandom.current().nextInt(1500, 2600));
                    return true;
                }
            } catch (PlaywrightException ignored) {
            }
        }
        return false;
    }

    /**
     * RSS 补充入口：Playwright 打开官方 feed，从 XML/渲染文本里正则抽 .html 文章 URL
     */
    private static List<String> collectFromRss(Page page, Config cfg) {
        System.out.println("[RSS] 打开官方 Make It feed 补充链接…");
        try {
            page.navigate(RSS_URL, new Page.NavigateOptions()
                    .setWaitUntil(WaitUntilState.DOMCONTENTLOADED).setTimeout(45_000));
            String xml = page.content();
            Matcher m = CNBC_ARTICLE_URL.matcher(xml);
            Set<String> out = new LinkedHashSet<>();
            int rssTotal = 0, rssDropped = 0;
            while (m.find()) {
                rssTotal++;
                String u = m.group().replace("http://", "https://");
                if (u.contains("pardon") || u.contains("access-denied")) {
                    rssDropped++;
                    continue;
                }
                if (cfg.requireMakeIt && !u.toLowerCase(Locale.ROOT).contains("make-it")) {
                    rssDropped++;
                    continue;
                }
                out.add(u);
            }
            // Chrome 的 XML 视图有时会把 link 渲染成带 &amp; 的 href，再兜一层
            Matcher m2 = Pattern.compile("https://(?:www\\.)?cnbc\\.com/[^\"<>\\s]+?\\.html").matcher(xml);
            while (m2.find()) {
                rssTotal++;
                String u = m2.group().replace("&amp;", "&").replace("http://", "https://");
                if (u.toLowerCase(Locale.ROOT).contains("access-denied")) {
                    rssDropped++;
                    continue;
                }
                if (cfg.requireMakeIt && !u.toLowerCase(Locale.ROOT).contains("make-it")) {
                    rssDropped++;
                    continue;
                }
                out.add(u);
            }
            System.out.printf("[RSS] 抽到 %d 条，排除 %d 条（不含 make-it / 拦截页），保留 %d 条%n",
                    rssTotal, rssDropped, out.size());
            return new ArrayList<>(out);
        } catch (Exception e) {
            System.out.println("[RSS] 获取失败（不影响主流程）：" + e.getMessage());
            return List.of();
        }
    }

    /**
     * 导航 + Akamai 拦截检测 + 人工兜底
     */
    private static void open(Page page, String url, Config cfg, List<String> akamaiHits) {
        page.navigate(url, new Page.NavigateOptions()
                .setWaitUntil(WaitUntilState.DOMCONTENTLOADED)
                .setTimeout(60_000));

        for (int i = 0; i < cfg.waitSeconds; i++) {
            String state = "";
            try {
                state = (String) page.evaluate(PAGE_STATE_JS);
            } catch (PlaywrightException ignored) {
            }
            boolean blocked = state.contains("\"blocked\":true");
            // 频道首页常常没有 h1/article/main（截图那种卡片网格就是纯 div+section），
            // 所以不再用 DOM 标签当硬性放行条件，只看 ready + 非拦截 + 有实质文本。
            boolean ok = state.contains("\"ready\":true") && !blocked;

            // 从 textLen 判断是不是空白页
            int textLen = 0;
            try {
                Matcher mm = Pattern.compile("\"textLen\":(\\d+)").matcher(state);
                if (mm.find()) textLen = Integer.parseInt(mm.group(1));
            } catch (Exception ignored) {
            }
            if (ok && textLen > 200) return;

            if ((blocked || textLen < 120) && i == 3) {
                System.out.println("[诊断] 页面疑似被 Akamai 拦截或空白：" + state);
                if (!akamaiHits.isEmpty()) {
                    System.out.println("[诊断] 命中 Akamai 响应头：" + akamaiHits.get(0));
                }
                try {
                    Set<String> cookieNames = new HashSet<>();
                    for (com.microsoft.playwright.options.Cookie c : page.context().cookies()) {
                        cookieNames.add(c.name);
                    }
                    System.out.println("[诊断] 现有 cookie 含 _abck=" + cookieNames.contains("_abck")
                            + " bm_sz=" + cookieNames.contains("bm_sz")
                            + "（这两个是 Akamai Bot Manager 的签名 cookie）");
                } catch (Exception ignored) {
                }
                System.out.println("[诊断] 建议：--cdp 连手动开的 Chrome、保持 --headless=false、"
                        + "开启 --warmup=true，或在该 Chrome 里手动完成一次验证。");
            }
            if (cfg.manual && (blocked || textLen < 120) && i == 6) {
                System.out.println("[人工] 请在 Chrome 窗口里刷新/完成验证，看到 CNBC 正文后"
                        + "回控制台按【回车】继续…");
                try {
                    System.in.read();
                } catch (java.io.IOException ignored) {
                }
                return;
            }
            page.waitForTimeout(1000);
        }
        // 只警告、不抛：频道页判定没达标也照样让调用方去抽链接，避免整批 0 条
        System.out.println("[警告] " + cfg.waitSeconds + "s 内未达到预期渲染，仍尝试抽取：" + url);
        System.out.println("[警告] 若持续如此：先手动 Chrome 确认可访问（国内可能需要 --proxy），"
                + "Akamai 对无头敏感，优先 --cdp + --warmup=true。");
    }

    /**
     * 从 JSON-LD 中找 NewsArticle / Article / BlogPosting 等，取元数据与 articleBody
     */
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
                    if (cur.isArray()) {
                        cur.forEach(q::add);
                        continue;
                    }
                    if (!cur.isObject()) continue;

                    JsonNode t = cur.get("@type");
                    Set<String> ts = new HashSet<>();
                    if (t != null) {
                        if (t.isArray()) t.forEach(x -> ts.add(x.asText("")));
                        else ts.add(t.asText(""));
                    }
                    boolean isArticle = ts.stream().anyMatch(types::contains);
                    if (!isArticle && ts.stream().noneMatch(x -> x.contains("Article"))) {
                        // 继续往子结构找（@graph 等）
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
            n.forEach(x -> {
                String s = authorOf(x);
                if (!s.isBlank()) xs.add(s);
            });
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
            n.forEach(x -> {
                String s = flattenLd(x);
                if (!s.isBlank()) xs.add(s);
            });
            return String.join(", ", xs);
        }
        return "";
    }

    /**
     * articleBody 兜底拆段：去标签 + 按行 / 中文句号切
     */
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
        try {
            Thread.sleep(ThreadLocalRandom.current().nextInt(1800, 3800));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static class Config {
        int limit = 800;
        int waitSeconds = 30;
        int scroll = 2;                 // 频道页滚动次数
        int loadMore = 0;               // 点 Load More 次数
        int follow = 3;                 // 自动跟进几个栏目 Tab / 分页页
        boolean headless = false;
        boolean warmup = true;          // 首页 → 频道页 session 预热
        boolean manual = false;
        boolean requireMakeIt = true;   // 硬约束：所有待抓文章 URL 必须包含 make-it
        String source = "channel";      // channel | rss | both
        String seedsRaw = "";
        List<String> seeds = SEEDS;
        String profileDir = "./.pw-profile-cnbc";
        String channel = "chrome";
        String chromePath = "";
        String cdpUrl = "";
        String proxy = "";
        String outFile = "cnbc-makeit.json";

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
                else if (s.startsWith("--require-makeit="))
                    c.requireMakeIt = Boolean.parseBoolean(s.split("=", 2)[1]);
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
                            参数（JDK 17 / Playwright 驱动本地 Chrome / CNBC Make It）：
                              --limit=8                    最多抓取篇数
                              --wait=30                    每页等待渲染的最长秒数
                              --scroll=2                   频道页滚动次数（懒加载）
                              --loadmore=0                 点 Load More 按钮次数
                              --follow=3                   自动跟进几个栏目 Tab / 分页页（0=不跟进）
                              --source=channel|rss|both    链接来源，默认频道页；rss 走官方 Make It feed
                              --seeds=url1,url2            自定义频道种子页
                              --require-makeit=true|false  默认 true：所有待抓文章 URL 必须含 make-it
                              --warmup=true               先访问首页让 Akamai session cookie 成熟
                              --headless=false|true        默认 false，Akamai 对无头敏感
                              --cdp=http://127.0.0.1:9222 连接手动开的 Chrome（推荐）
                              --channel=chrome|chromium    默认本机 Chrome stable
                              --chrome-path=...            显式指定 Chrome 可执行文件
                              --profile=./.pw-profile-cnbc 独立持久化 profile
                              --proxy=http://127.0.0.1:7890 可选代理（国内访问 CNBC 常需要）
                              --manual=true                遇拦截页时停住，人工处理后回车
                              --out=cnbc-makeit.json       输出文件
                              --help                       打印本说明
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
