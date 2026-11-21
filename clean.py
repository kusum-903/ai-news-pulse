import html
import re
from urllib.parse import urlsplit

import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import create_engine

from utils import load_config


def get_engine():
    c = load_config()["database"]
    url = (
        f"postgresql+psycopg2://{c['user']}:{c['password']}"
        f"@{c['host']}:{c['port']}/{c['dbname']}"
    )
    return create_engine(url)


# ---------- cleaning helpers ----------
def clean_text(value):
    """Remove HTML tags, decode &amp; etc., collapse extra spaces."""
    if value is None or pd.isna(value):
        return None
    text = BeautifulSoup(str(value), "html.parser").get_text(" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def title_key(title):
    """Lowercase, letters and digits only, so tiny differences don't matter."""
    return re.sub(r"[^a-z0-9]+", " ", str(title).lower()).strip()


def url_key(url):
    """Drop ?utm=... tracking parts, #fragments and trailing slash."""
    p = urlsplit(str(url).strip())
    return f"{p.netloc.lower()}{p.path.rstrip('/')}"


# ---------- main ----------
def clean():
    engine = get_engine()
    df = pd.read_sql("SELECT * FROM articles", engine)
    print(f"Raw rows: {len(df)}")

    # 1. Clean text columns
    for col in ["title", "summary", "content", "author"]:
        df[col] = df[col].apply(clean_text)

    # 2. Fix dates (UTC); if missing, use the collection time
    df["published_at"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    df["collected_at"] = pd.to_datetime(df["collected_at"], utc=True, errors="coerce")
    df["published_at"] = df["published_at"].fillna(df["collected_at"])

    # 3. Remove rows with no title
    df = df.dropna(subset=["title"]).copy()

    # 4. Build comparison keys
    df["title_key"] = df["title"].apply(title_key)
    df["url_key"] = df["url"].apply(url_key)

    # 5. Flag duplicates (the earliest copy is kept as the original)
    df = df.sort_values(["published_at", "id"]).reset_index(drop=True)
    same_outlet_repost = df.duplicated(subset=["source", "title_key"], keep="first")
    same_link = df.duplicated(subset=["url_key"], keep="first")
    df["is_duplicate"] = same_outlet_repost | same_link

    # 6. Save to a new table
    df.to_sql("articles_clean", engine, if_exists="replace", index=False)

    total = len(df)
    dups = int(df["is_duplicate"].sum())
    print(f"Clean rows saved: {total}")
    print(f"Flagged as duplicates: {dups}")
    print(f"Unique articles: {total - dups}")


if __name__ == "__main__":
    clean()