#!/usr/bin/env python3
"""Watch for the IND vs SL 2nd ODI (16 Dec 2026, Chinnaswamy) ticket sale and alert via ntfy.

Signals checked every run:
  1. Google News RSS (static XML, no JS, best early signal for the announcement)
  2. Optional ticketing/KSCA pages listed in PAGES (text search; JS-heavy pages may not work)
"""
import json, os, re, sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
STATE_FILE = "state.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
IST = timezone(timedelta(hours=5, minutes=30))
MAX_AGE_DAYS = 7  # ignore old articles (e.g. the 2022 Bengaluru Test)

NEWS_QUERIES = [
    "India Sri Lanka Chinnaswamy ODI tickets",
    "KSCA tickets India vs Sri Lanka Bengaluru ODI",
    "District Zomato India Sri Lanka ODI tickets Bengaluru",
]
# Add listing pages you want scanned. Verify each URL opens in a browser first.
PAGES = [
    "https://www.kscacricket.com/",
]

TEAM = re.compile(r"sri lanka|ind vs sl|india vs sl|ind-sl", re.I)
VENUE = re.compile(r"chinnaswamy|bengaluru|bangalore", re.I)
ODI = re.compile(r"\bodi\b|16 dec|december 16|dec 16|2026", re.I)
SALE = re.compile(
    r"tickets?\b.{0,40}(on sale|go(?:es)? live|live now|available|booking|open)"
    r"|book (?:now|tickets)|buy tickets|sale (?:begins|starts|opens)|ticket sales?",
    re.I | re.S,
)


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"seen": [], "hb_date": ""}


def save_state(state):
    state["seen"] = state["seen"][-200:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def notify(title, body, url=None, priority="urgent", tags="cricket,rotating_light"):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC] {title}: {body}")
        return
    headers = {"Title": title, "Priority": priority, "Tags": tags}
    if url:
        headers["Click"] = url
    r = requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode("utf-8"), headers=headers, timeout=15)
    r.raise_for_status()


def is_hit(text):
    return bool(TEAM.search(text) and VENUE.search(text) and ODI.search(text) and SALE.search(text))


def check_news():
    hits, ok = [], 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    for q in NEWS_QUERIES:
        url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            ok += 1
        except Exception as e:
            print(f"news fail [{q}]: {e}")
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            try:
                pub = parsedate_to_datetime(item.findtext("pubDate"))
            except Exception:
                pub = datetime.now(timezone.utc)
            if pub >= cutoff and is_hit(title):
                hits.append((f"news:{title}", title, link))
    return hits, ok


def check_pages():
    hits, ok = [], 0
    today = datetime.now(IST).strftime("%Y-%m-%d")
    for url in PAGES:
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            ok += 1
        except Exception as e:
            print(f"page fail [{url}]: {e}")
            continue
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        for m in TEAM.finditer(text):
            window = text[max(0, m.start() - 300): m.end() + 300]
            if is_hit(window):
                hits.append((f"page:{url}:{today}", window[:200], url))
                break
    return hits, ok


def main():
    state = load_state()
    news_hits, news_ok = check_news()
    page_hits, page_ok = check_pages()
    total_ok = news_ok + page_ok
    total = len(NEWS_QUERIES) + len(PAGES)
    print(f"sources ok: {total_ok}/{total}; hits: {len(news_hits) + len(page_hits)}")

    for hit_id, snippet, url in news_hits + page_hits:
        if hit_id in state["seen"]:
            continue
        notify("IND vs SL Bengaluru tickets: possible sale", snippet, url)
        state["seen"].append(hit_id)

    # Daily heartbeat (after 8am IST) so a silently broken monitor gets noticed.
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if now.hour >= 8 and state.get("hb_date") != today:
        status = "OK" if total_ok == total else f"DEGRADED ({total_ok}/{total} sources reachable)"
        notify("Ticket watch heartbeat", f"Monitor running: {status}. No sale detected yet.",
               priority="low", tags="white_check_mark" if total_ok == total else "warning")
        state["hb_date"] = today

    save_state(state)
    if total_ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
