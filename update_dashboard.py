"""
Reddit Intelligence Dashboard Generator
========================================
Reads data/archive.json + data/history.json,
injects JS constants into dashboard.html.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
HERE       = Path(__file__).parent
DASHBOARD  = HERE / "dashboard.html"
DATA_DIR   = HERE / "data"
ARCHIVE    = DATA_DIR / "archive.json"
HISTORY    = DATA_DIR / "history.json"

BRAND_ORDER = ["arena-club", "courtyard", "rbt", "icybox"]
BRANDS = {
    "arena-club": {"name": "Arena Club",       "short": "AC",  "color": "#22c55e", "key": "ac"},
    "courtyard":  {"name": "Courtyard",         "short": "CY",  "color": "#5B8DD9", "key": "cy"},
    "rbt":        {"name": "Rips by Triumph",   "short": "RBT", "color": "#E8823A", "key": "rbt"},
    "icybox":     {"name": "IcyBox",            "short": "ICY", "color": "#9B59B6", "key": "icy"},
}

# ─── Loaders ──────────────────────────────────────────────────────────────────
def load_archive():
    if not ARCHIVE.exists():
        print(f"  ⚠  {ARCHIVE} not found — run run_weekly.py first")
        return []
    data = json.loads(ARCHIVE.read_text())
    return data if isinstance(data, list) else list(data.values())


def load_history():
    if not HISTORY.exists():
        return {"snapshots": []}
    return json.loads(HISTORY.read_text())


# ─── Computations ─────────────────────────────────────────────────────────────
def compute_sentiment(mentions):
    by_brand = defaultdict(list)
    for m in mentions:
        bid = m.get("brand")
        if bid in BRAND_ORDER:
            by_brand[bid].append(m)
    out = {}
    for bid in BRAND_ORDER:
        blist = by_brand[bid]
        total = len(blist) or 1
        pos = sum(1 for m in blist if m.get("sentiment") == "positive")
        neu = sum(1 for m in blist if m.get("sentiment") == "neutral")
        pos_pct = round(pos / total * 100)
        neu_pct = round(neu / total * 100)
        out[bid] = {
            "pos": pos_pct,
            "neu": neu_pct,
            "neg": max(0, 100 - pos_pct - neu_pct),
            "total": len(blist),
        }
    return out


def compute_subreddit_breakdown(mentions):
    """Count mentions per subreddit per brand."""
    by_brand = defaultdict(lambda: defaultdict(int))
    for m in mentions:
        bid = m.get("brand")
        sub = m.get("subreddit", "unknown")
        if bid in BRAND_ORDER:
            by_brand[bid][sub] += 1
    out = {}
    for bid in BRAND_ORDER:
        subs = dict(sorted(by_brand[bid].items(), key=lambda x: -x[1]))
        out[bid] = subs
    return out


def load_wow_deltas():
    hist = load_history()
    snaps = hist.get("snapshots", [])
    if len(snaps) < 2:
        return {}
    prev = snaps[-2].get("brands", {})
    cur  = snaps[-1].get("brands", {})
    out  = {}
    for bid in BRAND_ORDER:
        c = cur.get(bid, {})
        p = prev.get(bid, {})
        out[bid] = {
            "neg_delta": c.get("neg_delta", 0),
            "pos_delta": round(c.get("positive_rate", 0) - p.get("positive_rate", c.get("positive_rate", 0)), 4),
        }
    return out


def top_posts(mentions, n=20):
    """Top N posts by score this week."""
    posts = [m for m in mentions if m.get("type") == "post"]
    return sorted(posts, key=lambda m: m.get("score", 0), reverse=True)[:n]


def hot_this_week(mentions, n=15):
    """Most-upvoted NEW posts/comments this week."""
    new_m = [m for m in mentions if m.get("is_new")]
    return sorted(new_m, key=lambda m: m.get("score", 0), reverse=True)[:n]


def creator_posts(mentions, n=10):
    """Posts with creator/influencer signals."""
    return [m for m in mentions if m.get("has_creator")][:n]


def ad_opportunity_posts(mentions, n=15):
    """Posts flagged as ad opportunities."""
    return [m for m in mentions if m.get("ad_opportunity")][:n]


# ─── Weekly digest ────────────────────────────────────────────────────────────
def compute_digest(mentions, sentiment, wow_deltas):
    by_brand     = defaultdict(list)
    new_by_brand = defaultdict(list)
    for m in mentions:
        bid = m.get("brand")
        if bid in BRAND_ORDER:
            by_brand[bid].append(m)
            if m.get("is_new"):
                new_by_brand[bid].append(m)

    today    = date.today()
    wk_start = (today - timedelta(days=6)).strftime("%b %-d")
    wk_end   = today.strftime("%b %-d, %Y")

    def brand_section(bid):
        blist   = by_brand[bid]
        nlist   = new_by_brand[bid]
        s       = sentiment.get(bid, {"pos": 0, "neu": 0, "neg": 0, "total": 0})
        sd      = wow_deltas.get(bid, {})
        top_sub = sorted(
            ((sub, cnt) for sub, cnt in defaultdict(int, [(m["subreddit"], 1) for m in blist]).items()),
            key=lambda x: -x[1]
        )
        best_post = max(nlist, key=lambda m: m.get("score", 0)) if nlist else None
        return {
            "new_mentions":   len(nlist),
            "total_mentions": len(blist),
            "sentiment":      s,
            "sentiment_delta": sd,
            "top_subreddit":  top_sub[0][0] if top_sub else None,
            "creator_count":  sum(1 for m in nlist if m.get("has_creator")),
            "ad_opps":        sum(1 for m in nlist if m.get("ad_opportunity")),
            "best_post": {
                "title":  best_post["title"],
                "score":  best_post["score"],
                "url":    best_post["url"],
                "sub":    best_post["subreddit"],
                "sentiment": best_post["sentiment"],
            } if best_post else None,
        }

    ac    = brand_section("arena-club")
    comps = {bid: brand_section(bid) for bid in ["courtyard", "rbt", "icybox"]}

    # Ad impact paragraph
    cy_neg  = sentiment.get("courtyard", {}).get("neg", 0)
    icy_neg = sentiment.get("icybox",    {}).get("neg", 0)
    ac_pos  = sentiment.get("arena-club",{}).get("pos", 0)
    cy_sd   = wow_deltas.get("courtyard", {})
    icy_sd  = wow_deltas.get("icybox",    {})
    ac_sd   = wow_deltas.get("arena-club",{})

    impact_parts = []
    if cy_sd.get("neg_delta", 0) > 0.03:
        impact_parts.append(
            f"Courtyard's Reddit negativity climbed this week — CS complaints and value concerns "
            f"are spreading in the community. Counter-position now with AC's response speed and Buyback Guarantee."
        )
    elif cy_neg > 45:
        impact_parts.append(
            f"Courtyard holds at {cy_neg}% negative sentiment on Reddit. Their churning community "
            f"members are actively searching for alternatives — target Courtyard brand keywords."
        )

    ac_creators = sum(1 for m in by_brand["arena-club"] if m.get("has_creator") and m.get("is_new"))
    if ac_creators > 0:
        impact_parts.append(
            f"{ac_creators} Arena Club post{'s' if ac_creators > 1 else ''} this week "
            f"mentioned creators or social media. These are audience amplification opportunities — "
            f"engage those threads and consider reaching out to the creators directly."
        )

    ac_ad_opps = sum(1 for m in new_by_brand["arena-club"] if m.get("ad_opportunity"))
    all_ad_opps = sum(1 for m in mentions if m.get("ad_opportunity") and m.get("is_new"))
    if all_ad_opps > 3:
        impact_parts.append(
            f"{all_ad_opps} posts this week contain explicit 'looking for alternative' or "
            f"comparison signals — these are high-intent moments. Retargeting those threads with "
            f"a well-timed AC ad or organic reply converts at a much higher rate."
        )

    if not impact_parts:
        impact_parts.append(
            "Community sentiment is stable this week. Maintain your organic presence in "
            "r/tradingcards and r/basketballcards. The Buyback Guarantee remains the strongest "
            "differentiator in these communities — lead with it whenever AC comes up."
        )

    # 3 actions
    actions = []
    ac_neg_pct = sentiment.get("arena-club", {}).get("neg", 0)
    neg_posts = [m for m in new_by_brand["arena-club"] if m.get("sentiment") == "negative"]
    if neg_posts:
        actions.append(
            f"Respond to Arena Club's {len(neg_posts)} negative Reddit mention{'s' if len(neg_posts)>1 else ''} "
            f"this week — organic brand responses in threads convert skeptics and show the community AC listens."
        )
    else:
        actions.append(
            "Drop an organic value post in r/tradingcards or r/basketballcards — "
            "a thread about Buyback economics or a 'how AC works' explainer builds community credibility."
        )

    if cy_neg > 50 or icy_neg > 45:
        top_comp = "Courtyard" if cy_neg > icy_neg else "IcyBox"
        top_pct  = cy_neg if cy_neg > icy_neg else icy_neg
        actions.append(
            f"{top_comp} is at {top_pct}% negative Reddit sentiment. Find threads where "
            f"users are complaining about them and add a genuine, helpful comparison — "
            f"this community-level retargeting is free and highly effective."
        )
    else:
        actions.append(
            "Boost the highest-scoring Arena Club post this week — even a small upvote campaign "
            "on a genuinely positive thread increases visibility in the subreddit algorithm."
        )

    total_new = sum(len(v) for v in new_by_brand.values())
    actions.append(
        f"Review the {len(creator_posts(mentions))} creator-signal posts in the Insights tab. "
        f"If any are from active YouTubers or TikTokers in the card space, DM them about a "
        f"partnership before a competitor does."
    )

    # Best post overall (highest score, new)
    all_new = [m for m in mentions if m.get("is_new")]
    best = max(all_new, key=lambda m: m.get("score", 0)) if all_new else None

    return {
        "week":        f"{wk_start}–{wk_end}",
        "total_new":   sum(len(v) for v in new_by_brand.values()),
        "arena_club":  ac,
        "competitors": comps,
        "ad_impact":   " ".join(impact_parts),
        "top_actions": actions,
        "top_post_week": {
            "title":  best["title"],
            "score":  best["score"],
            "url":    best["url"],
            "sub":    best["subreddit"],
            "brand":  best["brand"],
            "sentiment": best["sentiment"],
        } if best else None,
    }


# ─── JS serializers ───────────────────────────────────────────────────────────
def inject(html: str, const_name: str, new_value: str) -> str:
    """Replace a JS const declaration by scanning bracket depth."""
    pattern = rf"(?s)(const\s+{re.escape(const_name)}\s*=\s*)"
    m = re.search(pattern, html)
    if not m:
        print(f"  ⚠  const {const_name} not found in HTML — skipping")
        return html
    start = m.end()
    first = html[start]
    if first not in ("{", "["):
        end = html.index(";", start)
        return html[:m.start()] + f"const {const_name} = {new_value};" + html[end + 1:]
    depth, i, in_str, esc = 0, start, False, False
    open_ch  = first
    close_ch = "}" if open_ch == "{" else "]"
    while i < len(html):
        ch = html[i]
        if esc:
            esc = False
        elif ch == "\\" and in_str:
            esc = True
        elif ch in ('"', "'", "`") and not in_str:
            in_str = True; str_ch = ch
        elif in_str and ch == str_ch:
            in_str = False
        elif not in_str:
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    end = i
                    break
        i += 1
    semi = html.index(";", end)
    return html[:m.start()] + f"const {const_name} = {new_value};" + html[semi + 1:]


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print(f"\nReading archive...")
    mentions = load_archive()
    print(f"  {len(mentions)} total mentions on file")

    sentiment   = compute_sentiment(mentions)
    subreddits  = compute_subreddit_breakdown(mentions)
    wow_deltas  = load_wow_deltas()
    digest      = compute_digest(mentions, sentiment, wow_deltas)
    hot         = hot_this_week(mentions)
    creators    = creator_posts(mentions)
    ad_opps     = ad_opportunity_posts(mentions)

    # Serialize mentions for dashboard (cap at 2000 most recent for page size)
    mentions_sorted = sorted(mentions, key=lambda m: m.get("created_utc", 0), reverse=True)

    print(f"\nReading {DASHBOARD.name}...")
    html = DASHBOARD.read_text(encoding="utf-8")

    today = date.today().isoformat()
    html  = re.sub(r'const DATA_DATE\s*=\s*"[^"]*";', f'const DATA_DATE = "{today}";', html)

    html = inject(html, "MENTIONS",    json.dumps(mentions_sorted[:2000], ensure_ascii=False))
    html = inject(html, "SENTIMENT",   json.dumps(sentiment,  ensure_ascii=False))
    html = inject(html, "SUBREDDITS",  json.dumps(subreddits, ensure_ascii=False))
    html = inject(html, "HOT_POSTS",   json.dumps(hot,        ensure_ascii=False))
    html = inject(html, "CREATORS",    json.dumps(creators,   ensure_ascii=False))
    html = inject(html, "AD_OPPS",     json.dumps(ad_opps,    ensure_ascii=False))
    html = inject(html, "WEEKLY_DIGEST", json.dumps(digest,   ensure_ascii=False, indent=2))

    # Update digest meta line
    new_count  = sum(1 for m in mentions if m.get("is_new"))
    week_label = digest["week"]
    meta_text  = (f"{week_label} · {new_count} new mentions across 4 brands"
                  if new_count else f"{week_label} · {len(mentions)} mentions on file")
    html = re.sub(r'id="digestMeta">[^<]*<', f'id="digestMeta">{meta_text}<', html)

    DASHBOARD.write_text(html, encoding="utf-8")
    print(f"\n{'='*55}")
    print("Dashboard updated!")
    print(f"  Mentions injected : {min(len(mentions_sorted), 2000)}")
    print(f"  Date stamped      : {today}")
    print(f"  File              : {DASHBOARD}")


if __name__ == "__main__":
    main()
