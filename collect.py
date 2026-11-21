import feedparser

from db import init_db, get_connection, insert_article
from utils import (
    load_config, build_ai_pattern, is_ai_related, parse_date, get_content,
)


def collect():
    config = load_config()
    feeds = config["feeds"]
    user_agent = config["user_agent"]
    ai_pattern = build_ai_pattern(config["ai_keywords"])

    init_db()  # creates the database and table if missing

    conn = get_connection()
    cur = conn.cursor()
    total_new = 0

    for feed_cfg in feeds:
        source = feed_cfg["name"]
        url = feed_cfg["url"]
        ai_only = feed_cfg.get("ai_only", False)

        try:
            feed = feedparser.parse(url, agent=user_agent)

            if not feed.entries:
                print(f"[SKIP] {source}: no entries (check URL or feed may be down)")
                continue

            new_count = 0
            for entry in feed.entries:
                title = entry.get("title")
                link = entry.get("link")
                if not title or not link:
                    continue

                summary = entry.get("summary")
                if not ai_only and not is_ai_related(ai_pattern, title, summary):
                    continue

                new_count += insert_article(
                    cur,
                    source,
                    title.strip(),
                    link.strip(),
                    summary,
                    get_content(entry),
                    entry.get("author"),
                    parse_date(entry),
                )

            conn.commit()
            total_new += new_count
            print(f"[OK]   {source}: {new_count} new / {len(feed.entries)} fetched")

        except Exception as e:
            conn.rollback()
            print(f"[FAIL] {source}: {e}")

    cur.close()
    conn.close()
    print(f"\nDone. Total new articles saved: {total_new}")


if __name__ == "__main__":
    collect()