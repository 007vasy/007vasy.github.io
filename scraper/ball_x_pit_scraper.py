import os
import re
import time
import json
import pathlib
from typing import Dict, List, Tuple, Optional

import requests
from bs4 import BeautifulSoup


API_ENDPOINT = "https://ballpit.fandom.com/api.php"
BASE_WIKI_URL = "https://ballpit.fandom.com/wiki/"

OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "docs" / "ball-x-pit"
IMAGES_BASE = pathlib.Path(__file__).resolve().parents[1] / "docs" / "images" / "ball-x-pit"

HEADERS = {
    "User-Agent": "007vasy.github.io-scraper/1.0 (+https://github.com/007vasy/007vasy.github.io)"
}

# Categories to scrape from the wiki. The exact names may vary; adjust if needed.
CATEGORIES = {
    "Ball": ["Balls"],
    "Character": ["Characters"],
    "Passive": ["Passives"],
}


def safe_slug(name: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9\-_. ]+", "", slug)
    slug = slug.replace(" ", "_")
    return slug[:120]


def ensure_dirs() -> None:
    (IMAGES_BASE / "balls").mkdir(parents=True, exist_ok=True)
    (IMAGES_BASE / "characters").mkdir(parents=True, exist_ok=True)
    (IMAGES_BASE / "passives").mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def mw_get(params: Dict) -> Dict:
    params = {"format": "json", **params}
    resp = requests.get(API_ENDPOINT, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def list_category_members(category: str) -> List[Dict]:
    members: List[Dict] = []
    cmcontinue: Optional[str] = None
    while True:
        p = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": "500",
        }
        if cmcontinue:
            p["cmcontinue"] = cmcontinue
        data = mw_get(p)
        members.extend(data.get("query", {}).get("categorymembers", []))
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
        time.sleep(0.2)
    return members


def list_all_pages() -> List[str]:
    """List all article titles (namespace 0) for small wikis as a robust fallback."""
    titles: List[str] = []
    apcontinue: Optional[str] = None
    while True:
        p = {
            "action": "query",
            "list": "allpages",
            "apnamespace": 0,
            "aplimit": "500",
        }
        if apcontinue:
            p["apcontinue"] = apcontinue
        data = mw_get(p)
        pages = data.get("query", {}).get("allpages", [])
        for pg in pages:
            title = pg.get("title")
            if title and title not in titles:
                titles.append(title)
        apcontinue = data.get("continue", {}).get("apcontinue")
        if not apcontinue:
            break
        time.sleep(0.2)
    return titles


def get_page_info(titles: List[str]) -> Dict[str, Dict]:
    """Return mapping title -> info with fullurl, image, and categories if available."""
    result: Dict[str, Dict] = {}
    # MediaWiki API limits titles length; batch them
    batch: List[str] = []
    for title in titles + ["__flush__"]:
        if title == "__flush__" or sum(len(t) for t in batch) > 7500:
            if batch:
                resp = mw_get(
                    {
                        "action": "query",
                        "prop": "info|pageimages|categories",
                        "inprop": "url",
                        "piprop": "original",
                        "cllimit": "max",
                        "titles": "|".join(batch),
                        "redirects": 1,
                    }
                )
                pages = resp.get("query", {}).get("pages", {})
                for _, page in pages.items():
                    title_key = page.get("title", "")
                    info = {
                        "title": title_key,
                        "fullurl": page.get("fullurl", f"{BASE_WIKI_URL}{title_key.replace(' ', '_')}"),
                        "image": None,
                        "categories": [c.get("title", "") for c in page.get("categories", []) if isinstance(c, dict)],
                    }
                    orig = page.get("original")
                    if orig and isinstance(orig, dict):
                        info["image"] = orig.get("source")
                    result[title_key] = info
            batch = []
        if title != "__flush__":
            batch.append(title)
    return result


def fetch_html(title: str) -> BeautifulSoup:
    url = f"{BASE_WIKI_URL}{title.replace(' ', '_')}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")


def find_infobox_image(soup: BeautifulSoup) -> Optional[str]:
    # Common Fandom structures
    fig = soup.select_one("aside.portable-infobox figure.pi-image img, figure.pi-image img")
    if fig and fig.get("src"):
        return fig["src"]
    # Fallback: first content image
    img = soup.select_one(".mw-parser-output img")
    if img and img.get("src"):
        return img["src"]
    return None


def download_image(url: str, dest_path: pathlib.Path) -> Optional[str]:
    try:
        if dest_path.exists():
            return str(dest_path.relative_to(OUTPUT_DIR.parents[0]))
        with requests.get(url, headers=HEADERS, timeout=60, stream=True) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        # return web path relative to docs/
        return str(dest_path.relative_to(OUTPUT_DIR.parents[0]))
    except Exception:
        return None


def collect_section_links(soup: BeautifulSoup, header_keywords: List[str]) -> List[str]:
    links: List[str] = []
    headers = soup.select("h1, h2, h3, h4, h5, h6")
    pattern = re.compile("|".join([re.escape(k) for k in header_keywords]), re.I)
    for h in headers:
        if not h.get_text(strip=True):
            continue
        if not pattern.search(h.get_text(" ", strip=True)):
            continue
        # collect until next header of same level
        level = int(h.name[1])
        node = h.next_sibling
        while node is not None:
            if getattr(node, "name", None) and re.fullmatch(r"h[1-6]", node.name or ""):
                lvl2 = int(node.name[1])
                if lvl2 <= level:
                    break
            for a in BeautifulSoup(str(node), "lxml").select("a[href]"):
                href = a.get("href") or ""
                if href.startswith("/wiki/"):
                    title = href.split("/wiki/")[-1].replace("_", " ")
                    links.append(title)
            node = node.next_sibling
    return list(dict.fromkeys(links))  # de-dupe keep order


def build_graph() -> Dict:
    ensure_dirs()

    # 1) Discover pages: use categories if present; otherwise, fall back to all pages and classify by categories
    label_to_titles: Dict[str, List[str]] = {label: [] for label in CATEGORIES}

    # Try categories first
    for label, cats in CATEGORIES.items():
        for cat in cats:
            members = list_category_members(cat)
            for m in members:
                title = m.get("title", "").strip()
                if title and title not in label_to_titles[label]:
                    label_to_titles[label].append(title)
            time.sleep(0.2)

    if not any(label_to_titles.values()):
        # Fallback: list all pages and then classify via prop=categories
        all_titles = list_all_pages()
        info_map = get_page_info(all_titles)
        for title, info in info_map.items():
            cats = [c.split(":", 1)[-1] for c in info.get("categories", [])]
            for label, need_cats in CATEGORIES.items():
                if any(c in need_cats for c in cats):
                    label_to_titles[label].append(title)
        # De-dup
        for k, v in list(label_to_titles.items()):
            label_to_titles[k] = list(dict.fromkeys(v))
        title_info = info_map

    # If still empty, parse index pages directly to harvest item links
    if not any(label_to_titles.values()):
        index_pages = {
            "Ball": "Balls",
            "Character": "Characters",
            "Passive": "Passives",
        }
        for label, page in index_pages.items():
            try:
                soup = fetch_html(page)
            except Exception:
                continue
            # Collect wiki links in main content
            candidates: List[str] = []
            for a in soup.select('.mw-parser-output a[href^="/wiki/"]'):
                href = a.get('href') or ''
                title = href.split('/wiki/')[-1].replace('_', ' ')
                # skip generic or index pages, files, special namespaces
                if any(title.startswith(ns) for ns in ["Category:", "File:", "Special:", "Talk:", "Template:"]):
                    continue
                # skip section anchors
                if '#' in title:
                    continue
                if title in {"Main Page", "Ball X Pit Wiki", page}:
                    continue
                candidates.append(title)
            # unique preserve order
            candidates = list(dict.fromkeys(candidates))
            if candidates:
                # Filter candidates by categories to match intended label (if available)
                info_subset = get_page_info(candidates)
                for t, inf in info_subset.items():
                    cats = [c.split(":", 1)[-1] for c in inf.get("categories", [])]
                    if any(c in CATEGORIES.get(label, []) for c in cats):
                        if t not in label_to_titles[label]:
                            label_to_titles[label].append(t)

        # Recompute title_info for any found titles
        if any(label_to_titles.values()):
            all_titles = sorted({t for ts in label_to_titles.values() for t in ts})
            ti2 = get_page_info(all_titles)
            title_info.update(ti2)
    else:
        # Resolve page info (urls + images + categories) for discovered titles
        all_titles = sorted({t for ts in label_to_titles.values() for t in ts})
        title_info = get_page_info(all_titles)

    # 3) Create nodes
    nodes: List[Dict] = []
    title_to_node_id: Dict[str, str] = {}
    image_web_paths: Dict[str, str] = {}

    for label, titles in label_to_titles.items():
        for t in titles:
            info = title_info.get(t, {"fullurl": f"{BASE_WIKI_URL}{t.replace(' ', '_')}", "image": None})
            img_url = info.get("image")
            if not img_url:
                # fetch HTML and try to detect infobox image
                soup = fetch_html(t)
                img_url = find_infobox_image(soup)
                time.sleep(0.2)

            local_img_dir = {
                "Ball": IMAGES_BASE / "balls",
                "Character": IMAGES_BASE / "characters",
                "Passive": IMAGES_BASE / "passives",
            }.get(label, IMAGES_BASE)

            image_path_rel: Optional[str] = None
            if img_url:
                ext = os.path.splitext(img_url.split("?")[0].split("/")[-1])[1] or ".jpg"
                dest = local_img_dir / f"{safe_slug(t)}{ext}"
                image_path_rel = download_image(img_url, dest)
                time.sleep(0.15)

            node_id = f"n{len(nodes)}"
            title_to_node_id[t] = node_id
            if image_path_rel:
                image_web_paths[t] = image_path_rel

            nodes.append(
                {
                    "id": node_id,
                    "caption": t,
                    "labels": [label],
                    "properties": {
                        "url": info.get("fullurl"),
                        "imagePath": image_path_rel or "",
                    },
                    "style": {},
                }
            )

    # 4) Relationships
    relationships: List[Dict] = []

    # Helper: only consider links that point to known titles
    known_titles = set(title_to_node_id.keys())

    def add_rel(from_title: str, to_title: str, rel_type: str) -> None:
        if from_title not in known_titles or to_title not in known_titles:
            return
        relationships.append(
            {
                "id": f"r{len(relationships)}",
                "type": rel_type,
                "style": {},
                "properties": {},
                "fromId": title_to_node_id[from_title],
                "toId": title_to_node_id[to_title],
            }
        )

    # Character -> Ball (Starts With)
    for title in label_to_titles.get("Character", []):
        soup = fetch_html(title)
        # prioritize sections named Starts, Starter
        links = collect_section_links(soup, ["Starts With", "Starter", "Starter Ball", "Starting Ball"])
        # fallback: any ball links on the page (broad)
        if not links:
            links = [t for t in {a.get("href", "") for a in soup.select("a[href]")} if t.startswith("/wiki/")]
            links = [l.split("/wiki/")[-1].replace("_", " ") for l in links]
        for tgt in links:
            if tgt in label_to_titles.get("Ball", []):
                add_rel(title, tgt, "Starts With")
        time.sleep(0.15)

    # Ball -> Passive (HAS Passive) and Ball -> Ball (HAS Evolution)
    for title in label_to_titles.get("Ball", []):
        soup = fetch_html(title)
        # Passives section
        passive_links = collect_section_links(soup, ["Passive", "Passives"]) or []
        for tgt in passive_links:
            if tgt in label_to_titles.get("Passive", []):
                add_rel(title, tgt, "HAS Passive")

        # Evolution section: Evolves, Evolution
        evo_links = collect_section_links(soup, ["Evolve", "Evolves", "Evolution"]) or []
        for tgt in evo_links:
            if tgt in label_to_titles.get("Ball", []):
                add_rel(title, tgt, "HAS Evolution")
        time.sleep(0.15)

    graph = {"nodes": nodes, "relationships": relationships}
    return graph


def main() -> None:
    graph = build_graph()
    out_path = OUTPUT_DIR / "graph.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    print(f"Wrote graph to {out_path}")


if __name__ == "__main__":
    main()


