"""
Reddit Intelligence Weekly Runner
===================================
Scrapes Reddit for brand mentions, updates persistent data,
regenerates dashboard.html, and pushes to GitHub → Vercel auto-deploys.

FILES MANAGED:
  data/archive.json          — every mention ever (append-only)
  data/history.json          — weekly mention/sentiment snapshots
  data/weekly/YYYY-MM-DD.json — this week's new mentions only

SCHEDULE:
  Every Monday at 9am PT — via Cowork scheduled task

SETUP (one time):
  No credentials needed — uses Reddit's public JSON API.
  python3 run_weekly.py --initial   # seed 90-day history on first run
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
WEEKLY_DIR  = DATA_DIR / "weekly"
DATA_DIR.mkdir(exist_ok=True)
WEEKLY_DIR.mkdir(exist_ok=True)

ARCHIVE_PATH = DATA_DIR / "archive.json"
HISTORY_PATH = DATA_DIR / "history.json"

GIT_AUTO_PUSH = True

BRAND_NAMES = {
    "arena-club": "Arena Club",
    "courtyard":  "Courtyard",
    "rbt":        "Rips by Triumph",
    "icybox":     "IcyBox",
}

# ─── Helpers ──────────────────────────────────────────────────────────────────
def load_json(path, default):
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str))


def today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_archive():
    data = load_json(ARCHIVE_PATH, [])
    return data if isinstance(data, list) else list(data.values())


def merge_new(archive, new_mentions):
    existing_ids = {r["id"] for r in archive}
    added = 0
    for m in new_mentions:
        if m["id"] not in existing_ids:
            archive.append(m)
            existing_ids.add(m["id"])
            added += 1
    return archive, added


# ─── Brand stats ──────────────────────────────────────────────────────────────
def compute_brand_stats(archive):
    stats = {}
    for m in archive:
        bid = m.get("brand", "unknown")
        if bid not in stats:
            stats[bid] = {
                "total": 0, "positive": 0, "neutral": 0, "negative": 0,
                "posts": 0, "comments": 0, "creator_mentions": 0, "ad_opportunities": 0,
            }
        s = stats[bid]
        s["total"] += 1
        s[m.get("sentiment", "neutral")] = s.get(m.get("sentiment", "neutral"), 0) + 1
        if m.get("type") == "post":
            s["posts"] += 1
        else:
            s["comments"] += 1
        if m.get("has_creator"):
            s["creator_mentions"] += 1
        if m.get("ad_opportunity"):
            s["ad_opportunities"] += 1

    for bid, s in stats.items():
        total = max(s["total"], 1)
        s["negative_rate"] = round(s["negative"] / total, 4)
        s["positive_rate"] = round(s["positive"] / total, 4)

    return stats


# ─── History snapshot ─────────────────────────────────────────────────────────
def update_history(current_stats, week):
    history = load_json(HISTORY_PATH, {"snapshots": []})
    prev_brands = {}
    if history["snapshots"]:
        prev_brands = history["snapshots"][-1].get("brands", {})

    snapshot = {"week": week, "brands": {}}
    for bid, s in current_stats.items():
        prev_neg = prev_brands.get(bid, {}).get("negative_rate", s["negative_rate"])
        delta    = round(s["negative_rate"] - prev_neg, 4)
        snapshot["brands"][bid] = {
            "total":         s["total"],
            "negative_rate": s["negative_rate"],
            "positive_rate": s["positive_rate"],
            "neg_delta":     delta,
            "creator_mentions": s.get("creator_mentions", 0),
            "ad_opportunities": s.get("ad_opportunities", 0),
        }

    history["snapshots"].append(snapshot)
    if len(history["snapshots"]) > 52:
        history["snapshots"] = history["snapshots"][-52:]
    save_json(HISTORY_PATH, history)
    print(f"  History: {len(history['snapshots'])} weeks logged")
    return history


# ─── Git push ─────────────────────────────────────────────────────────────────
def git_push(week):
    if not GIT_AUTO_PUSH:
        print("  Git push skipped (GIT_AUTO_PUSH=False)")
        return
    try:
        subprocess.run(["git", "add", "dashboard.html"], cwd=BASE_DIR,
                       check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Reddit weekly update {week}"],
                       cwd=BASE_DIR, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=BASE_DIR, check=True, capture_output=True)
        print("  Pushed to GitHub — Vercel deploying")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        if "nothing to commit" in stderr or "nothing added" in stderr:
            print("  No changes to push")
        else:
            print(f"  Git push failed: {stderr[:200]}")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    initial     = "--initial" in sys.argv
    lookback    = 90 if initial else 7
    week        = today_str()

    print("=" * 62)
    print(f"Reddit Intelligence  --  {datetime.now().strftime('%A %b %d, %Y %H:%M')}")
    print("Initial (90-day seed)" if initial else "Weekly update (7 days)")
    print("=" * 62)

    archive   = load_archive()
    known_ids = {m["id"] for m in archive}
    print(f"\nArchive: {len(known_ids)} mentions on file\n")

    # ── Scrape Reddit ─────────────────────────────────────────────────────────
    print("REDDIT")
    all_new = []
    try:
        from reddit_scraper import run as run_reddit
        result = run_reddit(
            known_ids=known_ids,
            lookback_days=lookback,
        )
        for brand_data in result["brands"].values():
            all_new.extend([m for m in brand_data["mentions"] if m.get("is_new")])
    except Exception as e:
        print(f"  Reddit scraper failed: {e}")

    # ── Persist ───────────────────────────────────────────────────────────────
    archive, added = merge_new(archive, all_new)
    save_json(ARCHIVE_PATH, archive)

    weekly_path = WEEKLY_DIR / f"{week}.json"
    save_json(weekly_path, {"week": week, "count": len(all_new), "mentions": all_new})
    print(f"\nArchive: +{added} new  →  {len(archive)} total")

    # ── Stats + history ───────────────────────────────────────────────────────
    print("\nSTATS")
    current_stats = compute_brand_stats(archive)
    history = update_history(current_stats, week)

    # ── Regenerate dashboard ──────────────────────────────────────────────────
    print("\nREGENERATING DASHBOARD")
    try:
        result = subprocess.run(
            [sys.executable, str(BASE_DIR / "update_dashboard.py")],
            capture_output=True, text=True, cwd=str(BASE_DIR),
        )
        if result.returncode == 0:
            print("  Dashboard updated successfully")
        else:
            print(f"  Dashboard error:\n{result.stderr[:400]}")
    except Exception as e:
        print(f"  Could not run update_dashboard.py: {e}")

    # ── Git push ──────────────────────────────────────────────────────────────
    print("\nGIT PUSH")
    git_push(week)

    # ── Digest ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("WEEKLY DIGEST")
    print("=" * 62)
    snapshot = history["snapshots"][-1]["brands"] if history["snapshots"] else {}
    for bid, bname in BRAND_NAMES.items():
        s    = current_stats.get(bid, {})
        snap = snapshot.get(bid, {})
        delta = snap.get("neg_delta", 0)
        new_n = sum(1 for m in all_new if m.get("brand") == bid)
        print(f"\n  {bname}")
        print(f"    Neg rate  : {s.get('negative_rate',0)*100:.1f}%  ({delta*100:+.1f}% vs last week)")
        print(f"    Total     : {s.get('total',0)} mentions on file")
        print(f"    New       : {new_n} this week")
        print(f"    Creators  : {s.get('creator_mentions',0)} posts with creator signals")
        print(f"    Ad opps   : {s.get('ad_opportunities',0)} posts with ad opportunity signals")

    print(f"\n  Week       : {week}")
    print(f"  New total  : {added}")
    print("=" * 62)


if __name__ == "__main__":
    main()
