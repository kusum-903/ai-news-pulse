import pandas as pd
import numpy as np

from db import get_connection


def load_articles_df(days=30):
    """Load recent articles joined with their parent story topic and title."""
    conn = get_connection()
    cur = conn.cursor()
    query = """
        SELECT
            a.id AS article_id,
            a.story_id,
            a.source,
            a.title,
            a.url,
            a.published_at,
            a.update_delta,
            s.title AS story_title,
            s.topic,
            s.summary AS story_summary
        FROM articles a
        LEFT JOIN stories s ON a.story_id = s.id
        WHERE a.published_at >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY a.published_at ASC
    """
    cur.execute(query, (days,))
    cols = [desc[0] for desc in cur.description]
    df = pd.DataFrame(cur.fetchall(), columns=cols)
    cur.close()
    conn.close()

    if not df.empty:
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)
        df["date"] = df["published_at"].dt.date
        df["topic"] = df["topic"].fillna("Uncategorized")
    return df
    


def get_daily_volume(df):
    """Count total articles published per day."""
    if df.empty:
        return pd.DataFrame(columns=["date", "article_count"])
    return (
        df.groupby("date")
        .size()
        .reset_index(name="article_count")
        .sort_values("date")
    )


def get_topic_trends(df):
    """Count daily articles per topic."""
    if df.empty:
        return pd.DataFrame(columns=["date", "topic", "article_count"])
    return (
        df.groupby(["date", "topic"])
        .size()
        .reset_index(name="article_count")
        .sort_values(["date", "article_count"], ascending=[True, False])
    )


def detect_coverage_spikes(df, window=7, z_threshold=2.0):
    """Flag topics where daily volume exceeds rolling mean + (z_threshold * std)."""
    trends = get_topic_trends(df)
    trends = trends[trends["topic"] != "Uncategorized"]
    if trends.empty:
        return pd.DataFrame(columns=["date", "topic", "article_count", "rolling_mean", "z_score"])

    spikes = []
    for topic, group in trends.groupby("topic"):
        group = group.sort_values("date").copy()
        group["rolling_mean"] = group["article_count"].rolling(window=window, min_periods=2).mean()
        group["rolling_std"] = group["article_count"].rolling(window=window, min_periods=2).std().fillna(0)

        # Avoid dividing by zero when daily counts are flat
        group["z_score"] = np.where(
            group["rolling_std"] > 0,
            (group["article_count"] - group["rolling_mean"]) / group["rolling_std"],
            0.0,
        )
        flagged = group[group["z_score"] >= z_threshold]
        if not flagged.empty:
            spikes.append(flagged[["date", "topic", "article_count", "rolling_mean", "z_score"]])

    if not spikes:
        return pd.DataFrame(columns=["date", "topic", "article_count", "rolling_mean", "z_score"])
    return pd.concat(spikes, ignore_index=True).sort_values("z_score", ascending=False)


def get_source_comparison(df):
    """Compare news sources by total articles, unique stories, and active days."""
    if df.empty:
        return pd.DataFrame(columns=["source", "articles", "unique_stories", "topics_covered"])
    return (
        df.groupby("source")
        .agg(
            articles=("article_id", "count"),
            unique_stories=("story_id", "nunique"),
            topics_covered=("topic", "nunique"),
        )
        .reset_index()
        .sort_values("articles", ascending=False)
    )


if __name__ == "__main__":
    data = load_articles_df()
    print(f"Loaded {len(data)} articles.")
    print("\n--- Top Sources ---")
    print(get_source_comparison(data).head(5))
    print("\n--- Coverage Spikes ---")
    spikes = detect_coverage_spikes(data)
    print(spikes if not spikes.empty else "No statistical spikes detected yet (collect a few days of data).")