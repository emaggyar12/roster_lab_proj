import json
import re
import threading
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RECRUITR_ROOT = PROJECT_ROOT / "data_pulls" / "sdverse_recruitR" / "recruitR-py"
TFS_BASE_URL = "https://ipa.247sports.com/rdb/v1/"
SPORT_KEY_MBB = 2
SEARCH_LOCK = threading.Lock()
LAST_SEARCH_AT = 0.0


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


def _extract_search_result_urls(html):
    urls = set()
    for match in re.finditer(r"https?://[^\"'<>\\\s]+", html):
        raw_url = unescape(match.group(0))
        parsed = urlparse(raw_url)
        if parsed.netloc.endswith("duckduckgo.com"):
            uddg = parse_qs(parsed.query).get("uddg")
            if uddg:
                raw_url = unquote(uddg[0])
        raw_url = unquote(raw_url)
        if "247sports.com/player/" in raw_url:
            clean = raw_url.split("&")[0].split("?")[0]
            urls.add(clean)
    return urls


def discover_247_profile_url(session, full_name, year, player_key, cache_path):
    global LAST_SEARCH_AT

    full_name = str(full_name or "").strip()
    if not full_name:
        return None

    cache_path = Path(cache_path)
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        if data.get("resolved_url"):
            return data.get("resolved_url")

    query = f'{full_name} {year} 247sports'
    candidates = set()
    search_attempts = []

    with SEARCH_LOCK:
        elapsed = time.monotonic() - LAST_SEARCH_AT
        if elapsed < 2.0:
            time.sleep(2.0 - elapsed)

        for search_url in ["https://duckduckgo.com/html/", "https://search.brave.com/search"]:
            response = None
            for attempt in range(1, 4):
                response = session.get(search_url, params={"q": query}, timeout=30)
                if response.status_code != 429:
                    break
                time.sleep(10 * attempt)
            LAST_SEARCH_AT = time.monotonic()
            if response is None:
                continue
            if response.status_code >= 400:
                search_attempts.append(
                    {
                        "search_url": response.url,
                        "status_code": response.status_code,
                        "candidate_count": 0,
                    }
                )
                continue
            found = _extract_search_result_urls(response.text)
            candidates.update(found)
            search_attempts.append(
                {
                    "search_url": response.url,
                    "status_code": response.status_code,
                    "candidate_count": len(found),
                }
            )
            if found:
                break

    candidates = sorted(candidates)
    player_key_text = str(player_key)
    matching_key = [url for url in candidates if f"-{player_key_text}/" in url]
    college_key = [url for url in matching_key if re.search(r"/college-\d+/?$", url)]
    chosen = college_key[0] if college_key else (matching_key[0] if matching_key else None)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "query": query,
                "resolved_url": chosen,
                "candidates": candidates,
                "search_attempts": search_attempts,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return chosen
