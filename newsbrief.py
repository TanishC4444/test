"""
newsbrief.py - RSS scraper + distilbart summarizer
===================================================

Storage
    store.json          — rolling 30-day window, fast access
    data/YYYY-Www.json  — permanent weekly archive, never deleted

Model
    sshleifer/distilbart-cnn-6-6 — fast CPU inference, ~300MB
"""

import json, os, time, argparse, signal, subprocess
from datetime import datetime, timezone, timedelta

# ── Constants ──────────────────────────────────────────────────────────────────

STORE_PATH     = os.environ.get("NEWSBRIEF_STORE", "store.json")
RETENTION_DAYS = 30
DEFAULT_FEED   = "https://feeds.bbci.co.uk/news/world/rss.xml"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

FEEDS = [
    # ── BBC ───────────────────────────────────────────────────────────────────
    ("https://feeds.bbci.co.uk/news/world/rss.xml",                    "BBC World"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml",               "BBC Tech"),
    ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",  "BBC Science"),
    ("https://feeds.bbci.co.uk/news/health/rss.xml",                   "BBC Health"),
    ("https://feeds.bbci.co.uk/news/business/rss.xml",                 "BBC Business"),
    ("https://feeds.bbci.co.uk/news/politics/rss.xml",                 "BBC Politics"),
    ("https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",   "BBC Entertainment"),
    ("https://feeds.bbci.co.uk/news/education/rss.xml",                "BBC Education"),

    # ── NYT ───────────────────────────────────────────────────────────────────
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml",         "NYT World"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/US.xml",            "NYT US"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",      "NYT Politics"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",    "NYT Tech"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",       "NYT Science"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Health.xml",        "NYT Health"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",      "NYT Business"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Climate.xml",       "NYT Climate"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",       "NYT Economy"),

    # ── NPR ───────────────────────────────────────────────────────────────────
    ("https://feeds.npr.org/1001/rss.xml",                             "NPR News"),
    ("https://feeds.npr.org/1014/rss.xml",                             "NPR Politics"),
    ("https://feeds.npr.org/1019/rss.xml",                             "NPR Science"),
    ("https://feeds.npr.org/1128/rss.xml",                             "NPR Business"),
    ("https://feeds.npr.org/1039/rss.xml",                             "NPR Health"),
    ("https://feeds.npr.org/1025/rss.xml",                             "NPR World"),

    # ── Reuters ───────────────────────────────────────────────────────────────
    ("https://feeds.reuters.com/reuters/topNews",                       "Reuters Top"),
    ("https://feeds.reuters.com/reuters/businessNews",                  "Reuters Business"),
    ("https://feeds.reuters.com/reuters/technologyNews",                "Reuters Tech"),
    ("https://feeds.reuters.com/reuters/scienceNews",                   "Reuters Science"),
    ("https://feeds.reuters.com/reuters/healthNews",                    "Reuters Health"),
    ("https://feeds.reuters.com/reuters/worldNews",                     "Reuters World"),
    ("https://feeds.reuters.com/reuters/politicsNews",                  "Reuters Politics"),
    ("https://feeds.reuters.com/reuters/environment",                   "Reuters Environment"),

    # ── AP News ───────────────────────────────────────────────────────────────
    ("https://rsshub.app/apnews/topics/ap-top-news",                   "AP Top News"),
    ("https://rsshub.app/apnews/topics/politics",                      "AP Politics"),
    ("https://rsshub.app/apnews/topics/technology",                    "AP Tech"),
    ("https://rsshub.app/apnews/topics/science",                       "AP Science"),
    ("https://rsshub.app/apnews/topics/health",                        "AP Health"),
    ("https://rsshub.app/apnews/topics/business",                      "AP Business"),
    ("https://rsshub.app/apnews/topics/world-news",                    "AP World"),
    ("https://rsshub.app/apnews/topics/us-news",                       "AP US"),

    # ── Guardian ──────────────────────────────────────────────────────────────
    ("https://www.theguardian.com/world/rss",                          "Guardian World"),
    ("https://www.theguardian.com/us-news/rss",                        "Guardian US"),
    ("https://www.theguardian.com/technology/rss",                     "Guardian Tech"),
    ("https://www.theguardian.com/science/rss",                        "Guardian Science"),
    ("https://www.theguardian.com/environment/rss",                    "Guardian Environment"),
    ("https://www.theguardian.com/business/rss",                       "Guardian Business"),
    ("https://www.theguardian.com/politics/rss",                       "Guardian Politics"),
    ("https://www.theguardian.com/society/health/rss",                 "Guardian Health"),
    ("https://www.theguardian.com/education/rss",                      "Guardian Education"),

    # ── Al Jazeera ────────────────────────────────────────────────────────────
    ("https://www.aljazeera.com/xml/rss/all.xml",                      "Al Jazeera"),
    ("https://www.aljazeera.com/xml/rss/economy.xml",                  "Al Jazeera Economy"),

    # ── CNN ───────────────────────────────────────────────────────────────────
    ("http://rss.cnn.com/rss/edition.rss",                             "CNN World"),
    ("http://rss.cnn.com/rss/edition_us.rss",                          "CNN US"),
    ("http://rss.cnn.com/rss/edition_technology.rss",                  "CNN Tech"),
    ("http://rss.cnn.com/rss/edition_health.rss",                      "CNN Health"),
    ("http://rss.cnn.com/rss/edition_business.rss",                    "CNN Business"),
    ("http://rss.cnn.com/rss/edition_space.rss",                       "CNN Space"),

    # ── Washington Post ───────────────────────────────────────────────────────
    ("https://feeds.washingtonpost.com/rss/world",                     "WashPost World"),
    ("https://feeds.washingtonpost.com/rss/politics",                  "WashPost Politics"),
    ("https://feeds.washingtonpost.com/rss/business",                  "WashPost Business"),
    ("https://feeds.washingtonpost.com/rss/technology",                "WashPost Tech"),
    ("https://feeds.washingtonpost.com/rss/national",                  "WashPost National"),
    ("https://feeds.washingtonpost.com/rss/health-science",            "WashPost Health"),

    # ── Politico ──────────────────────────────────────────────────────────────
    ("https://www.politico.com/rss/politics08.xml",                    "Politico Politics"),
    ("https://www.politico.com/rss/congress.xml",                      "Politico Congress"),
    ("https://www.politico.com/rss/economy.xml",                       "Politico Economy"),
    ("https://www.politico.com/rss/healthcare.xml",                    "Politico Health"),
    ("https://www.politico.com/rss/defense.xml",                       "Politico Defense"),

    # ── Tech ──────────────────────────────────────────────────────────────────
    ("https://techcrunch.com/feed/",                                   "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml",                         "The Verge"),
    ("https://www.wired.com/feed/rss",                                 "Wired"),
    ("https://feeds.arstechnica.com/arstechnica/index",                "Ars Technica"),
    ("https://www.technologyreview.com/feed/",                         "MIT Tech Review"),
    ("https://venturebeat.com/feed/",                                  "VentureBeat"),
    ("https://www.zdnet.com/news/rss.xml",                             "ZDNet"),
    ("https://feeds.feedburner.com/TheHackersNews",                    "Hacker News THN"),
    ("https://www.darkreading.com/rss.xml",                            "Dark Reading"),

    # ── Science ───────────────────────────────────────────────────────────────
    ("https://www.sciencedaily.com/rss/all.xml",                       "Science Daily"),
    ("https://www.newscientist.com/feed/home/",                        "New Scientist"),
    ("https://feeds.nature.com/nature/rss/current",                    "Nature"),
    ("https://www.science.org/rss/news_current.xml",                   "Science Magazine"),
    ("https://phys.org/rss-feed/",                                     "Phys.org"),
    ("https://www.scientificamerican.com/feed/",                       "Scientific American"),
    ("https://feeds.feedburner.com/IeeeSpectrum",                      "IEEE Spectrum"),
    ("https://spacenews.com/feed/",                                    "Space News"),
    ("https://www.space.com/feeds/all",                                "Space.com"),
    ("https://earthobservatory.nasa.gov/feeds/earth-observatory.rss",  "NASA Earth Observatory"),

    # ── Health / Medicine ─────────────────────────────────────────────────────
    ("https://www.statnews.com/feed/",                                 "STAT News"),
    ("https://www.medscape.com/cx/rssfeeds/2678.xml",                  "Medscape"),
    ("https://jamanetwork.com/rss/site_3/67.xml",                      "JAMA"),
    ("https://www.bmj.com/rss/current.xml",                            "BMJ"),
    ("https://www.medicalnewstoday.com/rss",                           "Medical News Today"),
    ("https://www.healio.com/rss/cardiology",                          "Healio Cardiology"),
    ("https://www.nejm.org/action/showFeed?type=etoc&feed=rss",        "NEJM"),

    # ── Business / Finance ────────────────────────────────────────────────────
    ("https://feeds.bloomberg.com/markets/news.rss",                   "Bloomberg Markets"),
    ("https://feeds.bloomberg.com/technology/news.rss",                "Bloomberg Tech"),
    ("https://www.ft.com/rss/home",                                    "Financial Times"),
    ("https://feeds.wsj.com/wsj/xml/rss/3_7085.xml",                  "WSJ World"),
    ("https://feeds.wsj.com/wsj/xml/rss/3_7014.xml",                  "WSJ US Business"),
    ("https://feeds.wsj.com/wsj/xml/rss/3_7455.xml",                  "WSJ Tech"),
    ("https://www.forbes.com/real-time/feed2/",                        "Forbes"),
    ("https://fortune.com/feed/",                                      "Fortune"),
    ("https://www.cnbc.com/id/100003114/device/rss/rss.html",         "CNBC Top News"),
    ("https://www.cnbc.com/id/10001147/device/rss/rss.html",          "CNBC Finance"),
    ("https://www.cnbc.com/id/19854910/device/rss/rss.html",          "CNBC Tech"),

    # ── Environment / Climate ─────────────────────────────────────────────────
    ("https://insideclimatenews.org/feed/",                            "Inside Climate News"),
    ("https://www.climatecentral.org/feed",                            "Climate Central"),
    ("https://e360.yale.edu/feed",                                     "Yale E360"),
    ("https://grist.org/feed/",                                        "Grist"),
    ("https://www.carbonbrief.org/feed",                               "Carbon Brief"),

    # ── Policy / Foreign Affairs ──────────────────────────────────────────────
    ("https://foreignpolicy.com/feed/",                                "Foreign Policy"),
    ("https://www.foreignaffairs.com/rss.xml",                         "Foreign Affairs"),
    ("https://thehill.com/rss/syndicator/19110",                       "The Hill"),
    ("https://www.brookings.edu/feed/",                                "Brookings"),
    ("https://carnegieendowment.org/feed/rss",                         "Carnegie Endowment"),
    ("https://www.cfr.org/rss.xml",                                    "Council on Foreign Relations"),

    # ── International ─────────────────────────────────────────────────────────
    ("https://www.france24.com/en/rss",                                "France 24"),
    ("https://www.dw.com/rss/rss.xml",                                 "Deutsche Welle"),
    ("https://feeds.skynews.com/feeds/rss/world.xml",                  "Sky News World"),
    ("https://www.abc.net.au/news/feed/51120/rss.xml",                 "ABC Australia"),
    ("https://timesofindia.indiatimes.com/rssfeedstopstories.cms",     "Times of India"),
    ("https://japantimes.co.jp/feed/",                                 "Japan Times"),
    ("https://www.scmp.com/rss/91/feed",                               "South China Morning Post"),
    ("https://rss.dw.com/rdf/rss-en-all",                              "DW All"),
]

SELECTORS = {
    "bbc":              'article p, [data-component="text-block"] p',
    "npr":              'article p, .storytext p, #storytext p',
    "cnn":              'article p, .article__content p, .zn-body__paragraph',
    "apnews":           'article p, .RichTextStoryBody p',
    "reuters":          'article p, [class*="article-body"] p, [class*="ArticleBody"] p',
    "theguardian":      'article p, .article-body-commercial-selector p, .dcr-1eu7p3o p',
    "nytimes":          'article p, section[name="articleBody"] p',
    "washingtonpost":   'article p, .article-body p, [data-qa="article-body"] p',
    "aljazeera":        'article p, .wysiwyg p, .article-p-wrapper p',
    "techcrunch":       'article p, .article-content p, .entry-content p',
    "theverge":         'article p, .duet--article--article-body-component p',
    "wired":            'article p, .body__inner-container p',
    "arstechnica":      'article p, .article-content p',
    "politico":         'article p, .story-text p, .article-body p',
    "thehill":          'article p, .field-items p, .article__text p',
    "sciencedaily":     'article p, #text p, .lead, #first p',
    "newscientist":     'article p, .article-body p',
    "economist":        'article p, .article__body p, [data-body-type="figure"] p',
    "foreignpolicy":    'article p, .post-content-main p',
    "foreignaffairs":   'article p, .article-body p',
    "technologyreview": 'article p, .content-body p',
    "venturebeat":      'article p, .article-content p',
    "zdnet":            'article p, .c-articleBody p',
    "nature":           'article p, .article__body p, [data-component="article-container"] p',
    "science.org":      'article p, .article__body p',
    "phys.org":         'article p, .article-main p',
    "scientificamerican": 'article p, .article-text p',
    "spectrum.ieee":    'article p, .article-body p',
    "spacenews":        'article p, .entry-content p',
    "space.com":        'article p, #article-body p',
    "statnews":         'article p, .entry-content p',
    "medicalnewstoday": 'article p, .css-1jnqwms p',
    "bloomberg":        'article p, .body-content p, [class*="body__content"] p',
    "ft.com":           'article p, .article__content-body p',
    "wsj.com":          'article p, [class*="article-wrap"] p',
    "forbes":           'article p, .article-body p, .body-container p',
    "fortune":          'article p, .article-body p',
    "cnbc":             'article p, .ArticleBody-articleBody p, .RenderKeyPoints-list li',
    "france24":         'article p, .t-content__body p',
    "dw.com":           'article p, .longText p',
    "skynews":          'article p, .sdc-article-body p',
    "abc.net.au":       'article p, [class*="article"] p',
    "timesofindia":     'article p, .article_content p, ._3WlLe p',
    "japantimes":       'article p, .article-body p',
    "scmp":             'article p, .article-body p, [class*="article__body"] p',
    "brookings":        'article p, .post-body p',
    "cfr.org":          'article p, .body-content p',
    "insideclimatenews": 'article p, .entry-content p',
    "carbonbrief":      'article p, .post-content p',
    "grist":            'article p, .post-content p',
    "darkreading":      'article p, .article-body p',
    "thehackernews":    'article p, .post-content p, .articlebody p',
}
FALLBACK = "article p, main p, .content p, p"

EXTRACT_TEXT_JS = """
(selector) => {
    let els = document.querySelectorAll(selector);
    if (els.length > 0)
        return Array.from(els)
            .map(e => e.innerText.trim())
            .filter(t => t.length > 20)
            .join('\\n\\n');
    return Array.from(document.querySelectorAll('p'))
        .map(p => p.innerText.trim())
        .filter(t => t.length > 20)
        .join('\\n\\n');
}
"""

EXTRACT_META_JS = """
() => {
    const m = n => {
        const e = document.querySelector(
            `meta[name="${n}"],meta[property="${n}"],meta[itemprop="${n}"]`
        );
        return e ? e.content || '' : '';
    };
    return {
        author: m('author') || m('article:author') || m('og:author') || '',
        date:   m('article:published_time') || m('datePublished') || m('pubdate') || ''
    };
}
"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def week_key():
    y, w, _ = datetime.now(timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"

def sel_for(url: str) -> str:
    low = url.lower()
    for k, v in SELECTORS.items():
        if k in low:
            return v
    return FALLBACK

def git_commit():
    """Commit and push store.json and data/ to GitHub."""
    try:
        subprocess.run(["git", "stash"],                              check=False, capture_output=True)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"],check=False, capture_output=True)
        subprocess.run(["git", "stash", "pop"],                       check=False, capture_output=True)
        subprocess.run(["git", "add", "store.json", "data/"],         check=False, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m",
             f"data: {datetime.now(timezone.utc).isoformat()} [skip ci]"],
            check=False, capture_output=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "push"], check=False, capture_output=True)
            print("[GIT] Pushed.")
        else:
            print("[GIT] Nothing new to commit.")
    except Exception as e:
        print(f"[GIT] Error: {e}")

# ── Store ──────────────────────────────────────────────────────────────────────

class Store:
    def __init__(self, path: str = STORE_PATH):
        self.path  = path
        self._data: dict[str, dict] = {}
        self._load()
        self._purge()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self._data = json.load(f).get("articles", {})
        except Exception as e:
            print(f"[Store] Could not read store: {e}. Starting fresh.")

    def _purge(self):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        before = len(self._data)
        self._data = {u: a for u, a in self._data.items()
                      if a.get("retrieved_at", "9999") >= cutoff}
        n = before - len(self._data)
        if n:
            print(f"[Store] Trimmed {n} articles (kept in weekly files).")
        self._save()

    def _save(self):
        # Write store.json atomically
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"articles": self._data}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

        # Write/update weekly archive
        week   = week_key()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        weekly = {u: a for u, a in self._data.items()
                  if a.get("retrieved_at", "") >= cutoff}
        os.makedirs("data", exist_ok=True)
        wpath  = f"data/{week}.json"
        wtmp   = wpath + ".tmp"

        existing = {}
        if os.path.exists(wpath):
            try:
                with open(wpath, "r", encoding="utf-8") as f:
                    existing = json.load(f).get("articles", {})
            except Exception:
                pass
        merged = {**existing, **weekly}

        with open(wtmp, "w", encoding="utf-8") as f:
            json.dump({"week": week, "count": len(merged), "articles": merged},
                      f, indent=2, ensure_ascii=False)
        os.replace(wtmp, wpath)

    def upsert(self, art: dict):
        url = art.get("link", "")
        if not url:
            return
        existing       = self._data.get(url, {})
        merged         = {**existing, **art}
        if "summary" not in art and "summary" in existing:
            merged["summary"] = existing["summary"]
        self._data[url] = merged
        self._save()

    def set_summary(self, url: str, summary: str):
        if url in self._data:
            self._data[url]["summary"] = summary
            self._save()

    def has(self, url: str) -> bool:
        return url in self._data and bool(self._data[url].get("text"))

    def unsummarized(self) -> list:
        return [a for a in self._data.values()
                if not a.get("summary") and a.get("text")]

    def all(self) -> list:
        arts = list(self._data.values())
        arts.sort(key=lambda a: a.get("retrieved_at", ""), reverse=True)
        return arts

# ── NewsBrief ──────────────────────────────────────────────────────────────────

class NewsBrief:
    def __init__(self, store_path: str = STORE_PATH):
        self.store     = Store(store_path)
        self._articles = []

    def rss(self, feed_url: str, source: str = "", max_articles: int = 0, delay: float = 0.3) -> list:
        try:
            import feedparser
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ImportError(f"Missing: {e}. pip install feedparser playwright && playwright install chromium")

        src = source or feed_url
        print(f"\n[RSS] {src}")

        try:
            entries = feedparser.parse(feed_url).entries
        except Exception as e:
            print(f"[RSS] Parse error: {e}")
            return []

        if max_articles > 0:
            entries = entries[:max_articles]

        new_entries = [e for e in entries if not self.store.has(e.get("link", ""))]
        if not new_entries:
            print(f"[RSS] All {len(entries)} already in store.")
            return []

        print(f"[RSS] {len(new_entries)} new / {len(entries)} total")
        new_arts = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx     = browser.new_context(user_agent=UA)
            page    = ctx.new_page()

            for i, entry in enumerate(new_entries, 1):
                title = entry.get("title", "Untitled")
                link  = entry.get("link",  "")
                if not link:
                    continue

                print(f"  [{i}/{len(new_entries)}] {title[:60]}", end=" ", flush=True)

                art = {
                    "source":       src,
                    "link":         link,
                    "title":        title,
                    "date":         entry.get("published", entry.get("updated", "")),
                    "author":       entry.get("author", ""),
                    "text":         "",
                    "summary":      None,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                }

                try:
                    page.goto(link, timeout=20_000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2_000)
                    text = (page.evaluate(EXTRACT_TEXT_JS, sel_for(link)) or "").strip()
                    meta = page.evaluate(EXTRACT_META_JS) or {}
                    if not art["author"]: art["author"] = meta.get("author", "")
                    if not art["date"]:   art["date"]   = meta.get("date", "")
                    art["text"] = text
                    wc = len(text.split())
                    print(f"{'⚠' if wc < 10 else '✓'}  ({wc:,} words)")
                except Exception as e:
                    print(f"✗  {e}")

                new_arts.append(art)
                self.store.upsert(art)
                time.sleep(delay)

            ctx.close()
            browser.close()

        self._articles = new_arts
        print(f"[RSS] Done — {len(new_arts)} scraped.\n")
        return new_arts

    def rss_all(self, feeds: list = FEEDS) -> list:
        all_arts = []
        for url, name in feeds:
            all_arts.extend(self.rss(url, source=name))
        return all_arts

    def summarize(self, articles: list = None, deadline: float = None) -> list:
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
            import torch
        except ImportError:
            raise ImportError("pip install transformers torch")

        arts = articles if articles is not None else self.store.unsummarized()
        if not arts:
            print("[Summarize] Nothing to summarize.")
            return []

        MODEL = "sshleifer/distilbart-cnn-6-6"
        print(f"[Summarize] Loading {MODEL}...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL)
        model     = AutoModelForSeq2SeqLM.from_pretrained(MODEL)
        model.eval()
        print(f"[Summarize] Ready. {len(arts)} articles.\n")

        for i, art in enumerate(arts, 1):
            # Stop early if deadline approaching
            if deadline and time.time() > deadline:
                print(f"[Summarize] Deadline reached at article {i}/{len(arts)} — stopping.")
                break

            text = art.get("text", "")
            if not text:
                continue

            print(f"  [{i}/{len(arts)}] {art.get('title','')[:60]}", end=" ", flush=True)
            t0 = time.time()

            try:
                import torch
                words  = text.split()
                chunks = [" ".join(words[j:j+900]) for j in range(0, len(words), 900)]

                chunk_sums = []
                for chunk in chunks:
                    inputs = tokenizer(chunk, return_tensors="pt",
                                       max_length=1024, truncation=True)
                    with torch.no_grad():
                        ids = model.generate(
                            inputs["input_ids"],
                            max_length=130, min_length=30,
                            num_beams=1, early_stopping=True,
                        )
                    chunk_sums.append(tokenizer.decode(ids[0], skip_special_tokens=True))

                if len(chunk_sums) > 1:
                    combined = " ".join(chunk_sums)
                    inputs   = tokenizer(combined, return_tensors="pt",
                                         max_length=1024, truncation=True)
                    with torch.no_grad():
                        ids = model.generate(inputs["input_ids"], max_length=130,
                                             min_length=30, num_beams=1)
                    summary = tokenizer.decode(ids[0], skip_special_tokens=True)
                else:
                    summary = chunk_sums[0]

                art["summary"] = summary
                self.store.set_summary(art["link"], summary)
                print(f"✓  ({time.time()-t0:.1f}s)")

            except Exception as e:
                print(f"✗  {e}")

        print("\n[Summarize] Complete.\n")
        return arts

    def get(self, source: str = "") -> list:
        arts = self.store.all()
        if source:
            arts = [a for a in arts if a.get("source") == source]
        return arts


# ── CLI / Loop ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="NewsBrief — RSS + distilbart summarizer")
    p.add_argument("feed_url",        nargs="?", default="")
    p.add_argument("--source",  "-s", type=str,   default="")
    p.add_argument("--max",     "-m", type=int,   default=0)
    p.add_argument("--all",           action="store_true")
    p.add_argument("--store",         type=str,   default=STORE_PATH)
    p.add_argument("--no-summarize",  action="store_true")
    p.add_argument("--loop",          action="store_true", help="Run continuously until --hours elapses")
    p.add_argument("--hours",         type=float, default=5.75, help="Total runtime in hours")
    args = p.parse_args()

    START    = time.time()
    DEADLINE = START + (args.hours * 3600)
    SLEEP    = 300   # 5 min between iterations
    BUFFER   = 600   # 10 min safety buffer before deadline

    # Always commit on any signal so no work is lost
    def handle_signal(sig, frame):
        print(f"\n[SIGNAL] Caught signal {sig} — committing before exit.")
        git_commit()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT,  handle_signal)

    nb        = NewsBrief(store_path=args.store)
    iteration = 1

    while True:
        remaining = DEADLINE - time.time()
        print(f"\n{'═'*55}")
        print(f" Iteration {iteration}  |  {remaining/60:.1f} min remaining")
        print(f"{'═'*55}\n")

        if remaining < BUFFER:
            print("[LOOP] Under 10 min left — committing and exiting.")
            git_commit()
            break

        # Scrape
        if args.all:
            nb.rss_all()
        elif args.feed_url:
            nb.rss(args.feed_url, source=args.source, max_articles=args.max)
        else:
            print("Pass a feed URL or --all.")
            raise SystemExit(1)

        # Summarize — stop if deadline is within buffer
        if not args.no_summarize:
            nb.summarize(deadline=DEADLINE - BUFFER)

        # Commit after every iteration — no work lost if killed after this
        git_commit()

        iteration += 1
        remaining  = DEADLINE - time.time()

        if not args.loop:
            break

        if remaining < SLEEP + BUFFER:
            print("[LOOP] Not enough time for another full run — exiting.")
            break

        print(f"[LOOP] Sleeping 5 min... ({remaining/60:.1f} min remaining)")
        time.sleep(SLEEP)

    print(f"\n[DONE] Finished {iteration-1} iteration(s).")