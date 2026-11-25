"""Morning HN's code steps: the work code does better than Claude (fetching, keeping, the gate's case, delivering).
Each is `def name(ctx, inputs) -> dict`; botrun calls them in the loop's order and passes their data on."""

import datetime as dt
import re
import time
import urllib.parse

SEARCH = "https://hn.algolia.com/api/v1/search"
QUERIES = ["AI agent", "AI agents", "agentic", "LLM agent", "agent memory", "LLM memory", "long-term memory AI"]
MIN_POINTS = 10
AGENT = re.compile(r"\bagent(s|ic)?\b", re.I)
MEMORY = re.compile(r"\bmemory\b|\bcontext window\b|\bremember", re.I)


def stories(ctx, inputs):
    """The last day's HN stories matching the queries, one per id, most points first."""
    since = int(time.time()) - 26 * 3600
    found = {}
    for q in QUERIES:
        params = urllib.parse.urlencode({
            "query": q,
            "tags": "story",
            "numericFilters": f"created_at_i>{since},points>={MIN_POINTS}",
            "hitsPerPage": 50,
        })
        for h in ctx.http_json(f"{SEARCH}?{params}").get("hits", []):
            sid = h.get("objectID")
            title = h.get("title") or ""
            if not sid or not title or sid in found:
                continue
            text = re.sub(r"<[^>]+>", " ", h.get("story_text") or "")
            hn_url = f"https://news.ycombinator.com/item?id={sid}"
            found[sid] = {
                "id": sid,
                "title": title,
                "url": h.get("url") or hn_url,
                "hn_url": hn_url,
                "points": h.get("points") or 0,
                "comments": h.get("num_comments") or 0,
                "author": h.get("author") or "",
                "text": " ".join(text.split())[:300],
            }
    ctx.log(f"found {len(found)} stories")
    return {"date": ctx.today.isoformat(), "stories": sorted(found.values(), key=lambda s: -s["points"])}


def keep(ctx, inputs):
    """Today's stories kept as seen; answers only those not seen on an earlier morning (at most 30)."""
    db = ctx.db()
    db.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, date TEXT, title TEXT, points INT)")
    new = []
    for s in inputs["stories"]:
        row = db.execute("SELECT date FROM seen WHERE id = ?", (s["id"],)).fetchone()
        if row and row[0] < inputs["date"]:
            continue
        db.execute("INSERT OR REPLACE INTO seen VALUES (?, ?, ?, ?)", (s["id"], inputs["date"], s["title"], s["points"]))
        new.append(s)
    db.commit()
    return {"date": inputs["date"], "stories": new[:30]}


def worth_case(ctx, data):
    """The worth_digest gate's case: how much new turned up, how big it is, and how long since the last digest."""
    found = data["keep"]["stories"]
    last_sent = ctx.state("last_sent")
    since = (ctx.today - dt.date.fromisoformat(last_sent)).days if last_sent else 14
    return {
        "morning": {
            "found": {
                "stories": min(len(found), 50),
                "agent_stories": min(sum(1 for s in found if AGENT.search(s["title"])), 50),
                "memory_stories": min(sum(1 for s in found if MEMORY.search(s["title"])), 50),
                "top_points": min(max((s["points"] for s in found), default=0), 1000),
                "top_comments": min(max((s["comments"] for s in found), default=0), 500),
                "titles": " ".join(s["title"] for s in found),
            },
            "when": {"weekday": ctx.today.strftime("%a"), "days_since_sent": min(since, 14), "run": ctx.run_id},
        }
    }


def deliver(ctx, inputs):
    """The digest into out/<date>.md."""
    path = ctx.dir / "out" / f"{ctx.today.isoformat()}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(inputs if isinstance(inputs, str) else str(inputs))
    ctx.set_state("last_sent", ctx.today.isoformat())
    return {"path": str(path)}
