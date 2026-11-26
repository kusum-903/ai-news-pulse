"""AI News Pulse - Streamlit frontend.

Run from the project root folder (same place as db.py / utils.py / config.yaml):
    pip install streamlit pandas
    streamlit run frontend/app.py
"""
import html
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Project root (the folder that contains db.py, collect.py, analyze.py)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import get_connection  # noqa: E402

st.set_page_config(page_title="AI News Pulse", page_icon="📰", layout="wide")


# ---------- helpers ----------
def clean(text):
    """Strip HTML tags and extra whitespace. Safe for None / NaN values."""
    if text is None or pd.isna(text):
        return ""
    text = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fmt_date(value, fmt):
    """Format a date safely; return 'no date' for missing values."""
    return f"{value:{fmt}}" if pd.notna(value) else "no date"


@st.cache_data(ttl=60)
def query(sql, params=None):
    """Run a SELECT and return a DataFrame."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            cols = [d[0] for d in cur.description]
            return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        conn.close()


def run_script(name):
    """Run one of the pipeline scripts (from the project root) and return its output."""
    proc = subprocess.run(
        [sys.executable, name], cwd=ROOT, capture_output=True, text=True
    )
    return (proc.stdout + proc.stderr).strip()


# ---------- connection check ----------
try:
    totals = query("""
        SELECT (SELECT COUNT(*) FROM articles) AS articles,
               (SELECT COUNT(*) FROM stories) AS stories,
               (SELECT COUNT(*) FROM articles WHERE story_id IS NULL) AS pending,
               (SELECT COUNT(DISTINCT source) FROM articles) AS sources
    """).iloc[0]
except Exception as exc:
    st.error(f"Could not connect to the database: {exc}")
    st.info("Check config.yaml and make sure PostgreSQL is running.")
    st.stop()

# ---------- header ----------
st.title("📰 AI News Pulse")
st.caption("Track how AI stories develop across sources.")
c1, c2, c3, c4 = st.columns(4)
with c1.container(border=True):
    st.metric("Articles", int(totals["articles"]))
with c2.container(border=True):
    st.metric("Stories", int(totals["stories"]))
with c3.container(border=True):
    st.metric("Awaiting analysis", int(totals["pending"]))
with c4.container(border=True):
    st.metric("Sources", int(totals["sources"]))

# ---------- sidebar ----------
with st.sidebar:
    st.header("Pipeline")
    st.caption("Run the backend steps from here.")
    if st.button("1. Collect new articles", use_container_width=True):
        with st.spinner("Collecting from RSS feeds..."):
            st.code(run_script("collect.py") or "Done")
        st.cache_data.clear()
    if st.button("2. Analyze (needs Ollama)", use_container_width=True):
        with st.spinner("Clustering and summarizing... this can take a while"):
            st.code(run_script("analyze.py") or "Done")
        st.cache_data.clear()
    if st.button("Refresh view", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

tab_stories, tab_articles, tab_entities = st.tabs(
    ["📈 Stories", "🗞️ Latest articles", "🏷️ Entities"]
)

# ---------- Stories tab ----------
with tab_stories:
    stories = query("""
        SELECT s.id, s.title, s.summary, s.topic, s.first_seen, s.last_updated,
               COUNT(a.id) AS article_count,
               COUNT(DISTINCT a.source) AS source_count
        FROM stories s
        LEFT JOIN articles a ON a.story_id = s.id
        GROUP BY s.id
        ORDER BY s.last_updated DESC
    """)

    if stories.empty:
        st.info("No stories yet. Run Collect, then Analyze from the sidebar.")
    else:
        f1, f2, f3 = st.columns([2, 2, 1])
        search = f1.text_input("Search stories", placeholder="e.g. OpenAI")
        topics = sorted(stories["topic"].dropna().unique())
        picked = f2.multiselect("Topic", topics)
        multi_only = f3.toggle("Developing only", help="Stories with 2+ articles")

        view = stories
        if search:
            mask = (
                view["title"].str.contains(search, case=False, na=False)
                | view["summary"].str.contains(search, case=False, na=False)
            )
            view = view[mask]
        if picked:
            view = view[view["topic"].isin(picked)]
        if multi_only:
            view = view[view["article_count"] >= 2]

        st.write(f"**{len(view)}** stories")
        for _, s in view.head(50).iterrows():
            with st.container(border=True):
                st.subheader(clean(s["title"]) or "Untitled story")
                topic = clean(s["topic"]) or "General"
                updated = fmt_date(s["last_updated"], "%d %b %Y, %H:%M")
                st.caption(
                    f"🏷️ {topic}  ·  "
                    f"{s['article_count']} articles from {s['source_count']} sources  ·  "
                    f"updated {updated}"
                )
                story_summary = clean(s["summary"])
                if story_summary:
                    st.write(story_summary)

                with st.expander("Story timeline"):
                    arts = query("""
                        SELECT source, title, url, published_at, update_delta
                        FROM articles WHERE story_id = %s
                        ORDER BY published_at ASC NULLS LAST, id ASC
                    """, (int(s["id"]),))
                    for _, a in arts.iterrows():
                        when = fmt_date(a["published_at"], "%d %b, %H:%M")
                        st.markdown(
                            f"**{when}** · {a['source']} — [{a['title']}]({a['url']})"
                        )
                        delta = clean(a["update_delta"])
                        if delta:
                            st.caption(f"➜ {delta}")

                    ents = query("""
                        SELECT DISTINCT e.name, e.type
                        FROM entities e
                        JOIN article_entities ae ON ae.entity_id = e.id
                        JOIN articles a ON a.id = ae.article_id
                        WHERE a.story_id = %s
                        ORDER BY e.type, e.name
                    """, (int(s["id"]),))
                    if not ents.empty:
                        st.divider()
                        for etype, grp in ents.groupby("type"):
                            st.markdown(f"**{etype}s:** " + ", ".join(grp["name"]))

# ---------- Latest articles tab ----------
with tab_articles:
    sources = query("SELECT DISTINCT source FROM articles ORDER BY source")["source"].tolist()
    a1, a2 = st.columns([2, 1])
    src = a1.multiselect("Source", sources)
    limit = a2.slider("Show", 10, 100, 30, step=10)

    sql = "SELECT source, title, summary, url, published_at FROM articles"
    params = []
    if src:
        sql += " WHERE source = ANY(%s)"
        params.append(src)
    sql += " ORDER BY published_at DESC NULLS LAST, id DESC LIMIT %s"
    params.append(limit)

    for _, a in query(sql, tuple(params)).iterrows():
        with st.container(border=True):
            st.markdown(f"**[{a['title']}]({a['url']})**")
            when = fmt_date(a["published_at"], "%d %b %Y, %H:%M")
            st.caption(f"{a['source']} · {when}")
            summary = clean(a["summary"])
            if summary:
                st.write(summary[:300] + ("…" if len(summary) > 300 else ""))

# ---------- Entities tab ----------
with tab_entities:
    etype = st.radio("Type", ["Person", "Organization", "Location"], horizontal=True)
    top = query("""
        SELECT e.name, COUNT(DISTINCT ae.article_id) AS mentions
        FROM entities e
        JOIN article_entities ae ON ae.entity_id = e.id
        WHERE e.type = %s
        GROUP BY e.name
        ORDER BY mentions DESC
        LIMIT 15
    """, (etype,))
    if top.empty:
        st.info("No entities yet. They are created when articles are analyzed.")
    else:
        st.bar_chart(top.set_index("name")["mentions"])

    daily = query("""
        SELECT DATE(published_at) AS day, COUNT(*) AS articles
        FROM articles
        WHERE published_at >= NOW() - INTERVAL '30 days'
        GROUP BY day ORDER BY day
    """)
    if not daily.empty:
        st.subheader("Articles per day (last 30 days)")
        st.line_chart(daily.set_index("day")["articles"])