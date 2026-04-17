#!/usr/bin/env python3
"""
Собирает сырые кандидаты из GitHub, HN, Reddit, PubMed, arXiv.
Дедуплицирует через config/scout/seen.jsonl.
Пишет результат в data/scout/candidates_YYYY-WW.json — Claude потом синтезирует дайджест.

Usage:
    python scripts/scout/fetch_candidates.py
    python scripts/scout/fetch_candidates.py --week 2026-W17   # принудительно перезапустить
    python scripts/scout/fetch_candidates.py --no-dedup        # игнорировать seen.jsonl
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config" / "scout"
DATA_DIR = ROOT / "data" / "scout"
SEEN_PATH = CONFIG_DIR / "seen.jsonl"
UA = "HealthVault-Scout/1.0 (personal research; contact: lyskovsky@gmail.com)"


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_seen() -> set[str]:
    if not SEEN_PATH.exists():
        return set()
    seen = set()
    for line in SEEN_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            seen.add(json.loads(line)["url"])
        except Exception:
            pass
    return seen


def append_seen(urls: list[str]) -> None:
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.utcnow().isoformat()
    with SEEN_PATH.open("a") as f:
        for u in urls:
            f.write(json.dumps({"url": u, "seen_at": now}) + "\n")


def iso_week(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def fetch_github(cfg: dict, ctx: dict) -> list[dict]:
    items = []
    for q in cfg.get("queries", []):
        query = q["q"].format(**ctx)
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": query, "sort": q.get("sort", "stars"), "order": "desc", "per_page": q.get("per_page", 15)}
        )
        try:
            data = json.loads(http_get(url))
        except Exception as e:
            print(f"[github] skip {query!r}: {e}", file=sys.stderr)
            continue
        for r in data.get("items", []):
            items.append(
                {
                    "source": "github",
                    "url": r["html_url"],
                    "title": r["full_name"],
                    "description": (r.get("description") or "")[:500],
                    "stars": r.get("stargazers_count", 0),
                    "language": r.get("language"),
                    "pushed_at": r.get("pushed_at"),
                    "topics": r.get("topics", []),
                    "query": query,
                }
            )
        time.sleep(2)  # GitHub unauthenticated: 10 req/min
    return items


def fetch_hn(cfg: dict) -> list[dict]:
    items = []
    for q in cfg.get("queries", []):
        since = int((dt.datetime.utcnow() - dt.timedelta(days=q["window_days"])).timestamp())
        params = {
            "query": q["query"],
            "tags": q.get("tags", "story"),
            "numericFilters": f"created_at_i>{since}",
            "hitsPerPage": 20,
        }
        url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(http_get(url))
        except Exception as e:
            print(f"[hn] skip {q['query']!r}: {e}", file=sys.stderr)
            continue
        for h in data.get("hits", []):
            link = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
            items.append(
                {
                    "source": "hn",
                    "url": link,
                    "title": h.get("title") or h.get("story_title") or "",
                    "description": (h.get("story_text") or "")[:300],
                    "points": h.get("points", 0),
                    "num_comments": h.get("num_comments", 0),
                    "created_at": h.get("created_at"),
                    "hn_discussion": f"https://news.ycombinator.com/item?id={h['objectID']}",
                    "query": q["query"],
                }
            )
        time.sleep(0.5)
    return items


def fetch_reddit(cfg: dict) -> list[dict]:
    items = []
    window = cfg.get("top_window", "week")
    limit = cfg.get("limit", 20)
    # Reddit blocks unknown UAs since 2023 — используем .json на old.reddit с браузерным UA
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept": "application/json",
    }
    for sub in cfg.get("subreddits", []):
        url = f"https://old.reddit.com/r/{sub}/top.json?t={window}&limit={limit}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[reddit] skip r/{sub}: {e}", file=sys.stderr)
            time.sleep(3)
            continue
        for child in data.get("data", {}).get("children", []):
            p = child["data"]
            items.append(
                {
                    "source": "reddit",
                    "url": "https://www.reddit.com" + p["permalink"],
                    "title": p["title"],
                    "description": (p.get("selftext") or "")[:400],
                    "score": p.get("score", 0),
                    "num_comments": p.get("num_comments", 0),
                    "subreddit": sub,
                    "external_url": p.get("url")
                    if p.get("url", "").startswith("http") and "reddit.com" not in p.get("url", "")
                    else None,
                    "created_utc": p.get("created_utc"),
                }
            )
        time.sleep(2)
    return items


def fetch_pubmed(cfg: dict) -> list[dict]:
    items = []
    for q in cfg.get("queries", []):
        since = (dt.date.today() - dt.timedelta(days=q["days_back"])).strftime("%Y/%m/%d")
        term = f"({q['query']}) AND ({since}[PDAT] : 3000[PDAT])"
        esearch = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "term": term, "retmax": q.get("limit", 10), "retmode": "json", "sort": "date"}
        )
        try:
            ids = json.loads(http_get(esearch)).get("esearchresult", {}).get("idlist", [])
        except Exception as e:
            print(f"[pubmed] skip {q['query']!r}: {e}", file=sys.stderr)
            continue
        if not ids:
            continue
        esummary = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"}
        )
        try:
            summ = json.loads(http_get(esummary)).get("result", {})
        except Exception:
            continue
        for pmid in ids:
            r = summ.get(pmid, {})
            if not r:
                continue
            items.append(
                {
                    "source": "pubmed",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "title": r.get("title", ""),
                    "description": (r.get("authors", [{}])[0].get("name", "") if r.get("authors") else "")
                    + " et al. "
                    + r.get("source", ""),
                    "pubdate": r.get("pubdate"),
                    "query": q["query"],
                }
            )
        time.sleep(0.5)
    return items


def fetch_arxiv(cfg: dict) -> list[dict]:
    items = []
    for q in cfg.get("queries", []):
        url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {
                "search_query": q["query"],
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": q.get("limit", 10),
            }
        )
        try:
            xml = http_get(url).decode()
        except Exception as e:
            print(f"[arxiv] skip {q['query']!r}: {e}", file=sys.stderr)
            continue
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=q["days_back"])
        for entry in root.findall("a:entry", ns):
            published = entry.findtext("a:published", default="", namespaces=ns)
            try:
                pub_dt = dt.datetime.fromisoformat(published.replace("Z", "+00:00")).replace(tzinfo=None)
                if pub_dt < cutoff:
                    continue
            except Exception:
                pass
            link = entry.findtext("a:id", default="", namespaces=ns)
            items.append(
                {
                    "source": "arxiv",
                    "url": link,
                    "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
                    "description": (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()[:500],
                    "published": published,
                    "query": q["query"],
                }
            )
        time.sleep(1)
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="YYYY-Www override")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--skip", default="", help="comma-separated sources to skip (github,hn,reddit,pubmed,arxiv)")
    args = ap.parse_args()

    sources = yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text())
    profile = yaml.safe_load((CONFIG_DIR / "profile.yaml").read_text())

    today = dt.date.today()
    week = args.week or iso_week(today)
    ctx = {
        "week_ago": (today - dt.timedelta(days=7)).isoformat(),
        "month_ago": (today - dt.timedelta(days=30)).isoformat(),
    }
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    seen = set() if args.no_dedup else load_seen()

    all_items: list[dict] = []
    fetchers = [
        ("github", lambda: fetch_github(sources.get("github", {}), ctx)),
        ("hn", lambda: fetch_hn(sources.get("hn", {}))),
        ("reddit", lambda: fetch_reddit(sources.get("reddit", {})) if sources.get("reddit", {}).get("enabled") else []),
        ("pubmed", lambda: fetch_pubmed(sources.get("pubmed", {}))),
        ("arxiv", lambda: fetch_arxiv(sources.get("arxiv", {}))),
    ]
    for name, fn in fetchers:
        if name in skip:
            print(f"[{name}] skipped via --skip", file=sys.stderr)
            continue
        print(f"[{name}] fetching...", file=sys.stderr)
        try:
            items = fn()
        except Exception as e:
            print(f"[{name}] ERROR: {e}", file=sys.stderr)
            continue
        print(f"[{name}] got {len(items)}", file=sys.stderr)
        all_items.extend(items)

    # Дедуп по URL
    deduped = []
    batch_urls = set()
    for it in all_items:
        url = it.get("url")
        if not url or url in seen or url in batch_urls:
            continue
        batch_urls.add(url)
        deduped.append(it)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"candidates_{week}.json"
    out = {
        "week": week,
        "generated_at": dt.datetime.utcnow().isoformat(),
        "profile_keywords": {
            "high": profile.get("wanted", {}).get("high_priority", []),
            "medium": profile.get("wanted", {}).get("medium_priority", []),
            "not_interested": profile.get("not_interested", []),
        },
        "total": len(deduped),
        "by_source": {s: sum(1 for x in deduped if x["source"] == s) for s in {x["source"] for x in deduped}},
        "items": deduped,
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n✅ {len(deduped)} свежих кандидатов → {out_path.relative_to(ROOT)}", file=sys.stderr)

    if not args.no_dedup:
        append_seen([it["url"] for it in deduped])
    return 0


if __name__ == "__main__":
    sys.exit(main())
