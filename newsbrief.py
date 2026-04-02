"""
newsbrief.py - RSS scraper + LED summarizer
===========================================

Storage
    store.json          — rolling 30-day window, fast access
    data/YYYY-Www.json  — permanent weekly archive, never deleted

Model
    allenai/led-large-16384 — 16384 token context, minimal chunking needed
"""

import json, os, time, argparse
from datetime import datetime, timezone, timedelta

# ── Constants ──────────────────────────────────────────────────────────────────

STORE_PATH     = os.environ.get("NEWSBRIEF_STORE", "store.json")
RETENTION_DAYS = 30   # store.json rolling window; weekly files keep everything
DEFAULT_FEED   = "https://feeds.bbci.co.uk/news/world/rss.xml"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

FEEDS = [
    ("https://feeds.bbci.co.uk/news/world/rss.xml",          "BBC World"),
    ("https://feeds.bbci.co.uk/news/technology/rss.xml",      "BBC Tech"),
    ("https://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "BBC Science"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml","NYT World"),
    ("https://feeds.npr.org/1001/rss.xml",                    "NPR News"),
    ("https://feeds.reuters.com/reuters/topNews",             "Reuters"),
]

SELECTORS = {
    "bbc":          'article p, [data-component="text-block"] p',
    "npr":          'article p, .storytext p, #storytext p',
    "cnn":          'article p, .article__content p',
    "apnews":       'article p, .RichTextStoryBody p',
    "reuters":      'article p, [class*="article-body"] p',
    "guardian":     'article p, .article-body-commercial-selector p',
    "nytimes":      'article p, section[name="articleBody"] p',
    "washingtonpost": 'article p, .article-body p',
    "aljazeera":    'article p, .wysiwyg p',
    "techcrunch":   'article p, .article-content p',
    "theverge":     'article p, .duet--article--article-body-component p',
    "wired":        'article p, .body__inner-container p',
    "arstechnica":  'article p, .article-content p',
    "politico":     'article p, .story-text p',
    "thehill":      'article p, .field-items p',
    "sciencedaily": 'article p, #text p, .lead',
    "newscientist": 'article p, .article-body p',
    "economist":    'article p, .article__body p',
    "foreignpolicy":'article p, .post-content-main p',
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

# ── Store ──────────────────────────────────────────────────────────────────────

class Store:
    """
    Two-tier storage:
      store.json        — 30-day rolling window for fast access
      data/YYYY-Www.json — permanent weekly snapshots, never purged
    URL is the unique key; re-scraping updates in place, never duplicates.
    """

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
        """Trim store.json to rolling 30-day window only."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        before = len(self._data)
        self._data = {u: a for u, a in self._data.items()
                      if a.get("retrieved_at", "9999") >= cutoff}
        n = before - len(self._data)
        if n:
            print(f"[Store] Trimmed {n} articles from store.json (kept in weekly files).")
        self._save()

    def _save(self):
        """Atomically write store.json and update this week's archive file."""
        # Write store.json
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"articles": self._data}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

        # Write weekly archive file
        week    = week_key()
        cutoff  = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        weekly  = {u: a for u, a in self._data.items()
                   if a.get("retrieved_at", "") >= cutoff}
        os.makedirs("data", exist_ok=True)
        wpath   = f"data/{week}.json"
        wtmp    = wpath + ".tmp"

        # Merge with existing weekly file to not lose earlier entries this week
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
        existing = self._data.get(url, {})
        merged   = {**existing, **art}
        if "summary" not in art and "summary" in existing:
            merged["summary"] = existing["summary"]
        self._data[url] = merged
        self._save()

    def set_summary(self, url: str, summary: str):
        if url in self._data:
            self._data[url]["summary"] = summary
            self._save()

    def has(self, url: str) -> bool:
        """True if article exists with text already scraped."""
        return url in self._data and bool(self._data[url].get("text"))

    def unsummarized(self) -> list:
        arts = [a for a in self._data.values()
                if not a.get("summary") and a.get("text")]
        return arts

    def all(self) -> list:
        arts = list(self._data.values())
        arts.sort(key=lambda a: a.get("retrieved_at", ""), reverse=True)
        return arts

# ── NewsBrief ──────────────────────────────────────────────────────────────────

class NewsBrief:
    def __init__(self, store_path: str = STORE_PATH):
        self.store     = Store(store_path)
        self._articles = []

    # ── Scraping ───────────────────────────────────────────────────────────────

    def rss(
        self,
        feed_url:     str,
        source:       str   = "",
        max_articles: int   = 0,
        delay:        float = 0.3,
    ) -> list:
        try:
            import feedparser
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise ImportError(f"Missing: {e}. pip install feedparser playwright && playwright install chromium")

        src = source or feed_url
        print(f"\n[RSS] {src}  ({feed_url})")

        try:
            entries = feedparser.parse(feed_url).entries
        except Exception as e:
            print(f"[RSS] Parse error: {e}")
            return []

        if max_articles > 0:
            entries = entries[:max_articles]

        # Filter to new only before launching browser
        new_entries = [e for e in entries if not self.store.has(e.get("link", ""))]
        if not new_entries:
            print(f"[RSS] All {len(entries)} articles already in store, skipping.")
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

    def rss_all(self, feeds: list[tuple] = FEEDS) -> list:
        """Scrape all feeds in sequence. Each tuple is (url, source_name)."""
        all_arts = []
        for url, name in feeds:
            all_arts.extend(self.rss(url, source=name))
        return all_arts

    # ── Summarization ──────────────────────────────────────────────────────────

    def summarize(self, articles: list = None) -> list:
        """
        Summarize using allenai/led-large-16384.
        16384 token context means almost no news article needs chunking.
        Only falls back to chunking for extremely long pieces (10k+ words).
        """
        try:
            from transformers import pipeline
        except ImportError:
            raise ImportError("pip install transformers torch")

        arts = articles if articles is not None else self.store.unsummarized()
        if not arts:
            print("[Summarize] Nothing to summarize.")
            return []

        print("[Summarize] Loading allenai/led-large-16384...")
        summarizer = pipeline(
            "summarization",
            model     = "allenai/led-large-16384",
            tokenizer = "allenai/led-large-16384",
            device    = -1,
        )
        print(f"[Summarize] Model ready. {len(arts)} articles to process.\n")

        for i, art in enumerate(arts, 1):
            text = art.get("text", "")
            if not text:
                continue

            print(f"  [{i}/{len(arts)}] {art.get('title','')[:60]}", end=" ", flush=True)
            t0 = time.time()

            try:
                words  = text.split()
                # LED handles ~12000 words in one pass — chunk only if longer
                chunks = [" ".join(words[j:j+12000]) for j in range(0, len(words), 12000)]

                if len(chunks) == 1:
                    out     = summarizer(text, max_length=180, min_length=40,
                                         do_sample=False, truncation=True)
                    summary = out[0]["summary_text"]
                else:
                    # Rare: article > 12k words, summarize chunks then reduce
                    print(f"\n    ↳ {len(chunks)} chunks", end=" ", flush=True)
                    chunk_sums = []
                    for chunk in chunks:
                        o = summarizer(chunk, max_length=130, min_length=30,
                                       do_sample=False, truncation=True)
                        chunk_sums.append(o[0]["summary_text"])
                    combined = " ".join(chunk_sums)
                    final    = summarizer(combined, max_length=180, min_length=40,
                                          do_sample=False, truncation=True)
                    summary  = final[0]["summary_text"]

                art["summary"] = summary
                self.store.set_summary(art["link"], summary)
                print(f"✓  ({time.time()-t0:.1f}s)")

            except Exception as e:
                print(f"✗  {e}")

        print("\n[Summarize] Complete.\n")
        return arts

    # ── Read ───────────────────────────────────────────────────────────────────

    def get(self, source: str = "") -> list:
        arts = self.store.all()
        if source:
            arts = [a for a in arts if a.get("source") == source]
        return arts


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="NewsBrief — RSS + LED summarizer")
    p.add_argument("feed_url", nargs="?", default="")
    p.add_argument("--source",  "-s", type=str, default="")
    p.add_argument("--max",     "-m", type=int, default=0)
    p.add_argument("--all",     action="store_true", help="Scrape all default feeds")
    p.add_argument("--store",   type=str, default=STORE_PATH)
    p.add_argument("--no-summarize", action="store_true")
    args = p.parse_args()

    nb = NewsBrief(store_path=args.store)

    if args.all:
        nb.rss_all()
    elif args.feed_url:
        nb.rss(args.feed_url, source=args.source, max_articles=args.max)
    else:
        print("Pass a feed URL or --all to scrape default feeds.")
        raise SystemExit(1)

    if not args.no_summarize:
        nb.summarize()

    total = len(nb.get())
    print(f"[DONE] {total} articles in store.")
