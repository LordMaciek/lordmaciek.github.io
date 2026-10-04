#!/usr/bin/env python3
"""Toot new Hugo posts to Mastodon.

Reads Hugo's RSS feed from the build output, compares it with a state file of
already-announced posts, and posts a status for each new one. Stdlib only.

Env vars:
  FEED_FILE          path to the built RSS feed (e.g. feed/index.xml)
  MASTODON_INSTANCE  e.g. https://mastodon.social
  MASTODON_TOKEN     access token with write:statuses scope
  STATE_FILE         default .github/mastodon-posted.txt
  MAX_NEW            safety cap, default 3 (abort if more "new" posts than this)
  DRY_RUN            set to 1 to print instead of posting
"""

import hashlib
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

FEED_FILE = Path(os.environ.get("FEED_FILE", "feed/index.xml"))
STATE = Path(os.environ.get("STATE_FILE", ".github/mastodon-posted.txt"))
MAX_NEW = int(os.environ.get("MAX_NEW", "3"))
DRY = os.environ.get("DRY_RUN") == "1"


def read_items():
    root = ET.parse(FEED_FILE).getroot()
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        if not link:
            continue
        items.append(
            {
                "id": (it.findtext("guid") or link).strip(),
                "title": (it.findtext("title") or "").strip(),
                "link": link,
            }
        )
    return items  # Hugo feeds are newest-first


def compose(item):
    return f"Nowy wpis na Blogu: {item['title']}\n\n{item['link']}"


def toot(text, key):
    if DRY:
        print(f"[dry run] would toot:\n{text}\n")
        return
    instance = os.environ["MASTODON_INSTANCE"].rstrip("/")
    data = urllib.parse.urlencode({"status": text, "visibility": "public"}).encode()
    req = urllib.request.Request(
        f"{instance}/api/v1/statuses",
        data=data,
        headers={
            "Authorization": f"Bearer {os.environ['MASTODON_TOKEN']}",
            # guards against double-posting if a run is retried within an hour
            "Idempotency-Key": hashlib.sha256(key.encode()).hexdigest(),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"Tooted ({r.status}): {text.splitlines()[0]}")


def main():
    items = read_items()

    # First run: record everything already published, toot nothing.
    if not STATE.exists():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text("".join(f"{i['id']}\n" for i in items))
        print(f"Initialised state with {len(items)} existing posts; nothing tooted.")
        return

    seen = set(STATE.read_text().splitlines())
    new = [i for i in items if i["id"] not in seen]

    if not new:
        print("No new posts.")
        return
    if len(new) > MAX_NEW:
        # Usually means permalinks/baseURL changed and every post looks "new".
        sys.exit(
            f"{len(new)} new posts exceeds MAX_NEW={MAX_NEW}; refusing to spam. "
            f"Fix the state file or raise MAX_NEW."
        )

    for item in reversed(new):  # oldest first
        toot(compose(item), item["id"])
        if not DRY:
            with STATE.open("a") as f:  # record after each success
                f.write(item["id"] + "\n")


if __name__ == "__main__":
    main()
