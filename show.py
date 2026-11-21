"""Read-only viewer: latest articles from ALL sources.

    python show_all.py                   latest 3 from every source
    python show_all.py -n 5              latest 5 from every source
    python show_all.py -s "BBC World"    only one source
    python show_all.py --clean           use articles_clean, skip duplicates
"""
import argparse
import html
import re
import sys
import unicodedata

from db import get_connection


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return "".join(
        char for char in text
        if unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


ap = argparse.ArgumentParser()
ap.add_argument("-n", type=int, default=3, help="articles to show per source")
ap.add_argument("-s", "--source", help="only this source name")
ap.add_argument("--clean", action="store_true",
                help="read articles_clean and hide duplicates")
args = ap.parse_args()

table = "articles_clean" if args.clean else "articles"
conditions, params = [], []
if args.clean:
    conditions.append("is_duplicate = FALSE")
if args.source:
    conditions.append("source = %s")
    params.append(args.source)
where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

query = f"""
    SELECT source, title, summary, published_at, url FROM (
        SELECT source, title, summary, published_at, url, id,
               ROW_NUMBER() OVER (
                   PARTITION BY source
                   ORDER BY published_at DESC NULLS LAST, id DESC
               ) AS rn
        FROM {table}
        {where}
    ) t
    WHERE rn <= %s
    ORDER BY source, published_at DESC NULLS LAST, id DESC
"""
params.append(args.n)

conn = get_connection()
with conn.cursor() as cur:
    cur.execute(query, params)
    rows = cur.fetchall()

    cur.execute(f"SELECT source, COUNT(*) FROM {table} {where.replace('rn', 'rn')} "
                f"GROUP BY source ORDER BY source", params[:-1])
    counts = dict(cur.fetchall())
conn.close()

if not rows:
    print(f"No articles in '{table}' yet. Run: python collect.py"
          + ("  then  python clean.py" if args.clean else ""))

current = None
for source, title, summary, published, url in rows:
    if source != current:
        current = source
        print("=" * 70)
        print(f"{source}  ({counts.get(source, 0)} articles in database)")
        print("=" * 70)
    print(f"- {title}")
    if clean(summary):
        print(f"    {clean(summary)[:160]}")
    print(f"    {published or 'no date'}  |  {url}\n")

print(f"Sources shown: {len(counts)}  |  Total articles in '{table}': {sum(counts.values())}")