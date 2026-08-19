"""
Reddit Brand Intelligence Scraper
==================================
Searches Reddit for mentions of Arena Club, Courtyard, Rips by Triumph, and IcyBox.
Uses Reddit's public JSON API — NO credentials or API key required.

SETUP: None. Just run it.
"""

import json
import re
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Brand config ─────────────────────────────────────────────────────────────
BRANDS = {
    "arena-club": {
        "name":       "Arena Club",
        "short":      "AC",
        "color":      "#22c55e",
        "keywords":   ["Arena Club", "arenaclub", "arena club app"],
        "subreddits": ["tradingcards", "basketballcards", "Sportscard", "sportscards",
                       "baseballcards", "footballcards", "hockeycards", "PokemonTCG"],
    },
    "courtyard": {
        "name":       "Courtyard",
        "short":      "CY",
        "color":      "#5B8DD9",
        "keywords":   ["Courtyard.io", "Courtyard app", "courtyard trading cards",
                       "courtyard collectibles", "courtyard card"],
        "subreddits": ["tradingcards", "basketballcards", "Sportscard", "sportscards",
                       "baseballcards", "footballcards"],
    },
    "rbt": {
        "name":       "Rips by Triumph",
        "short":      "RBT",
        "color":      "#E8823A",
        "keywords":   ["Rips by Triumph", "RBT cards", "ripsbytriumpth",
                       "triumph rips", "rips triumph"],
        "subreddits": ["tradingcards", "basketballcards", "Sportscard", "sportscards"],
    },
    "icybox": {
        "name":       "IcyBox",
        "short":      "ICY",
        "color":      "#9B59B6",
        "keywords":   ["IcyBox", "Icy Box app", "icybox.io", "icybox watches"],
        "subreddits": ["Watches", "WatchExchange", "WatchHorology"],
    },
}

BRAND_ORDER = ["arena-club", "courtyard", "rbt", "icybox"]

# ─── Sentiment keywords ────────────────────────────────────────────────────────
POSITIVE_WORDS = [
    "love", "great", "amazing", "excellent", "best", "awesome", "fantastic",
    "perfect", "recommend", "legit", "legitimate", "trusted", "trustworthy",
    "fast", "quick", "easy", "fair", "transparent", "happy", "pleased",
    "buyback", "guarantee", "authentic", "real", "solid", "worth it",
    "impressed", "satisfied", "reliable", "safe", "secure", "honest",
    "responsive", "helpful", "good service", "good experience",
]
NEGATIVE_WORDS = [
    "scam", "fraud", "fake", "terrible", "awful", "worst", "avoid", "lost",
    "stolen", "ripped off", "ripoff", "rip off", "shady", "sketchy", "suspicious",
    "never respond", "no response", "ghosted", "disappeared", "banned", "blocked",
    "broken", "crash", "bug", "glitch", "slow", "expensive", "overpriced",
    "disappointed", "waste", "regret", "refund", "complaint", "issue", "problem",
    "never again", "stay away", "warning", "beware", "horrible", "garbage",
    "useless", "worthless", "misleading", "deceptive", "lied", "not worth",
    "bad experience", "poor service", "ignored", "frustrated",
]

CREATOR_PATTERNS = [
    r"youtu(?:be|\.be)", r"tiktok\.com", r"instagram\.com",
    r"twitter\.com|x\.com", r"@\w{3,}", r"\byoutube\b", r"\btiktok\b",
    r"\binstagram\b", r"\binfluencer\b", r"\bcreator\b", r"\bstreamer\b",
    r"\byoutuber\b", r"\bpodcast\b", r"\bvideo\b", r"\bsponsor(?:ed)?\b",
]
CREATOR_RE = re.compile("|".join(CREATOR_PATTERNS), re.IGNORECASE)

AD_SIGNALS = [
    "looking for", "recommend", "any good", "alternatives", "switched from",
    "moved to", "left courtyard", "left icybox", "after courtyard",
    "better than", "worse than", "compared to", "vs ", "versus",
    "wish they had", "if only", "they should", "missing feature",
    "want an app", "need an app", "what app",
]
AD_SIGNAL_RE = re.compile("|".join(AD_SIGNALS), re.IGNORECASE)

# ─── HTTP helper ──────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 ArenaClubIntelligence/1.0 (reddit monitor; contact vborda@arenaclub.com)",
    "Accept": "application/json",
}

def reddit_get(url: str, retries: int = 3) -> dict | None:
    """Fetch a Reddit JSON endpoint with retry logic."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"    ⚠  Failed: {url[:80]} — {e}")
    return None


# ─── Sentiment / signal helpers ───────────────────────────────────────────────
def classify_sentiment(text: str) -> str:
    t = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in t)
    neg = sum(1 for w in NEGATIVE_WORDS if w in t)
    if neg > pos:   return "negative"
    if pos > neg:   return "positive"
    return "neutral"

def has_creator_signal(text: str) -> bool:
    return bool(CREATOR_RE.search(text))

def has_ad_opportunity(text: str) -> bool:
    return bool(AD_SIGNAL_RE.search(text))

def make_mention(*, mid, brand_id, mtype, subreddit, keyword,
                 title, body, author, score, num_comments, url,
                 created_utc, known_ids):
    full_text = f"{title} {body}"
    ts = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    return {
        "id":            mid,
        "brand":         brand_id,
        "type":          mtype,
        "subreddit":     subreddit,
        "keyword":       keyword,
        "title":         title[:300],
        "body":          body[:600],
        "author":        author,
        "score":         score,
        "num_comments":  num_comments,
        "url":           url,
        "date":          ts.strftime("%Y-%m-%d"),
        "created_utc":   int(created_utc),
        "sentiment":     classify_sentiment(full_text),
        "has_creator":   has_creator_signal(full_text),
        "ad_opportunity": has_ad_opportunity(full_text),
        "is_new":        mid not in known_ids,
        "source":        "reddit",
    }


# ─── Core scraper ─────────────────────────────────────────────────────────────
def scrape_subreddit_keyword(brand_id: str, subreddit: str, keyword: str,
                              known_ids: set, cutoff: datetime,
                              seen: set) -> list:
    """Search one subreddit for one keyword, return mention dicts."""
    out = []
    after = None
    pages = 0
    max_pages = 5   # up to 500 results per subreddit/keyword combo

    while pages < max_pages:
        params = {
            "q":           keyword,
            "restrict_sr": "1",
            "sort":        "new",
            "t":           "month",
            "limit":       "100",
            "type":        "link",    # posts only in first pass
        }
        if after:
            params["after"] = after

        url = f"https://www.reddit.com/r/{subreddit}/search.json?{urllib.parse.urlencode(params)}"
        data = reddit_get(url)
        time.sleep(1.1)   # stay well under rate limit

        if not data or "data" not in data:
            break

        children = data["data"].get("children", [])
        if not children:
            break

        for child in children:
            p = child.get("data", {})
            created = p.get("created_utc", 0)
            post_ts = datetime.fromtimestamp(created, tz=timezone.utc)
            if post_ts < cutoff:
                continue

            pid = f"post_{p.get('id', '')}"
            if pid not in seen:
                seen.add(pid)
                out.append(make_mention(
                    mid=pid, brand_id=brand_id, mtype="post",
                    subreddit=subreddit, keyword=keyword,
                    title=p.get("title", ""),
                    body=p.get("selftext", ""),
                    author=str(p.get("author", "[deleted]")),
                    score=p.get("score", 0),
                    num_comments=p.get("num_comments", 0),
                    url=f"https://reddit.com{p.get('permalink', '')}",
                    created_utc=created,
                    known_ids=known_ids,
                ))

        after = data["data"].get("after")
        if not after:
            break
        pages += 1

    return out


def scrape_comments_keyword(brand_id: str, keyword: str,
                             known_ids: set, cutoff: datetime,
                             seen: set, subreddits: list) -> list:
    """Search all-Reddit comments for keyword, filtered to relevant subreddits."""
    out = []
    sub_filter = "+".join(subreddits)
    params = {
        "q":     keyword,
        "sort":  "new",
        "t":     "month",
        "limit": "100",
        "type":  "comment",
    }
    url = f"https://www.reddit.com/r/{sub_filter}/search.json?{urllib.parse.urlencode(params)}"
    data = reddit_get(url)
    time.sleep(1.1)

    if not data or "data" not in data:
        return out

    for child in data["data"].get("children", []):
        c = child.get("data", {})
        created = c.get("created_utc", 0)
        c_ts = datetime.fromtimestamp(created, tz=timezone.utc)
        if c_ts < cutoff:
            continue
        if keyword.lower() not in (c.get("body", "") + c.get("link_title", "")).lower():
            continue

        cid = f"comment_{c.get('id', '')}"
        if cid in seen:
            continue
        seen.add(cid)
        sub = c.get("subreddit", "unknown")
        out.append(make_mention(
            mid=cid, brand_id=brand_id, mtype="comment",
            subreddit=sub, keyword=keyword,
            title=c.get("link_title", ""),
            body=c.get("body", ""),
            author=str(c.get("author", "[deleted]")),
            score=c.get("score", 0),
            num_comments=0,
            url=f"https://reddit.com{c.get('permalink', '')}",
            created_utc=created,
            known_ids=known_ids,
        ))

    return out


def scrape_brand(brand_id: str, cfg: dict, known_ids: set,
                 lookback_days: int = 7) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    seen   = set()
    out    = []

    for kw in cfg["keywords"]:
        for sub_name in cfg["subreddits"]:
            results = scrape_subreddit_keyword(
                brand_id, sub_name, kw, known_ids, cutoff, seen
            )
            out.extend(results)

        # Also grab comment mentions across all brand subreddits
        comment_results = scrape_comments_keyword(
            brand_id, kw, known_ids, cutoff, seen, cfg["subreddits"]
        )
        out.extend(comment_results)

    return out


# ─── Entry point called by run_weekly.py ──────────────────────────────────────
def run(known_ids: set = None, lookback_days: int = 7,
        config_path: str = None) -> dict:
    """
    Returns {"brands": {brand_id: {"mentions": [...], "new_this_run": N}}}
    No credentials required — uses Reddit's public JSON API.
    """
    if known_ids is None:
        known_ids = set()

    result = {"brands": {}}
    for brand_id in BRAND_ORDER:
        brand_cfg = BRANDS[brand_id]
        print(f"  {brand_cfg['name']}...")
        mentions  = scrape_brand(brand_id, brand_cfg, known_ids, lookback_days)
        new_count = sum(1 for m in mentions if m["is_new"])
        print(f"    → {len(mentions)} found, {new_count} new")
        result["brands"][brand_id] = {
            "mentions":     mentions,
            "new_this_run": new_count,
        }

    return result
