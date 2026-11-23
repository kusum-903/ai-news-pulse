import json
import numpy as np
import requests
from sentence_transformers import SentenceTransformer

from db import get_connection

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
SIMILARITY_THRESHOLD = 0.75
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"  # Change to "llama3.2" if you want faster CPU runs


def cosine_similarity(vec_a, vec_b):
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def build_article_text(title, summary, content):
    snippet = (summary or content or "")[:800]
    return f"Title: {title}\nText: {snippet}".strip()


def call_ollama_json(prompt):
    """Send a prompt to local Ollama and parse the JSON response."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        raw_text = resp.json().get("response", "{}")
        return json.loads(raw_text)
    except Exception as exc:
        print(f"[WARN] Ollama call failed: {exc}")
        return {}


def extract_new_story_info(article_text):
    prompt = f"""Analyze this news article and return ONLY valid JSON with these keys:
- "topic": a short 1 to 3 word category (e.g., "AI Regulation", "Chip Hardware", "Model Release")
- "summary": a concise 2-sentence summary of the event
- "entities": an object with lists for "people", "organizations", and "locations"

Article:
{article_text}
"""
    return call_ollama_json(prompt)


def extract_story_evolution(current_summary, article_text):
    prompt = f"""Compare the new article against the existing story summary and return ONLY valid JSON with these keys:
- "update_delta": 1 or 2 sentences explaining what new facts, reactions, or developments appear in this article
- "updated_summary": a refreshed 2 to 3 sentence summary combining the old summary and the new update
- "entities": an object with lists for "people", "organizations", and "locations" mentioned in the new article

Existing Summary:
{current_summary}

New Article:
{article_text}
"""
    return call_ollama_json(prompt)


def save_entities(cur, article_id, entities_dict):
    if not isinstance(entities_dict, dict):
        return

    type_map = {
        "people": "Person",
        "organizations": "Organization",
        "locations": "Location",
    }
    for key, entity_type in type_map.items():
        names = entities_dict.get(key, [])
        if not isinstance(names, list):
            continue
        for name in names:
            clean_name = str(name).strip()
            if not clean_name:
                continue
            cur.execute(
                """
                INSERT INTO entities (name, type)
                VALUES (%s, %s)
                ON CONFLICT (name, type) DO NOTHING
                """,
                (clean_name, entity_type),
            )
            cur.execute(
                "SELECT id FROM entities WHERE name = %s AND type = %s",
                (clean_name, entity_type),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    INSERT INTO article_entities (article_id, entity_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (article_id, row[0]),
                )


def analyze_articles():
    print(f"[AI] Loading embedding model: {EMBEDDING_MODEL}")
    model = SentenceTransformer(EMBEDDING_MODEL)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, summary, centroid_embedding
        FROM stories
        WHERE last_updated >= NOW() - INTERVAL '7 days'
          AND centroid_embedding IS NOT NULL
    """)
    active_stories = [
        {"id": row[0], "title": row[1], "summary": row[2], "embedding": row[3]}
        for row in cur.fetchall()
    ]

    cur.execute("""
        SELECT id, title, summary, content, published_at
        FROM articles
        WHERE story_id IS NULL
          AND published_at >= NOW() - INTERVAL '30 days'
        ORDER BY published_at ASC NULLS LAST
    """)
    articles = cur.fetchall()

    if not articles:
        print("[AI] No new articles to analyze.")
        cur.close()
        conn.close()
        return

    new_stories = 0
    matched_articles = 0

    for idx, (article_id, title, summary, content, published_at) in enumerate(articles, 1):
        print(f"[AI] Processing {idx}/{len(articles)}: {title[:60]}...")
        text = build_article_text(title, summary, content)
        embedding = model.encode(f"{title}. {(summary or content or '')[:300]}").tolist()

        best_story = None
        best_score = 0.0
        for story in active_stories:
            score = cosine_similarity(embedding, story["embedding"])
            if score > best_score:
                best_score = score
                best_story = story

        if best_story and best_score >= SIMILARITY_THRESHOLD:
            story_id = best_story["id"]
            evo = extract_story_evolution(best_story["summary"], text)
            update_delta = evo.get("update_delta", "Follow-up coverage.")
            updated_summary = evo.get("updated_summary", best_story["summary"])

            cur.execute(
                """
                UPDATE articles
                SET story_id = %s, embedding = %s, update_delta = %s
                WHERE id = %s
                """,
                (story_id, json.dumps(embedding), update_delta, article_id),
            )
            cur.execute(
                """
                UPDATE stories
                SET summary = %s, last_updated = GREATEST(last_updated, COALESCE(%s, NOW()))
                WHERE id = %s
                """,
                (updated_summary, published_at, story_id),
            )
            save_entities(cur, article_id, evo.get("entities", {}))
            best_story["summary"] = updated_summary
            matched_articles += 1
        else:
            info = extract_new_story_info(text)
            story_summary = info.get("summary", summary or title)
            story_topic = info.get("topic", "General AI")

            cur.execute(
                """
                INSERT INTO stories (title, summary, topic, first_seen, last_updated, centroid_embedding)
                VALUES (%s, %s, %s, COALESCE(%s, NOW()), COALESCE(%s, NOW()), %s)
                RETURNING id
                """,
                (title, story_summary, story_topic, published_at, published_at, json.dumps(embedding)),
            )
            story_id = cur.fetchone()[0]

            cur.execute(
                """
                UPDATE articles
                SET story_id = %s, embedding = %s, update_delta = %s
                WHERE id = %s
                """,
                (story_id, json.dumps(embedding), "Initial report.", article_id),
            )
            save_entities(cur, article_id, info.get("entities", {}))

            active_stories.append({
                "id": story_id,
                "title": title,
                "summary": story_summary,
                "embedding": embedding,
            })
            new_stories += 1

        # Commit after every article so progress is saved if you stop the script
        conn.commit()

    cur.close()
    conn.close()
    print(f"[AI] Done. Created {new_stories} stories and matched {matched_articles} follow-up articles.")


if __name__ == "__main__":
    analyze_articles()