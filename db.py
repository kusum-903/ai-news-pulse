import psycopg2
from psycopg2 import sql

from utils import load_config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stories (
    id                 SERIAL PRIMARY KEY,
    title              TEXT NOT NULL,
    summary            TEXT,
    topic              TEXT,
    first_seen         TIMESTAMPTZ DEFAULT NOW(),
    last_updated       TIMESTAMPTZ DEFAULT NOW(),
    centroid_embedding JSONB
);

CREATE TABLE IF NOT EXISTS articles (
    id            SERIAL PRIMARY KEY,
    story_id      INTEGER REFERENCES stories(id),
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    summary       TEXT,
    content       TEXT,
    author        TEXT,
    published_at  TIMESTAMPTZ,
    collected_at  TIMESTAMPTZ DEFAULT NOW(),
    embedding     JSONB,
    update_delta  TEXT
);

ALTER TABLE articles ADD COLUMN IF NOT EXISTS story_id INTEGER REFERENCES stories(id);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS embedding JSONB;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS update_delta TEXT;

CREATE TABLE IF NOT EXISTS entities (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    type  TEXT NOT NULL,
    UNIQUE (name, type)
);

CREATE TABLE IF NOT EXISTS article_entities (
    article_id INTEGER REFERENCES articles(id) ON DELETE CASCADE,
    entity_id  INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_articles_published ON articles (published_at);
CREATE INDEX IF NOT EXISTS idx_articles_story_id ON articles (story_id);
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
