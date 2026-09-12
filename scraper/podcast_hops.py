#!/usr/bin/env python3
"""Scan interview-podcast RSS feeds and build a guest-appearance graph.

People are nodes. An undirected edge means they appeared together on an
episode (typically host–guest, or co-guests). The frontend uses this JSON
to find the shortest path between any two people.

Guest names come from spaCy NER (en_core_web_sm, CPU-friendly) merged with
per-show title parsers. Previous runs are stored in episodes.json so weekly
jobs only extract newly seen RSS items.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "podcast-hops" / "graph.json"
DEFAULT_STATE = ROOT / "docs" / "podcast-hops" / "episodes.json"
SPACY_MODEL = "en_core_web_sm"

USER_AGENT = "podcast-hops/1.0 (+https://007vasy.github.io/podcast-hops)"
REQUEST_TIMEOUT = 45
RETRIES = 3

DEFAULT_FROM = "Eric Smith"
DEFAULT_TO = "Chiara Marletto"

# Title / particle noise that should never become a person node.
STOP_FIRST = {
    "a", "an", "the", "how", "why", "what", "when", "where", "who", "is", "are",
    "this", "that", "ask", "trailer", "episode", "preview", "bonus", "live",
    "introducing", "welcome", "update", "news", "review", "reaction", "inside",
    "intro", "introduction", "special", "roundtable", "ama", "q&a", "qa",
    "highlights", "recap", "clip", "shorts", "best", "top", "new", "our",
    "your", "we", "i", "on", "in", "of", "from", "for", "with", "and",
    "worldviews", "nature", "physics", "mapping", "fix", "work", "law",
    "contrarian", "both", "all", "hollywood", "civilization", "economics",
    "history", "gravity", "money", "did", "constructor", "thermodynamics",
    "quantum", "ai", "agi", "announcing", "watch", "listen", "re", "part",
}

STOP_NAMES = {
    "ask me anything", "worldviews", "special episode", "bonus episode",
    "constructor theory", "fabric of reality", "beginning of infinity",
    "science of can and can't", "theories of everything", "open source",
    "machine learning", "artificial intelligence", "general relativity",
    "quantum mechanics", "quantum gravity", "origin of life",
}

# Canonical display names for known aliases / punctuation variants.
ALIASES = {
    "d. eric smith": "Eric Smith",
    "d eric smith": "Eric Smith",
    "eric d. smith": "Eric Smith",
    "chiara marletto": "Chiara Marletto",
    "brett robert hall": "Brett Hall",
    "sara imari walker": "Sara Walker",
    "sara i. walker": "Sara Walker",
    "lee cronin": "Leroy Cronin",
    "leroy cronin": "Leroy Cronin",
    "dwarkesh": "Dwarkesh Patel",
    "curt": "Curt Jaimungal",
    "sean m. carroll": "Sean Carroll",
    "allison duettman": "Allison Duettmann",
    "ricardo lopes": "Ricardo Lopes",
    "tim ferris": "Tim Ferriss",
    "timothy ferriss": "Tim Ferriss",
}

PODCASTS = [
    {
        "id": "dwarkesh",
        "name": "Dwarkesh Podcast",
        "rss": "https://apple.dwarkesh-podcast.workers.dev/feed.rss",
        "hosts": ["Dwarkesh Patel"],
        "parser": "dwarkesh",
    },

    {
        "id": "toe",
        "name": "Theories of Everything",
        "rss": "https://feeds.megaphone.fm/TOE4643226064",
        "hosts": ["Curt Jaimungal"],
        "parser": "colon",
    },
    {
        "id": "dissenter",
        "name": "The Dissenter",
        "rss": "https://anchor.fm/s/822ba20/podcast/rss",
        "hosts": ["Ricardo Lopes"],
        "parser": "dissenter",
    },
    {
        "id": "jim-rutt",
        "name": "The Jim Rutt Show",
        "rss": "https://jimruttshow.blubrry.net/feed/podcast/",
        "hosts": ["Jim Rutt"],
        "parser": "jimrutt",
    },
    {
        "id": "tokcast",
        "name": "ToKCast",
        "rss": "https://feed.podbean.com/brettroberthall/feed.xml",
        "hosts": ["Brett Hall"],
        "parser": "tokcast",
    },
    {
        "id": "lex-fridman",
        "name": "Lex Fridman Podcast",
        "rss": "https://lexfridman.com/feed/podcast/",
        "hosts": ["Lex Fridman"],
        "parser": "lex",
    },
    {
        "id": "mindscape",
        "name": "Mindscape",
        "rss": "https://rss.art19.com/sean-carrolls-mindscape",
        "hosts": ["Sean Carroll"],
        "parser": "mindscape",
    },
    {
        "id": "cwt",
        "name": "Conversations with Tyler",
        "rss": "https://rss.libsyn.com/shows/137081/destinations/850607.xml",
        "hosts": ["Tyler Cowen"],
        "parser": "cwt",
    },
    {
        "id": "foresight",
        "name": "Foresight Institute Radio",
        "rss": "https://feeds.acast.com/public/shows/6527e4f1d40c9700125f42de",
        "hosts": ["Allison Duettmann"],
        "parser": "pipe",
    },
    {
        "id": "existential-hope",
        "name": "Existential Hope",
        "rss": "https://feeds.acast.com/public/shows/683f0798c966cde736234a29",
        "hosts": ["Allison Duettmann"],
        "parser": "pipe",
    },
    {
        "id": "mlst",
        "name": "Machine Learning Street Talk",
        "rss": "https://anchor.fm/s/1e4a0eac/podcast/rss",
        "hosts": ["Tim Scarfe"],
        "parser": "emdash_end",
    },
    {
        "id": "fallible-animals",
        "name": "Fallible Animals",
        "rss": "https://anchor.fm/s/e9f811c/podcast/rss",
        "hosts": ["Logan Chipkin"],
        "parser": "with_or_colon",
    },
    {
        "id": "conjecture",
        "name": "Conjecture Institute",
        "rss": "https://feed.podbean.com/conjectureinstitute/feed.xml",
        "hosts": ["Logan Chipkin"],
        "parser": "with_or_colon",
    },
    {
        "id": "complexity",
        "name": "COMPLEXITY",
        "rss": "https://feeds.simplecast.com/OzDH_At2",
        "hosts": [],
        "parser": "with_or_colon",
    },
    {
        "id": "wtf4cities",
        "name": "WTF4Cities",
        "rss": "https://anchor.fm/s/4e573598/podcast/rss",
        "hosts": ["Fanni Melles"],
        "parser": "wtf4cities",
    },
    {
        "id": "tim-ferriss",
        "name": "The Tim Ferriss Show",
        "rss": "https://rss.art19.com/tim-ferriss-show",
        "hosts": ["Tim Ferriss"],
        "parser": "ferriss",
    },
]


ITEM_SPLIT_RE = re.compile(r"<item[\s>]", re.I)
TITLE_RE = re.compile(
    r"<title(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
    re.I | re.S,
)
LINK_RE = re.compile(
    r"<link(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>",
    re.I | re.S,
)
PERSON_TAG_RE = re.compile(
    r"<podcast:person[^>]*\bname=['\"]([^'\"]+)['\"]",
    re.I,
)
GUID_RE = re.compile(
    r"<guid(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</guid>",
    re.I | re.S,
)
DESC_RE = re.compile(
    r"<description(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>",
    re.I | re.S,
)
SUMMARY_RE = re.compile(
    r"<itunes:summary(?:\s[^>]*)?>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</itunes:summary>",
    re.I | re.S,
)
EP_PREFIX_RE = re.compile(r"^(?:#\s*\d+\s*|EP\s*\d+\s*|\d+[IRPB]?_)", re.I)

# "First Last", "D. Eric Smith", "Jim Al-Khalili", "Sara Imari Walker"
NAME_TOKEN_RE = re.compile(
    r"^(?:"
    r"[A-Z][a-zà-öø-ÿ]+(?:['’][A-Z]?[a-zà-öø-ÿ]+)?(?:-[A-Z][a-zà-öø-ÿ]+)?|"
    r"[A-Z]\.|"
    r"[A-Z]{2,4}|"  # DHH, AGI-ish initials; filtered later if not a known short name
    r"de|da|di|del|della|van|von|le|la|bin|al|du|st\.?|the"
    r")$"
)


def slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def clean_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def canonical_name(name: str) -> str:
    name = clean_text(name)
    name = re.sub(r"\s+", " ", name).strip(" .,-–—|/")
    name = re.sub(
        r"^(dr|prof|professor|sir|dame|rev|physicist|philosopher|author|journalist|scientist|researcher|historian)\.?\s+",
        "",
        name,
        flags=re.I,
    )
    name = re.sub(r",?\s+(ph\.?d\.?|md|mbe|obe|frs|obe)$", "", name, flags=re.I)
    key = name.lower().replace("’", "'")
    return ALIASES.get(key, name)


def looks_like_name(text: str) -> bool:
    if not text:
        return False
    text = clean_text(text).strip(" .,-–—|/:;()[]")
    if not text or text.lower() in STOP_NAMES:
        return False
    if re.search(r"\d", text):
        return False
    if len(text) > 60:
        return False
    # Strip a trailing parenthetical role: "Eric Smith (Santa Fe Institute)"
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip()
    parts = text.split()
    if len(parts) < 2 or len(parts) > 5:
        return False
    if parts[0].lower().rstrip(":") in STOP_FIRST:
        return False
    if any(w.lower() in {"chapter", "episode", "podcast", "interview", "readings"} for w in parts):
        return False
    named = 0
    for part in parts:
        token = part.strip(".,")
        if not NAME_TOKEN_RE.match(token) and token.lower() not in {
            "de", "da", "di", "del", "della", "van", "von", "le", "la", "bin", "al", "du", "st", "st.", "the",
        }:
            return False
        if token[:1].isupper():
            named += 1
    return named >= 2


def split_people(blob: str) -> list[str]:
    blob = clean_text(blob)
    blob = re.sub(r"\s*\([^)]*\)\s*", " ", blob)
    blob = blob.replace(" / ", " & ")
    parts = re.split(r"\s*(?:,|\s+&\s+|\s+and\s+|\s+x\s+)\s*", blob, flags=re.I)
    names = []
    for part in parts:
        part = part.strip(" .,-–—|/:;")
        name = canonical_name(part)
        if looks_like_name(name) or _loose_person_name(name):
            names.append(name)
    return names


def parse_dwarkesh(title: str) -> list[str]:
    m = re.match(r"^(.+?)\s+[—–-]\s+.+$", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_colon(title: str) -> list[str]:
    m = re.match(r"^([^:]+):\s+\S", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_dissenter(title: str) -> list[str]:
    m = re.match(r"#\d+\s+(.+?)\s*[:–-]\s+\S", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_jimrutt(title: str) -> list[str]:
    m = re.match(
        r"EP\s*\d+\s+(?:Worldviews:\s*)?(.+?)\s+on\s+\S",
        title,
        flags=re.I,
    )
    if m:
        return split_people(m.group(1))
    m = re.match(r"EP\s*\d+\s+Worldviews:\s*(.+)$", title, flags=re.I)
    if m:
        return split_people(m.group(1))
    with_m = re.search(
        r"\bwith\s+([A-Z][A-Za-zÀ-öø-ÿ.'’\-]+(?:\s+[A-Z][A-Za-zÀ-öø-ÿ.'’\-]+){1,3})",
        title,
    )
    return split_people(with_m.group(1)) if with_m else []


def parse_lex(title: str) -> list[str]:
    m = re.match(r"#\d+\s*[–-]\s*([^:]+):\s+\S", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_mindscape(title: str) -> list[str]:
    if re.search(r"ask me anything", title, re.I):
        return []
    m = re.match(r"^\d+\s*\|\s*(.+?)\s+on\s+\S", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_cwt(title: str) -> list[str]:
    m = re.match(r"^(.+?)\s+on\s+\S", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_pipe(title: str) -> list[str]:
    title = re.sub(r"^Existential Hope Podcast:\s*", "", title, flags=re.I)
    names: list[str] = []
    for part in title.split("|"):
        part = re.sub(r"@.*$", "", part).strip()
        part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()
        names.extend(split_people(part))
    seen = set()
    out = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def parse_emdash_end(title: str) -> list[str]:
    m = re.search(r"[—–-]\s*([^-—–]+)$", title)
    if not m:
        return []
    return split_people(m.group(1))


def parse_tokcast(title: str) -> list[str]:
    m = re.match(r"Ep\.?\s*:?\s*\d+\s*:?\s*(.+)$", title, flags=re.I)
    if not m:
        with_m = re.search(
            r"\bwith\s+([A-Z][A-Za-zÀ-öø-ÿ.'’\-]+(?:\s+[A-Z][A-Za-zÀ-öø-ÿ.'’\-]+){1,3})",
            title,
        )
        return split_people(with_m.group(1)) if with_m else []
    rest = m.group(1).strip()
    bookish = re.search(
        r"Chapter|Fabric of Reality|Beginning of Infinity|Readings|"
        r"Science of Can|retrospective|comments on|explains|answers a question|"
        r"Newsletter|weekend of Twitter",
        rest,
        flags=re.I,
    )
    if bookish:
        with_m = re.search(
            r"\bwith\s+([A-Z][A-Za-zÀ-öø-ÿ.'’\-]+(?:\s+[A-Z][A-Za-zÀ-öø-ÿ.'’\-]+){1,3})\s*$",
            rest,
        )
        return split_people(with_m.group(1)) if with_m else []
    rest = re.sub(r"\s*\(.*\)$", "", rest).strip().strip(" .")
    if looks_like_name(rest):
        return [canonical_name(rest)]
    with_m = re.search(
        r"\bwith\s+([A-Z][A-Za-zÀ-öø-ÿ.'’\-]+(?:\s+[A-Z][A-Za-zÀ-öø-ÿ.'’\-]+){1,3})",
        rest,
    )
    return split_people(with_m.group(1)) if with_m else []


def parse_with_or_colon(title: str) -> list[str]:
    names = parse_colon(title)
    if names:
        return names
    with_m = re.findall(
        r"\bwith\s+([A-Z][A-Za-zÀ-öø-ÿ.'’\-]+(?:\s+[A-Z][A-Za-zÀ-öø-ÿ.'’\-]+){1,3})",
        title,
    )
    found: list[str] = []
    for blob in with_m:
        found.extend(split_people(blob))
    return found


def _wtf_interview_name(blob: str) -> list[str]:
    blob = blob.split(",")[0].strip()
    particles = {"de", "da", "di", "del", "della", "van", "von", "le", "la", "bin", "al", "du", "st", "st.", "the"}

    def one(chunk: str) -> list[str]:
        name = canonical_name(chunk)
        if looks_like_name(name):
            return [name]
        parts = name.split()
        if not (2 <= len(parts) <= 5) or parts[0].lower() in STOP_FIRST:
            return []
        for part in parts:
            token = part.strip(".,")
            if re.fullmatch(r"[A-Z]", token) or token.lower() in particles:
                continue
            if NAME_TOKEN_RE.match(token):
                continue
            if re.fullmatch(r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-öø-ÿĀ-ž'’\-]+", token):
                continue
            return []
        return [name]

    names: list[str] = []
    for chunk in re.split(r"\s+and\s+", blob, flags=re.I):
        names.extend(one(chunk))
    return names


def parse_ferriss(title: str) -> list[str]:
    if re.search(r"Random Show|Q&A with Tim|Guided Meditation", title, re.I):
        return []
    m = re.match(r"#\d+:\s*(.+)$", title)
    if not m:
        return []
    rest = m.group(1)
    parts = re.split(r"\s+[—–]\s+", rest, maxsplit=1)
    left = parts[0].strip()
    names = split_people(left)
    if not names:
        stripped = canonical_name(left)
        if looks_like_name(stripped) or _loose_person_name(stripped):
            names = [stripped]
    if names:
        return names
    if len(parts) == 2:
        right = re.sub(r",?\s+and More\b.*$", "", parts[1], flags=re.I)
        names = split_people(right)
        if names:
            return names
    with_m = re.search(r"\bwith\s+(.+?)(?:\s*\(|$)", rest)
    if with_m:
        blob = re.sub(r"\s+and\s+", ", ", with_m.group(1), flags=re.I)
        return split_people(blob)
    return []


def parse_wtf4cities(title: str) -> list[str]:
    if re.search(r"\btrailer\b", title, re.I):
        return []
    m = re.match(r"^\d+I_(.+)$", title)
    if m:
        return _wtf_interview_name(m.group(1))
    m = re.match(r"^\d+[PB]_(.+)$", title)
    if not m:
        return []
    with_m = re.search(r"\bwith\s+(.+)$", m.group(1), flags=re.I)
    if not with_m:
        return []
    blob = re.sub(r"\s+and\s+", ", ", with_m.group(1), flags=re.I)
    return split_people(blob)


PARSERS = {
    "dwarkesh": parse_dwarkesh,
    "colon": parse_colon,
    "dissenter": parse_dissenter,
    "jimrutt": parse_jimrutt,
    "lex": parse_lex,
    "mindscape": parse_mindscape,
    "cwt": parse_cwt,
    "pipe": parse_pipe,
    "emdash_end": parse_emdash_end,
    "tokcast": parse_tokcast,
    "with_or_colon": parse_with_or_colon,
    "wtf4cities": parse_wtf4cities,
    "ferriss": parse_ferriss,
}


def load_spacy():
    try:
        import spacy
    except ImportError:
        print("spaCy not installed; falling back to title parsers only", file=sys.stderr)
        return None
    try:
        return spacy.load(SPACY_MODEL, disable=["parser", "lemmatizer"])
    except OSError:
        print(f"spaCy model {SPACY_MODEL} missing; falling back to title parsers only", file=sys.stderr)
        return None


def ner_people(nlp, text: str) -> list[str]:
    if not nlp or not text:
        return []
    names = []
    for ent in nlp(text).ents:
        if ent.label_ != "PERSON":
            continue
        raw = EP_PREFIX_RE.sub("", ent.text).strip(" .,-–—|/:;")
        raw = re.sub(r"\s+", " ", raw)
        name = canonical_name(raw)
        if looks_like_name(name) or _loose_person_name(name):
            names.append(name)
    return names


def _loose_person_name(name: str) -> bool:
    parts = name.split()
    if not (2 <= len(parts) <= 5) or parts[0].lower() in STOP_FIRST:
        return False
    if re.search(r"\d", name) or name.lower() in STOP_NAMES:
        return False
    particles = {"de", "da", "di", "del", "della", "van", "von", "le", "la", "bin", "al", "du", "st", "st.", "the"}
    for part in parts:
        token = part.strip(".,")
        if re.fullmatch(r"[A-Z]", token) or token.lower() in particles:
            continue
        if NAME_TOKEN_RE.match(token):
            continue
        if re.fullmatch(r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-öø-ÿĀ-ž'’\-]+", token):
            continue
        return False
    return True


def episode_key(podcast_id: str, item: dict) -> str:
    ident = item.get("guid") or item.get("url") or item.get("title") or ""
    return f"{podcast_id}::{ident}"


def load_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    episodes = data.get("episodes")
    if isinstance(episodes, dict):
        return episodes
    if isinstance(episodes, list):
        out = {}
        for rec in episodes:
            key = rec.get("id") or episode_key(rec.get("podcastId", ""), rec)
            out[key] = rec
        return out
    return {}


def save_state(path: Path, episodes: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "episodeCount": len(episodes),
        "episodes": dict(sorted(episodes.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fetch_url(url: str) -> str:
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
            with urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_err}")


def parse_items(xml_text: str) -> list[dict]:
    chunks = ITEM_SPLIT_RE.split(xml_text)
    items = []
    for chunk in chunks[1:]:
        title_m = TITLE_RE.search(chunk)
        if not title_m:
            continue
        title = clean_text(title_m.group(1))
        link_m = LINK_RE.search(chunk)
        guid_m = GUID_RE.search(chunk)
        desc_m = SUMMARY_RE.search(chunk) or DESC_RE.search(chunk)
        guid = clean_text(guid_m.group(1) if guid_m else "")
        url = clean_text((link_m.group(1) if link_m else "") or guid)
        people = [canonical_name(p) for p in PERSON_TAG_RE.findall(chunk)]
        description = clean_text(desc_m.group(1) if desc_m else "")[:800]
        items.append({
            "title": title,
            "url": url,
            "guid": guid,
            "description": description,
            "rss_people": people,
        })
    return items


SKIP_NER_RE = re.compile(
    r"\btrailer\b|chapter\b|fabric of reality|beginning of infinity|"
    r"readings and discussion|ask me anything|\d+R_|"
    r"\bnewsletter\b|weekend of twitter|^bonus\s*\|",
    re.I,
)


def guests_for(podcast: dict, item: dict, nlp) -> list[str]:
    names: list[str] = []
    parser_name = podcast.get("parser")
    if parser_name in PARSERS:
        names.extend(PARSERS[parser_name](item["title"]))
    for person in item.get("rss_people") or []:
        if looks_like_name(person) or _loose_person_name(canonical_name(person)):
            names.append(canonical_name(person))
    # spaCy fills in unstructured titles the parsers miss; skip book-club / trailer rows.
    if nlp and not names and not SKIP_NER_RE.search(item["title"] or ""):
        # Title only — show notes mention too many people who were never guests.
        names.extend(ner_people(nlp, item["title"]))
    hosts = {canonical_name(h) for h in podcast["hosts"]}
    seen = set()
    out = []
    for name in names:
        if name in hosts or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def add_edge(edges: dict, a: str, b: str, episode: dict) -> None:
    if a == b:
        return
    key = tuple(sorted((a, b)))
    rec = edges[key]
    rec["value"] += 1
    if len(rec["episodes"]) < 8:
        if not any(e["url"] == episode["url"] and e["title"] == episode["title"] for e in rec["episodes"]):
            rec["episodes"].append(episode)


def shortest_path(adj: dict[str, set[str]], src: str, dst: str) -> list[str] | None:
    if src not in adj or dst not in adj:
        return None
    if src == dst:
        return [src]
    prev = {src: None}
    queue = [src]
    i = 0
    while i < len(queue):
        cur = queue[i]
        i += 1
        for nxt in adj[cur]:
            if nxt in prev:
                continue
            prev[nxt] = cur
            if nxt == dst:
                path = [dst]
                while path[-1] != src:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            queue.append(nxt)
    return None


def run_parser_self_check() -> None:
    cases = [
        ("dwarkesh", "Ajeya Cotra – Inside the OpenAI agent swarm", ["Ajeya Cotra"]),
        ("dwarkesh", "Bethany McLean — Enron, FTX, 2008, Musk, frauds, & visionaries", ["Bethany McLean"]),
        ("tokcast", "Ep 166: Newsletter 18: A weekend of Twitter", []),
        ("mindscape", "Bonus | Cuts to Science Funding and Why They Matter", []),
        ("colon", "Chiara Marletto: Constructor Theory, Ghost Particles", ["Chiara Marletto"]),
        ("colon", "Emily Adlam & David Wallace: The Quantum Interpretation", ["Emily Adlam", "David Wallace"]),
        ("dissenter", "#18 Eric Smith: The Origin and Nature of Life on Earth", ["Eric Smith"]),
        ("jimrutt", "EP 40 Eric Smith on the Physics of Living Systems", ["Eric Smith"]),
        ("jimrutt", "EP40 Eric Smith on the Physics of Living Systems", ["Eric Smith"]),
        ("jimrutt", "EP 345 Worldviews: Tyson Yunkaporta on Ceremony, Skepticism, and Seeing in 3D", ["Tyson Yunkaporta"]),
        ("jimrutt", "EP 334 Worldviews: Joscha Bach", ["Joscha Bach"]),
        ("lex", "#198 – Sara Walker: The Origin of Life on Earth and Alien Worlds", ["Sara Walker"]),
        ("mindscape", "366 | Jim Al-Khalili on Time, Quantum, Biology, and Cosmology", ["Jim Al-Khalili"]),
        ("cwt", "Jared Diamond on Leaders, Luck, and Irreplaceability", ["Jared Diamond"]),
        ("tokcast", "Ep 200: Chiara Marletto", ["Chiara Marletto"]),
        ("tokcast", "Ep 265: David Deutsch's \"The Fabric of Reality\" Chapter 14", []),
        ("pipe", "The End of Money? | Neha Narula", ["Neha Narula"]),
        ("emdash_end", "How Replication Could Teach Machines What Good Science Looks Like — Edward Hughes", ["Edward Hughes"]),
        ("with_or_colon", "Fallible Animals Episode 6: Interview with Physicist Chiara Marletto", ["Chiara Marletto"]),
        ("wtf4cities", "308I_Chiara Marletto, Scientific Researcher at University of Oxford", ["Chiara Marletto"]),
        ("wtf4cities", "308I_Trailer_Chiara Marletto, Scientific Researcher at University of Oxford", []),
        ("wtf4cities", "432I_Dr Nathalie Mezza-Garcia, digital and water-based jurisdiction architect", ["Nathalie Mezza-Garcia"]),
        ("wtf4cities", "400P_Climate change vs cities with Hudson Worsley, Matt Gijselman, and Allan Savory", ["Hudson Worsley", "Matt Gijselman", "Allan Savory"]),
        ("wtf4cities", "457R_What have urban digital twins contributed to urban planning", []),
        ("wtf4cities", "414I_Cormac McKay, environmental technologist and policy advisor", ["Cormac McKay"]),
        ("wtf4cities", "388I_Maurice Berger and Raquel Medrano Clemente, co-founders of Liveable Cities Collective", ["Maurice Berger", "Raquel Medrano Clemente"]),
        ("ferriss", "#876: Dr. Andrew Huberman — Peptides, Performance, and Protocols", ["Andrew Huberman"]),
        ("ferriss", "#856: Jim Collins — What to Make of a Life and How to Maximize Your Return on Luck", ["Jim Collins"]),
        ("ferriss", "#875: The Random Show — Tim and Kevin Talk Retreats", []),
        ("ferriss", "#881: Tales of Overcoming The Odds — Tim McGraw, Terry Crews, Dax Shepard, and More", ["Tim McGraw", "Terry Crews", "Dax Shepard"]),
    ]
    failed = 0
    for parser_name, title, expected in cases:
        got = PARSERS[parser_name](title)
        if got != expected:
            failed += 1
            print(f"SELF-CHECK FAIL {parser_name!r} {title!r}\n  expected {expected}\n  got      {got}", file=sys.stderr)
    if failed:
        raise SystemExit(f"{failed} parser self-check(s) failed")


def build_graph(state: dict[str, dict], *, full_refresh: bool = False, skip_ner: bool = False) -> dict:
    people: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = defaultdict(lambda: {"value": 0, "episodes": []})
    podcast_stats = []
    scanned_episodes = 0
    new_count = 0
    reused_count = 0
    known_ids = {p["id"] for p in PODCASTS}

    def ensure_person(name: str, is_host: bool, podcast_id: str) -> None:
        rec = people.get(name)
        if rec is None:
            rec = {
                "id": slug(name),
                "name": name,
                "isHost": False,
                "episodeCount": 0,
                "podcasts": [],
            }
            people[name] = rec
        if is_host:
            rec["isHost"] = True
        if podcast_id not in rec["podcasts"]:
            rec["podcasts"].append(podcast_id)

    nlp = False if skip_ner else None
    nlp_loaded = False

    def ensure_nlp():
        nonlocal nlp, nlp_loaded
        if skip_ner:
            return None
        if nlp is not None:
            return nlp
        if nlp_loaded:
            return None
        nlp_loaded = True
        nlp = load_spacy()
        return nlp

    for podcast in PODCASTS:
        print(f"Fetching {podcast['name']} ...", flush=True)
        try:
            xml_text = fetch_url(podcast["rss"])
        except Exception as exc:
            print(f"  SKIP {podcast['id']}: {exc}", file=sys.stderr)
            podcast_stats.append({
                "id": podcast["id"],
                "name": podcast["name"],
                "hosts": podcast["hosts"],
                "episodeCount": 0,
                "guestCount": 0,
                "error": str(exc),
            })
            continue

        items = parse_items(xml_text)
        rss_keys = {episode_key(podcast["id"], it) for it in items}
        guests_found = set()
        used = 0
        new_here = 0
        reused_here = 0
        for host in podcast["hosts"]:
            ensure_person(canonical_name(host), True, podcast["id"])

        for item in items:
            key = episode_key(podcast["id"], item)
            prev = None if full_refresh else state.get(key)
            if prev and prev.get("title") == item["title"] and "guests" in prev:
                guests = list(prev["guests"])
                reused_here += 1
                reused_count += 1
            else:
                model = ensure_nlp()
                guests = guests_for(podcast, item, model)
                new_here += 1
                new_count += 1
            state[key] = {
                "id": key,
                "podcastId": podcast["id"],
                "podcast": podcast["name"],
                "title": item["title"],
                "url": item["url"],
                "guid": item.get("guid") or "",
                "guests": guests,
                "hosts": [canonical_name(h) for h in podcast["hosts"]],
            }
            if not guests:
                continue
            used += 1
            scanned_episodes += 1
            episode_meta = {
                "podcast": podcast["name"],
                "podcastId": podcast["id"],
                "title": item["title"],
                "url": item["url"],
            }
            for host in podcast["hosts"]:
                hname = canonical_name(host)
                ensure_person(hname, True, podcast["id"])
                people[hname]["episodeCount"] += 1
            for guest in guests:
                ensure_person(guest, False, podcast["id"])
                people[guest]["episodeCount"] += 1
                guests_found.add(guest)
                for host in podcast["hosts"]:
                    add_edge(edges, canonical_name(host), guest, episode_meta)
            for i, a in enumerate(guests):
                for b in guests[i + 1:]:
                    add_edge(edges, a, b, episode_meta)

        # Keep episodes that fell off the current RSS window.
        for key, rec in list(state.items()):
            if rec.get("podcastId") != podcast["id"]:
                continue
            if key in rss_keys:
                continue
            guests = rec.get("guests") or []
            if not guests:
                continue
            used += 1
            scanned_episodes += 1
            reused_count += 1
            episode_meta = {
                "podcast": rec.get("podcast") or podcast["name"],
                "podcastId": podcast["id"],
                "title": rec.get("title") or "",
                "url": rec.get("url") or "",
            }
            for host in rec.get("hosts") or podcast["hosts"]:
                hname = canonical_name(host)
                ensure_person(hname, True, podcast["id"])
                people[hname]["episodeCount"] += 1
            for guest in guests:
                ensure_person(guest, False, podcast["id"])
                people[guest]["episodeCount"] += 1
                guests_found.add(guest)
                for host in rec.get("hosts") or podcast["hosts"]:
                    add_edge(edges, canonical_name(host), guest, episode_meta)
            for i, a in enumerate(guests):
                for b in guests[i + 1:]:
                    add_edge(edges, a, b, episode_meta)

        podcast_stats.append({
            "id": podcast["id"],
            "name": podcast["name"],
            "hosts": podcast["hosts"],
            "episodeCount": used,
            "rssItems": len(items),
            "guestCount": len(guests_found),
            "newItems": new_here,
            "reusedItems": reused_here,
        })
        print(
            f"  {used}/{len(items)} episodes with guests, {len(guests_found)} people "
            f"(new {new_here}, reused {reused_here})",
            flush=True,
        )

    # Drop state for podcasts we no longer track.
    for key, rec in list(state.items()):
        if rec.get("podcastId") not in known_ids:
            del state[key]

    nodes = sorted(people.values(), key=lambda n: (-n["episodeCount"], n["name"]))
    # Force stable unique ids if two names slug-collide.
    seen_ids = set()
    for node in nodes:
        base = node["id"]
        if base not in seen_ids:
            seen_ids.add(base)
            continue
        i = 2
        while f"{base}-{i}" in seen_ids:
            i += 1
        node["id"] = f"{base}-{i}"
        seen_ids.add(node["id"])

    name_to_id = {n["name"]: n["id"] for n in nodes}
    links = []
    for (a, b), rec in sorted(edges.items(), key=lambda kv: (-kv[1]["value"], kv[0])):
        if a not in name_to_id or b not in name_to_id:
            continue
        links.append({
            "source": name_to_id[a],
            "target": name_to_id[b],
            "value": rec["value"],
            "episodes": rec["episodes"],
        })

    adj = defaultdict(set)
    for link in links:
        adj[link["source"]].add(link["target"])
        adj[link["target"]].add(link["source"])
    src_id = name_to_id.get(DEFAULT_FROM)
    dst_id = name_to_id.get(DEFAULT_TO)
    path = shortest_path(adj, src_id, dst_id) if src_id and dst_id else None

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "defaultFrom": DEFAULT_FROM,
        "defaultTo": DEFAULT_TO,
        "podcasts": podcast_stats,
        "stats": {
            "people": len(nodes),
            "links": len(links),
            "episodes": scanned_episodes,
            "newItems": new_count,
            "reusedItems": reused_count,
            "extractor": "spacy+parsers",
            "defaultHops": None if path is None else max(0, len(path) - 1),
            "defaultPath": path,
        },
        "nodes": nodes,
        "links": links,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build podcast guest-hop graph JSON")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--full-refresh", action="store_true", help="Re-extract guests for every RSS item")
    parser.add_argument("--skip-ner", action="store_true", help="Use title parsers only (no spaCy)")
    parser.add_argument("--skip-self-check", action="store_true")
    args = parser.parse_args()

    if not args.skip_self_check:
        run_parser_self_check()

    state = load_state(args.state)
    print(f"Loaded {len(state)} cached episodes from {args.state}")
    graph = build_graph(state, full_refresh=args.full_refresh, skip_ner=args.skip_ner)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(graph, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    save_state(args.state, state)
    stats = graph["stats"]
    print(f"Wrote {args.output} and {args.state}")
    print(
        f"People {stats['people']}  links {stats['links']}  episodes {stats['episodes']}  "
        f"new {stats['newItems']}  reused {stats['reusedItems']}"
    )
    names = {n["id"]: n["name"] for n in graph["nodes"]}
    if stats["defaultPath"]:
        hops = stats["defaultHops"]
        pretty = " → ".join(names[i] for i in stats["defaultPath"])
        print(f"Default path ({hops} hop{'s' if hops != 1 else ''}): {pretty}")
    else:
        have_from = any(n["name"] == DEFAULT_FROM for n in graph["nodes"])
        have_to = any(n["name"] == DEFAULT_TO for n in graph["nodes"])
        print(f"No default path. {DEFAULT_FROM} in graph={have_from}  {DEFAULT_TO} in graph={have_to}")


if __name__ == "__main__":
    main()
