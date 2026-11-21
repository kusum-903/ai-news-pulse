import psycopg2
from psycopg2 import sql

from utils import load_config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS articles (
    id            SERIAL PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    summary       TEXT,
    content       TEXT,
    author        TEXT,
    published_at  TIMESTAMPTZ,
    collected_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_at);
"""

INSERT_SQL = """
    INSERT INTO articles (source, title, url, summary, content, author, published_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (url) DO NOTHING;
"""


def ensure_database():
    """Create the configured news database if it does not exist."""
    cfg = load_config()["database"]
    conn = psycopg2.connect(
        host=cfg["host"], port=cfg["port"], user=cfg["user"],
        password=str(cfg["password"]), dbname="postgres",
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["dbname"],))
    if not cur.fetchone():
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(cfg["dbname"])))
        print(f"[DB] Created database '{cfg['dbname']}'")
    cur.close()
    conn.close()


def get_connection():
    cfg = load_config()["database"]
    return psycopg2.connect(
        host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"],
        user=cfg["user"], password=str(cfg["password"]),
    )


def init_db():
    """Make sure the database and the articles table exist."""
    ensure_database()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    cur.close()
    conn.close()
    print("[DB] Table 'articles' is ready")


def insert_article(cur, source, title, url, summary, content, author, published_at):
    """Insert one article. Returns 1 if saved, 0 if the URL already existed."""
    cur.execute(INSERT_SQL, (source, title, url, summary, content, author, published_at))
    return cur.rowcount