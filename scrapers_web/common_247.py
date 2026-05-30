import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECRUITR_ROOT = PROJECT_ROOT / "data_pulls" / "sdverse_recruitR" / "recruitR-py"
TFS_BASE_URL = "https://ipa.247sports.com/rdb/v1/"
SPORT_KEY_MBB = 2


def get_247_headers():
    import sys

    if str(RECRUITR_ROOT) not in sys.path:
        sys.path.insert(0, str(RECRUITR_ROOT))

    from recruitR.headers_gen import headers_gen

    return headers_gen()


def request_json(session, url, params, cache_path):
    cache_path = Path(cache_path)
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return data


def normalize_profile_url(profile_url):
    path = str(profile_url or "").strip()
    if not path:
        return None
    if not path.startswith("/"):
        path = "/" + path

    match = re.search(r"-(\d+)$", path.rstrip("/"))
    if not match:
        return "https://247sports.com" + path

    player_key = match.group(1)
    slug = path.rstrip("/").split("/")[-1]
    slug = re.sub(rf"-{player_key}$", "", slug)
    slug = slug.replace(".", "")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
    return f"https://247sports.com/player/{slug}-{player_key}/"


def quantitative_value(value):
    if isinstance(value, list) and value:
        value = value[0]
    if isinstance(value, dict):
        return value.get("value")
    return value


def extract_profile_jsonld_measurables(html):
    scripts = re.findall(
        r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        raw = unescape(script).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            height = quantitative_value(obj.get("height"))
            weight = quantitative_value(obj.get("weight"))
            if height or weight:
                return height, weight

    return None, None


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self):
        return " ".join(self.parts)


def html_to_text(fragment):
    parser = _TextExtractor()
    parser.feed(fragment)
    return re.sub(r"\s+", " ", unescape(parser.text())).strip()


def extract_scouting_report(html):
    match = re.search(
        r'<section\b[^>]*class=["\'][^"\']*\bscouting-report\b[^"\']*["\'][^>]*>'
        r".*?"
        r'<section\b[^>]*class=["\'][^"\']*\bevaluation\b[^"\']*["\'][^>]*>'
        r"(?P<body>.*?)"
        r"</section>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None

    text = html_to_text(match.group("body"))
    return text or None


def fetch_text_cached(session, url, cache_path):
    cache_path = Path(cache_path)
    if cache_path.exists():
        return cache_path.read_text(), 200

    response = session.get(url, timeout=30)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if response.status_code == 200:
        cache_path.write_text(response.text)
    return response.text, response.status_code
