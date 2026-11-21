import calendar
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_ai_pattern(keywords):
    """Compile keywords into one regex. Whole-word match, so 'ai' won't match 'said'."""
    parts = [r"\b" + re.escape(k) + r"s?\b" for k in keywords]
    return re.compile("|".join(parts), re.IGNORECASE)


def is_ai_related(pattern, title, summary):
    return bool(pattern.search(f"{title} {summary or ''}"))


def parse_date(entry):
    """Return a timezone-aware UTC datetime, or None if the feed has no date."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return None


def get_content(entry):
    if entry.get("content"):
        return entry["content"][0].get("value")
    return None