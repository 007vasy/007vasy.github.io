import os
import re
import time
import json
import csv
import pathlib
import traceback
from typing import Dict, List, Tuple, Optional

import requests
from bs4 import BeautifulSoup


API_ENDPOINT = "https://ballpit.fandom.com/api.php"
BASE_WIKI_URL = "https://ballpit.fandom.com/wiki/"

OUTPUT_DIR = pathlib.Path(__file__).resolve().parents[1] / "docs" / "ball_x_pit"
IMAGES_BASE = pathlib.Path(__file__).resolve().parents[1] / "docs" / "images" / "ball_x_pit"

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
    # Fandom's Cloudflare front-end returns 403 for direct /wiki/<title> GETs from
    # non-interactive clients, so pull rendered HTML via the MediaWiki parse API
    # (api.php is not subject to the same block) and reconstruct a soup from it.
    data = mw_get({
        "action": "parse",
        "page": title,
        "prop": "text",
        "formatversion": 2,
        "redirects": 1,
    })
    html = data.get("parse", {}).get("text", "") or ""
    if not html:
        raise RuntimeError(f"empty parse response for title={title!r}: {data!r}")
    return BeautifulSoup(html, "lxml")


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


def pick_best_img_src(img_tag) -> Optional[str]:
    if img_tag is None:
        return None
    # Prefer data-src if present and looks like a URL
    data_src = img_tag.get('data-src') or img_tag.get('data-original')
    if data_src and data_src.startswith(('http://', 'https://')):
        return data_src
    # Try srcset (pick first URL)
    srcset = img_tag.get('srcset')
    if srcset:
        first = srcset.split(',')[0].strip().split(' ')[0]
        if first.startswith(('http://', 'https://')):
            return first
    # Fallback to src if it's not a 1x1 gif/data uri
    src = img_tag.get('src')
    if src and src.startswith(('http://', 'https://')) and 'data:image/gif' not in src:
        return src
    return None


def extract_description_from_page(title_or_url: str) -> Optional[str]:
    try:
        if title_or_url.startswith('http://') or title_or_url.startswith('https://'):
            # Normalize URL -> wiki title and go through the parse API
            title = title_or_url.split('/wiki/')[-1].replace('_', ' ')
        else:
            title = title_or_url
        soup = fetch_html(title)
        # Parse API returns HTML rooted at <div class="mw-parser-output">,
        # so .mw-parser-output > p misses the actual paragraphs. Look for
        # both the rooted and unrooted variants.
        for p in soup.select('.mw-parser-output > p, :scope > p'):
            txt = p.get_text(' ', strip=True)
            if txt and len(txt) > 20:
                return txt
        # Fallback: any <p> in the document
        for p in soup.select('p'):
            txt = p.get_text(' ', strip=True)
            if txt and len(txt) > 20:
                return txt
    except Exception:
        return None
    return None


def download_image(url: str, dest_path: pathlib.Path) -> Optional[str]:
    try:
        if dest_path.exists():
            return "/" + str(dest_path.relative_to(OUTPUT_DIR.parents[0]))
        with requests.get(url, headers=HEADERS, timeout=60, stream=True) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        # return web path relative to docs/ with leading slash so it resolves from site root
        return "/" + str(dest_path.relative_to(OUTPUT_DIR.parents[0]))
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

    # Build primarily by parsing the tables on Characters, Balls, and Passives pages
    nodes: List[Dict] = []
    relationships: List[Dict] = []
    title_to_node_id: Dict[str, str] = {}
    # For schema output (nodes with Evolution type)
    schema_nodes: List[Dict] = []
    schema_rels: List[Dict] = []
    schema_title_to_id: Dict[str, str] = {}

    def get_or_create_node(name: str, label: str, page_url: str, icon_url: Optional[str], description: Optional[str] = None, requirement: Optional[str] = None, unlock: Optional[str] = None, ability: Optional[str] = None) -> str:
        if name in title_to_node_id:
            # Try to upgrade existing node with missing image/url
            node_id = title_to_node_id[name]
            for idx, n in enumerate(nodes):
                if n["id"] == node_id:
                    # fill url if empty
                    if page_url and not n.get("properties", {}).get("url"):
                        n["properties"]["url"] = page_url
                    # fill image if empty and we have an icon
                    if icon_url and not n.get("properties", {}).get("imagePath"):
                        local_img_dir = {
                            "Ball": IMAGES_BASE / "balls",
                            "Character": IMAGES_BASE / "characters",
                            "Passive": IMAGES_BASE / "passives",
                        }.get(label, IMAGES_BASE)
                        ext = os.path.splitext(icon_url.split("?")[0].split("/")[-1])[1] or ".jpg"
                        dest = local_img_dir / f"{safe_slug(name)}{ext}"
                        image_path_rel = download_image(icon_url, dest)
                        if image_path_rel:
                            n["properties"]["imagePath"] = image_path_rel
                    # fill description if empty
                    if description and not n.get("properties", {}).get("description"):
                        n["properties"]["description"] = description
                    # fill requirement if empty (for passives)
                    if requirement and not n.get("properties", {}).get("requirement"):
                        n["properties"]["requirement"] = requirement
                    # fill unlock/ability for characters
                    if unlock and not n.get("properties", {}).get("unlock"):
                        n["properties"]["unlock"] = unlock
                    if ability and not n.get("properties", {}).get("ability"):
                        n["properties"]["ability"] = ability
                    break
            return node_id
        local_img_dir = {
            "Ball": IMAGES_BASE / "balls",
            "Character": IMAGES_BASE / "characters",
            "Passive": IMAGES_BASE / "passives",
        }.get(label, IMAGES_BASE)
        image_path_rel: Optional[str] = None
        if icon_url:
            ext = os.path.splitext(icon_url.split("?")[0].split("/")[-1])[1] or ".jpg"
            dest = local_img_dir / f"{safe_slug(name)}{ext}"
            image_path_rel = download_image(icon_url, dest)
            time.sleep(0.05)
        node_id = f"n{len(nodes)}"
        title_to_node_id[name] = node_id
        nodes.append({
            "id": node_id,
            "caption": name,
            "labels": [label],
            "properties": {"url": page_url, "imagePath": image_path_rel or "", "description": description or "", "requirement": requirement or "", "unlock": unlock or "", "ability": ability or ""},
            "style": {},
        })
        return node_id

    def schema_get_or_create(name: str, label: str, page_url: str, icon_url: Optional[str], description: Optional[str] = None, requirement: Optional[str] = None, unlock: Optional[str] = None, ability: Optional[str] = None) -> str:
        if name in schema_title_to_id:
            node_id = schema_title_to_id[name]
            for idx, n in enumerate(schema_nodes):
                if n["id"] == node_id:
                    if page_url and not n.get("properties", {}).get("url"):
                        n["properties"]["url"] = page_url
                    if icon_url and not n.get("properties", {}).get("imagePath"):
                        local_img_dir = {
                            "Ball": IMAGES_BASE / "balls",
                            "Character": IMAGES_BASE / "characters",
                            "Passive": IMAGES_BASE / "passives",
                        }.get(label, IMAGES_BASE)
                        ext = os.path.splitext(icon_url.split("?")[0].split("/")[-1])[1] or ".jpg"
                        dest = local_img_dir / f"{safe_slug(name)}{ext}"
                        image_path_rel = download_image(icon_url, dest)
                        if image_path_rel:
                            n["properties"]["imagePath"] = image_path_rel
                    if description and not n.get("properties", {}).get("description"):
                        n["properties"]["description"] = description
                    if requirement and not n.get("properties", {}).get("requirement"):
                        n["properties"]["requirement"] = requirement
                    if unlock and not n.get("properties", {}).get("unlock"):
                        n["properties"]["unlock"] = unlock
                    if ability and not n.get("properties", {}).get("ability"):
                        n["properties"]["ability"] = ability
                    break
            return node_id
        # reuse downloaded path if we already created the runtime node
        # try to map to runtime node id and copy properties
        # but simplest: compute image path same as above
        local_img_dir = {
            "Ball": IMAGES_BASE / "balls",
            "Character": IMAGES_BASE / "characters",
            "Passive": IMAGES_BASE / "passives",
        }.get(label, IMAGES_BASE)
        image_path_rel: Optional[str] = None
        if icon_url:
            ext = os.path.splitext(icon_url.split("?")[0].split("/")[-1])[1] or ".jpg"
            dest = local_img_dir / f"{safe_slug(name)}{ext}"
            image_path_rel = download_image(icon_url, dest)
        node_id = f"n{len(schema_nodes)}"
        schema_title_to_id[name] = node_id
        schema_nodes.append({
            "id": node_id,
            "position": {"x": 0, "y": 0},
            "caption": name,
            "style": {},
            "labels": [label],
            "properties": {"url": page_url, "imagePath": image_path_rel or "", "description": description or "", "requirement": requirement or "", "unlock": unlock or "", "ability": ability or ""}
        })
        return node_id

    def schema_add_rel(from_name: str, to_name: str, rel_type: str):
        if from_name not in schema_title_to_id or to_name not in schema_title_to_id:
            return
        schema_rels.append({
            "id": f"r{len(schema_rels)}",
            "type": rel_type,
            "style": {},
            "properties": {},
            "fromId": schema_title_to_id[from_name],
            "toId": schema_title_to_id[to_name]
        })

    def add_edge(from_name: str, to_name: str, rel_type: str):
        if from_name not in title_to_node_id or to_name not in title_to_node_id:
            return
        relationships.append({
            "id": f"r{len(relationships)}",
            "type": rel_type,
            "style": {},
            "properties": {},
            "fromId": title_to_node_id[from_name],
            "toId": title_to_node_id[to_name],
        })

    def parse_table(page_title: str) -> List[Dict[str, str]]:
        soup = fetch_html(page_title)
        # find table with Name column
        all_rows: List[Dict[str, str]] = []
        for table in soup.select('.mw-parser-output table'):  # tables include class wikitable usually
            # build header
            headers = [th.get_text(" ", strip=True).lower() for th in table.select('tr th')]
            if not headers:
                # try first row
                first = table.find('tr')
                if first:
                    headers = [th.get_text(" ", strip=True).lower() for th in first.find_all('th')]
            if not headers or all(h == '' for h in headers):
                continue
            if 'name' not in headers:
                continue
            name_idx = headers.index('name')
            # optional known columns
            icon_idx = headers.index('icon') if 'icon' in headers else None
            description_idx = headers.index('description') if 'description' in headers else None
            unlock_idx = headers.index('unlock') if 'unlock' in headers else None
            ability_idx = headers.index('ability') if 'ability' in headers else None
            ball_idx = headers.index('ball') if 'ball' in headers else None
            passive_idx = headers.index('passive') if 'passive' in headers else None
            # evolution-like columns
            evol_indices = [i for i, h in enumerate(headers) if 'evol' in h]
            combination_idx = headers.index('combination') if 'combination' in headers else None
            requirement_idx = headers.index('requirement') if 'requirement' in headers else None
            rows: List[Dict[str, str]] = []
            for tr in table.select('tr')[1:]:
                tds = tr.find_all('td')
                if not tds or len(tds) <= name_idx:
                    continue
                name_cell = tds[name_idx]
                link_el = name_cell.select_one('a[href^="/wiki/"]')
                link_title = None
                page_url = None
                if link_el:
                    href = link_el.get('href') or ''
                    link_title = href.split('/wiki/')[-1].replace('_', ' ')
                    page_url = BASE_WIKI_URL + href.split('/wiki/')[-1]
                val = {
                    'name': name_cell.get_text(" ", strip=True),
                }
                if link_title:
                    val['link_title'] = link_title
                if page_url:
                    val['page_url'] = page_url
                if icon_idx is not None and icon_idx < len(tds):
                    img = tds[icon_idx].select_one('img')
                    chosen = pick_best_img_src(img)
                    if not chosen and img is not None:
                        # last resort: try parent anchor style background-image
                        parent = img.parent
                        style = parent.get('style') if parent else None
                        if style and 'background-image' in style:
                            m = re.search(r"url\(['\"]?(.*?)['\"]?\)", style)
                            if m:
                                chosen = m.group(1)
                    if chosen:
                        val['icon'] = chosen
                if description_idx is not None and description_idx < len(tds):
                    desc_txt = tds[description_idx].get_text(" ", strip=True)
                    if desc_txt:
                        val['description'] = desc_txt
                if unlock_idx is not None and unlock_idx < len(tds):
                    unlock_txt = tds[unlock_idx].get_text(" ", strip=True)
                    if unlock_txt:
                        val['unlock'] = unlock_txt
                if ability_idx is not None and ability_idx < len(tds):
                    ability_txt = tds[ability_idx].get_text(" ", strip=True)
                    if ability_txt:
                        val['ability'] = ability_txt
                if ball_idx is not None and ball_idx < len(tds):
                    val['ball'] = tds[ball_idx].get_text(" ", strip=True)
                if passive_idx is not None and passive_idx < len(tds):
                    val['passive'] = tds[passive_idx].get_text(" ", strip=True)
                # collect evolutions from any evolution-like columns (as linked titles)
                evols: List[str] = []
                for idx in evol_indices:
                    if idx < len(tds):
                        for a in tds[idx].select('a[href^="/wiki/"]'):
                            href = a.get('href') or ''
                            t = href.split('/wiki/')[-1].replace('_', ' ')
                            if t:
                                evols.append(t)
                if evols:
                    # de-dupe preserve order
                    val['evolutions'] = list(dict.fromkeys(evols))
                # collect combinations for evolved balls (each line like "Iron + Ghost")
                if combination_idx is not None and combination_idx < len(tds):
                    combo_cell = tds[combination_idx]
                    # split by <br> or newlines
                    lines: List[str] = []
                    # get text with line breaks represented
                    for br in combo_cell.find_all(['br']):
                        br.replace_with('\n')
                    raw = combo_cell.get_text('\n', strip=True)
                    for line in [l.strip() for l in raw.split('\n') if l.strip()]:
                        lines.append(line)
                    # fallback: if anchors exist with plus signs between, also construct from anchors
                    if not lines:
                        txt = combo_cell.get_text(' ', strip=True)
                        if '+' in txt:
                            lines = [txt]
                    if lines:
                        val.setdefault('combinations', [])
                        val['combinations'].extend(lines)
                # collect combinations from requirement column for passives if multiple wiki links present
                if requirement_idx is not None and requirement_idx < len(tds):
                    req_cell = tds[requirement_idx]
                    # preserve lines
                    for br in req_cell.find_all(['br']):
                        br.replace_with('\n')
                    raw = req_cell.get_text('\n', strip=True)
                    line_texts = [l.strip() for l in raw.split('\n') if l.strip()]
            # group anchors by line
                    req_html_lines = (str(req_cell)).split('<br') if '<br' in str(req_cell) else [str(req_cell)]
                    combos_from_links: List[str] = []
                    for seg in req_html_lines:
                        seg_soup = BeautifulSoup(seg, 'lxml')
                        titles = []
                        for a in seg_soup.select('a[href^="/wiki/"]'):
                            href = a.get('href') or ''
                            t = href.split('/wiki/')[-1].replace('_', ' ').strip()
                            if t and t not in titles:
                                titles.append(t)
                        if len(titles) >= 2:
                            combos_from_links.append(' + '.join(titles))
                    if combos_from_links:
                        val.setdefault('combinations', [])
                        val['combinations'].extend(combos_from_links)
                    # store raw requirement text for node property/CSV
                    if raw:
                        val['requirement'] = raw
                # Skip rows whose name cell is empty or purely punctuation
                # (the Passives wiki table intersperses "+" combination separators
                # that would otherwise be parsed as a phantom "+" entity).
                if val['name'] and re.search(r"[A-Za-z0-9]", val['name']):
                    rows.append(val)
            if rows:
                all_rows.extend(rows)
        return all_rows

    def dump_rows_to_csv(page_title: str, rows: List[Dict[str, str]]):
        if not rows:
            return
        tables_dir = OUTPUT_DIR / 'tables'
        tables_dir.mkdir(parents=True, exist_ok=True)
        csv_path = tables_dir / f"{safe_slug(page_title)}.csv"
        # normalize fields
        fieldnames = ['name', 'page_url', 'icon', 'description', 'unlock', 'ability', 'requirement', 'ball', 'passive', 'evolutions', 'combinations']
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                row = {k: r.get(k, '') for k in fieldnames}
                if isinstance(row.get('evolutions'), list):
                    row['evolutions'] = '; '.join(row['evolutions'])
                if isinstance(row.get('combinations'), list):
                    row['combinations'] = '; '.join(row['combinations'])
                w.writerow(row)

    # Parse Characters
    try:
        char_rows = parse_table('Characters')
        dump_rows_to_csv('Characters', char_rows)
        for row in char_rows:
            char_name = row.get('name')
            icon = row.get('icon')
            page_url = row.get('page_url') or (BASE_WIKI_URL + 'Characters')
            description = row.get('description')
            unlock = row.get('unlock')
            ability = row.get('ability')
            # try fallback icon from character page if missing
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            if not description and row.get('link_title'):
                description = extract_description_from_page(row['link_title'])
            char_id = get_or_create_node(char_name, 'Character', page_url, icon, description, None, unlock, ability)
            schema_get_or_create(char_name, 'Character', page_url, icon, description, None, unlock, ability)
            ball_name = (row.get('ball') or '').strip()
            if ball_name:
                ball_id = get_or_create_node(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                add_edge(char_name, ball_name, 'Starts With')
                # schema
                schema_get_or_create(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                schema_add_rel(char_name, ball_name, 'Starts With')
    except Exception:
        print("[scraper] Characters section failed:")
        traceback.print_exc()

    # Parse Balls
    try:
        ball_rows = parse_table('Balls')
        dump_rows_to_csv('Balls', ball_rows)
        for row in ball_rows:
            ball_name = row.get('name')
            icon = row.get('icon')
            page_url = row.get('page_url') or (BASE_WIKI_URL + 'Balls')
            description = row.get('description')
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            if not description and row.get('link_title'):
                description = extract_description_from_page(row['link_title'])
            get_or_create_node(ball_name, 'Ball', page_url, icon, description, None)
            schema_get_or_create(ball_name, 'Ball', page_url, icon, description, None)
            # If the table lists a passive column value, add relationship
            passive_name = (row.get('passive') or '').strip()
            if passive_name:
                get_or_create_node(passive_name, 'Passive', BASE_WIKI_URL + 'Passives', None)
                add_edge(ball_name, passive_name, 'HAS Passive')
            # If the table lists evolutions, add HAS Evolution edges
            for evo in row.get('evolutions', []) or []:
                # runtime graph: insert evolution node between source and target
                evo_node_name = f"{ball_name} -> {evo}"
                # create runtime nodes if missing
                get_or_create_node(evo, 'Ball', BASE_WIKI_URL + 'Balls', None)
                get_or_create_node(evo_node_name, 'Evolution', '', None)
                # runtime relationships
                relationships.append({
                    "id": f"r{len(relationships)}",
                    "type": 'HAS Evolution',
                    "style": {},
                    "properties": {},
                    "fromId": title_to_node_id[ball_name],
                    "toId": title_to_node_id[evo_node_name]
                })
                relationships.append({
                    "id": f"r{len(relationships)}",
                    "type": '',
                    "style": {},
                    "properties": {},
                    "fromId": title_to_node_id[evo_node_name],
                    "toId": title_to_node_id[evo]
                })
                # schema mirror
                schema_get_or_create(evo, 'Ball', BASE_WIKI_URL + 'Balls', None)
                schema_get_or_create(evo_node_name, 'Evolution', '', None)
                schema_add_rel(ball_name, evo_node_name, 'HAS Evolution')
                schema_add_rel(evo_node_name, evo, '')
            # If the table lists combinations, add edges from components -> evolved ball
            combos = row.get('combinations') or []
            for combo_line in combos:
                parts = [p.strip() for p in re.split(r"\+|,| and ", combo_line) if p.strip()]
                # runtime: components -> evolution node -> result ball
                evo_node_name = f"{' + '.join(parts)}"
                get_or_create_node(evo_node_name, 'Evolution', '', None)
                get_or_create_node(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                for comp in parts:
                    get_or_create_node(comp, 'Ball', BASE_WIKI_URL + 'Balls', None)
                    relationships.append({
                        "id": f"r{len(relationships)}",
                        "type": 'HAS Evolution',
                        "style": {},
                        "properties": {},
                        "fromId": title_to_node_id[comp],
                        "toId": title_to_node_id[evo_node_name]
                    })
                relationships.append({
                    "id": f"r{len(relationships)}",
                    "type": '',
                    "style": {},
                    "properties": {},
                    "fromId": title_to_node_id[evo_node_name],
                    "toId": title_to_node_id[ball_name]
                })
                # schema mirror
                schema_get_or_create(evo_node_name, 'Evolution', '', None)
                schema_get_or_create(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                for comp in parts:
                    schema_get_or_create(comp, 'Ball', BASE_WIKI_URL + 'Balls', None)
                    schema_add_rel(comp, evo_node_name, 'HAS Evolution')
                schema_add_rel(evo_node_name, ball_name, '')
    except Exception:
        print("[scraper] Balls section failed:")
        traceback.print_exc()

    # Parse Passives
    try:
        passive_rows = parse_table('Passives')
        dump_rows_to_csv('Passives', passive_rows)
        for row in passive_rows:
            passive_name = row.get('name')
            icon = row.get('icon')
            page_url = row.get('page_url') or (BASE_WIKI_URL + 'Passives')
            description = row.get('description')
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            if not description and row.get('link_title'):
                description = extract_description_from_page(row['link_title'])
            req_text = row.get('requirement')
            get_or_create_node(passive_name, 'Passive', page_url, icon, description, req_text)
            schema_get_or_create(passive_name, 'Passive', page_url, icon, description, req_text)
            # Passive combinations -> evolution nodes analogous to balls
            combos = row.get('combinations') or []
            for combo_line in combos:
                parts = [p.strip() for p in re.split(r"\+|,| and ", combo_line) if p.strip()]
                if len(parts) >= 2:
                    evo_node_name = f"{' + '.join(parts)}"
                    # runtime nodes/edges
                    get_or_create_node(evo_node_name, 'Evolution', '', None)
                    get_or_create_node(passive_name, 'Passive', page_url, icon)
                    for comp in parts:
                        get_or_create_node(comp, 'Passive', BASE_WIKI_URL + 'Passives', None)
                        relationships.append({
                            "id": f"r{len(relationships)}",
                            "type": 'HAS Evolution',
                            "style": {},
                            "properties": {},
                            "fromId": title_to_node_id[comp],
                            "toId": title_to_node_id[evo_node_name]
                        })
                    relationships.append({
                        "id": f"r{len(relationships)}",
                        "type": '',
                        "style": {},
                        "properties": {},
                        "fromId": title_to_node_id[evo_node_name],
                        "toId": title_to_node_id[passive_name]
                    })
                    # schema mirror
                    schema_get_or_create(evo_node_name, 'Evolution', '', None)
                    schema_get_or_create(passive_name, 'Passive', page_url, icon)
                    for comp in parts:
                        schema_get_or_create(comp, 'Passive', BASE_WIKI_URL + 'Passives', None)
                        schema_add_rel(comp, evo_node_name, 'HAS Evolution')
                    schema_add_rel(evo_node_name, passive_name, '')
    except Exception:
        print("[scraper] Passives section failed:")
        traceback.print_exc()

    # Re-load from CSVs to drive effect/requirement extraction (authoritative rows)
    def load_csv_rows(page_title: str) -> List[Dict[str, str]]:
        csv_path = OUTPUT_DIR / 'tables' / f"{safe_slug(page_title)}.csv"
        rows: List[Dict[str, str]] = []
        if not csv_path.exists():
            return rows
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
        return rows

    char_rows = load_csv_rows('Characters')
    ball_rows = load_csv_rows('Balls')
    passive_rows = load_csv_rows('Passives')

    # Effects extraction utilities
    def normalize_effect(raw: str) -> Optional[str]:
        if not raw:
            return None
        s = raw.strip().lower()
        # simple stemming
        s = re.sub(r"[.,()\[\]{}!?:;'\"]+", '', s)
        s = re.sub(r"ing$|ed$|s$", '', s)  # crude
        # map common roots
        replacements = {
            'bleeding': 'bleed', 'bleed': 'bleed',
            'burnt': 'burn', 'burn': 'burn',
            'freez': 'freeze', 'frozen': 'freeze', 'freeze': 'freeze',
            'poison': 'poison', 'poisoned': 'poison',
            'charm': 'charm', 'charmed': 'charm',
            'curse': 'curse', 'cursed': 'curse',
            'overgrowth': 'overgrowth', 'overgrown': 'overgrowth',
            'disease': 'disease', 'diseased': 'disease',
            'radiation': 'radiation',
            'blind': 'blind', 'blinded': 'blind', 'blindness': 'blind',
            'crit': 'critical chance', 'critical': 'critical chance',
            'ally': 'allies', 'allies': 'allies'
        }
        # prefer substring containment to canonicalize even if embedded
        for k, v in replacements.items():
            if k in s:
                return v.title()
        return s.title()

    effect_title_to_id: Dict[str, str] = {}

    def get_or_create_effect(effect_name: str, is_aoe: Optional[bool] = None) -> str:
        effect_name = effect_name.strip()
        if not effect_name:
            return ''
        key = effect_name.lower()
        if key in effect_title_to_id:
            # upgrade AOE flag if provided
            if is_aoe is True:
                eff_id = effect_title_to_id[key]
                for n in nodes:
                    if n["id"] == eff_id:
                        n.setdefault("properties", {})
                        n["properties"]["isAOE"] = True
                        break
            return effect_title_to_id[key]
        node_id = f"n{len(nodes)}"
        effect_title_to_id[key] = node_id
        nodes.append({
            "id": node_id,
            "caption": effect_name,
            "labels": ["Effect"],
            "properties": {"url": "", "imagePath": "", "description": "", "isAOE": bool(is_aoe) if is_aoe is not None else False},
            "style": {},
        })
        return node_id

    def mark_effect_aoe(effect_name: str):
        if not effect_name:
            return
        _ = get_or_create_effect(effect_name, is_aoe=True)

    # Interaction nodes (Wall, Projectile, Bounce, Heal, Instant Kill, Full Screen, Area Of Effect, etc.)
    interaction_title_to_id: Dict[str, str] = {}

    def normalize_interaction(raw: str) -> Optional[str]:
        if not raw:
            return None
        s = raw.strip().lower()
        maps = {
            'wall': 'Wall',
            'projectile': 'Projectile',
            'bounce': 'Bounce', 'bouncing': 'Bounce',
            'heal': 'Heal', 'heals': 'Heal', 'healing': 'Heal',
            'instant kill': 'Instant Kill', 'instantly kill': 'Instant Kill',
            'instantly dying': 'Instant Kill', 'dying immediately': 'Instant Kill',
            'chance of killing enemies': 'Instant Kill', 'kill': 'Instant Kill',
            'full screen': 'Full Screen', 'in view': 'Full Screen',
            'all active enemies': 'Full Screen', 'all enemies on screen': 'Full Screen',
            'every enemy on screen': 'Full Screen',
            'area of effect': 'Area Of Effect', 'aoe': 'Area Of Effect',
        }
        for k, v in maps.items():
            if k in s:
                return v
        return raw.strip().title()

    def get_or_create_interaction(name: str) -> str:
        name = (normalize_interaction(name) or '').strip()
        if not name:
            return ''
        key = name.lower()
        if key in interaction_title_to_id:
            return interaction_title_to_id[key]
        node_id = f"n{len(nodes)}"
        interaction_title_to_id[key] = node_id
        nodes.append({
            "id": node_id,
            "caption": name,
            "labels": ["Interaction"],
            "properties": {"url": "", "imagePath": "", "description": ""},
            "style": {},
        })
        return node_id

    def connect_has_interaction(from_name: str, interaction_name: str):
        if from_name not in title_to_node_id:
            return
        iid = get_or_create_interaction(interaction_name)
        if not iid:
            return
        relationships.append({
            "id": f"r{len(relationships)}",
            "type": 'HAS Interaction',
            "style": {},
            "properties": {},
            "fromId": title_to_node_id[from_name],
            "toId": iid
        })

    def connect_requires_interaction(from_name: str, interaction_name: str):
        if from_name not in title_to_node_id:
            return
        iid = get_or_create_interaction(interaction_name)
        if not iid:
            return
        relationships.append({
            "id": f"r{len(relationships)}",
            "type": 'REQUIRES',
            "style": {},
            "properties": {},
            "fromId": title_to_node_id[from_name],
            "toId": iid
        })

    def connect_has_effect(from_name: str, effect_name: str, is_aoe: Optional[bool] = None):
        norm = normalize_effect(effect_name)
        if not norm:
            return
        eff_id = get_or_create_effect(norm, is_aoe=is_aoe)
        # ensure from node exists
        if from_name not in title_to_node_id:
            return
        relationships.append({
            "id": f"r{len(relationships)}",
            "type": 'HAS Effect',
            "style": {},
            "properties": {},
            "fromId": title_to_node_id[from_name],
            "toId": eff_id
        })

    def connect_requires_effect(from_name: str, effect_name: str):
        norm = normalize_effect(effect_name)
        if not norm:
            return
        eff_id = get_or_create_effect(norm)
        if from_name not in title_to_node_id:
            return
        relationships.append({
            "id": f"r{len(relationships)}",
            "type": 'REQUIRES',
            "style": {},
            "properties": {},
            "fromId": title_to_node_id[from_name],
            "toId": eff_id
        })

    def is_aoe_text(text: str) -> bool:
        if not text:
            return False
        t = text.lower()
        if 'area-of-effect' in t or 'area of effect' in t or 'aoe' in t:
            return True
        # Explicit triggers
        if 'tile radius' in t or 'tile square' in t:
            return True
        # Row/column wide effects
        if 'same row' in t or 'same column' in t:
            return True
        # general tile-based
        if 'tile' in t and ('square' in t or 'radius' in t):
            return True
        if 'within a' in t and 'radius' in t:
            return True
        return False

    # 1) Ball effects from descriptions
    for row in ball_rows:
        name = row.get('name') or ''
        desc = (row.get('description') or '').lower()
        if not name:
            continue
        # stacks of X
        for m in re.finditer(r"stack[s]? of\s+([a-z\-]+)", desc):
            connect_has_effect(name, m.group(1), is_aoe=is_aoe_text(desc))
        # keywords (effects)
        for kw in ['freeze', 'blind', 'charm', 'curse', 'overgrowth', 'disease', 'radiation', 'burn', 'bleed', 'poison']:
            if kw in desc:
                connect_has_effect(name, kw, is_aoe=is_aoe_text(desc))
                if is_aoe_text(desc):
                    mark_effect_aoe(kw)
        # interactions
        if 'wall' in desc:
            connect_has_interaction(name, 'Wall')
        if 'projectile' in desc:
            connect_has_interaction(name, 'Projectile')
        if 'bounc' in desc:
            connect_has_interaction(name, 'Bounce')
        if 'heal' in desc or 'heals' in desc or 'healing' in desc:
            connect_has_interaction(name, 'Heal')
        if any(k in desc for k in ['instantly kill', 'instantly dying', 'dying immediately', 'chance of killing enemies']):
            connect_has_interaction(name, 'Instant Kill')
        if any(k in desc for k in ['in view', 'all active enemies', 'all enemies on screen', 'every enemy on screen', 'full screen']):
            connect_has_interaction(name, 'Full Screen')
        # baby balls
        if 'baby ball' in desc:
            connect_has_effect(name, 'baby balls')
        # flag AOE on generic effect and connect ball -> AOE
        if is_aoe_text(desc):
            connect_has_effect(name, 'Area Of Effect', is_aoe=True)

    # 2) Passive requirements/effects
    effigy_passives = {r.get('name') for r in passive_rows if r.get('name') and 'effigy' in (r.get('name') or '').lower()}
    for row in passive_rows:
        pname = row.get('name') or ''
        desc = (row.get('description') or '').lower()
        req = (row.get('requirement') or '').lower()
        if not pname:
            continue
        # HAS Effect from description
        for m in re.finditer(r"stack[s]? of\s+([a-z\-]+)", desc):
            connect_has_effect(pname, m.group(1), is_aoe=is_aoe_text(desc))
        if 'crit' in desc or 'critical' in desc:
            connect_has_effect(pname, 'critical chance')
        for kw in ['freeze', 'blind', 'charm', 'curse', 'overgrowth', 'disease', 'radiation', 'burn', 'bleed', 'poison']:
            if kw in desc:
                connect_has_effect(pname, kw, is_aoe=is_aoe_text(desc))
                if is_aoe_text(desc):
                    mark_effect_aoe(kw)
        # baby balls effect from passive descriptions
        if 'baby ball' in desc or 'baby balls' in desc:
            connect_has_effect(pname, 'baby balls')
        if is_aoe_text(desc):
            connect_has_interaction(pname, 'Area Of Effect')
        # interactions from passive description
        if 'wall' in desc:
            connect_has_interaction(pname, 'Wall')
        if 'projectile' in desc:
            connect_has_interaction(pname, 'Projectile')
        if 'bounc' in desc:
            connect_has_interaction(pname, 'Bounce')
        if 'heal' in desc or 'heals' in desc or 'healing' in desc:
            connect_has_interaction(pname, 'Heal')
        if any(k in desc for k in ['instantly kill', 'instantly dying', 'dying immediately', 'chance of killing enemies']):
            connect_has_interaction(pname, 'Instant Kill')
        if any(k in desc for k in ['in view', 'all active enemies', 'all enemies on screen', 'every enemy on screen', 'full screen']):
            connect_has_interaction(pname, 'Full Screen')
        # allies spawned (exclude baby balls)
        if (('spawn a' in desc) or ('spawn an' in desc)) and ('baby ball' not in desc and 'baby balls' not in desc):
            connect_has_effect(pname, 'Allies')
        # REQUIRES effects from requirement
        for m in re.finditer(r"(stack[s]? of\s+([a-z\-]+))", req):
            connect_requires_effect(pname, m.group(2))
        if 'crit' in req or 'critical' in req:
            connect_requires_effect(pname, 'critical chance')
        for kw in ['freeze', 'blind', 'charm', 'curse', 'overgrowth', 'disease', 'radiation', 'burn', 'bleed', 'poison', 'ally', 'allies']:
            if kw in req:
                connect_requires_effect(pname, kw)
        # baby balls requirement mentions
        if 'baby ball' in req or 'baby balls' in req:
            connect_requires_effect(pname, 'baby balls')
        if is_aoe_text(req):
            connect_requires_interaction(pname, 'Area Of Effect')
        # interactions from requirement
        if 'wall' in req:
            connect_requires_interaction(pname, 'Wall')
        if 'projectile' in req:
            connect_requires_interaction(pname, 'Projectile')
        if 'bounc' in req:
            connect_requires_interaction(pname, 'Bounce')
        if 'heal' in req or 'heals' in req or 'healing' in req:
            connect_requires_interaction(pname, 'Heal')
        if any(k in req for k in ['instantly kill', 'instantly dying', 'dying immediately', 'chance of killing enemies']):
            connect_requires_interaction(pname, 'Instant Kill')
        if any(k in req for k in ['in view', 'all active enemies', 'all enemies on screen', 'every enemy on screen', 'full screen']):
            connect_requires_interaction(pname, 'Full Screen')
        # Allies/friendly pieces requirements should connect to all Effigy passives (providers of allies)
        if any(ph in req for ph in ['stone allies', 'stone ally', 'allies', 'ally', 'friendly pieces']):
            for eff in effigy_passives:
                if eff and eff in title_to_node_id and pname in title_to_node_id:
                    relationships.append({
                        "id": f"r{len(relationships)}",
                        "type": 'REQUIRES',
                        "style": {},
                        "properties": {},
                        "fromId": title_to_node_id[pname],
                        "toId": title_to_node_id[eff]
                    })
    # 3) Character ability interactions and AOE
    for row in char_rows:
        cname = row.get('name') or ''
        ability = (row.get('ability') or '').lower()
        if not cname:
            continue
        if 'wall' in ability:
            connect_has_effect(cname, 'Wall')
        if 'bounc' in ability:
            connect_has_effect(cname, 'Bounce')
        if 'projectile' in ability:
            connect_has_effect(cname, 'Projectile')
        if 'no baby ball' in ability:
            connect_has_effect(cname, 'No Baby Balls')
        if is_aoe_text(ability):
            connect_has_interaction(cname, 'Area Of Effect')
        # interactions from ability
        if 'wall' in ability:
            connect_has_interaction(cname, 'Wall')
        if 'projectile' in ability:
            connect_has_interaction(cname, 'Projectile')
        if 'bounc' in ability:
            connect_has_interaction(cname, 'Bounce')
        if 'heal' in ability or 'heals' in ability or 'healing' in ability:
            connect_has_interaction(cname, 'Heal')
        if any(k in ability for k in ['instantly kill', 'instantly dying', 'dying immediately', 'chance of killing enemies']):
            connect_has_interaction(cname, 'Instant Kill')
        if any(k in ability for k in ['in view', 'all active enemies', 'all enemies on screen', 'every enemy on screen', 'full screen']):
            connect_has_interaction(cname, 'Full Screen')

    # Also parse explicit e.g. (...) lists in passive requirements to specific passives
    for row in passive_rows:
        pname = row.get('name') or ''
        if not pname:
            continue
        eg_text = row.get('requirement') or ''
        for a in re.findall(r"\((?:e\.g\.|eg)\.?\s*([^\)]+)\)", eg_text, flags=re.IGNORECASE):
            for part in re.split(r",|;| and ", a):
                nm = part.strip().strip('"\'')
                if nm in title_to_node_id and pname in title_to_node_id:
                    relationships.append({
                        "id": f"r{len(relationships)}",
                        "type": 'REQUIRES',
                        "style": {},
                        "properties": {},
                        "fromId": title_to_node_id[pname],
                        "toId": title_to_node_id[nm]
                    })

    # 4) Effigies grant Allies effect explicitly
    for eff in effigy_passives:
        if eff:
            connect_has_effect(eff, 'Allies')

    # Write secondary output in schema
    schema_graph = {"nodes": schema_nodes, "relationships": schema_rels}
    with open((OUTPUT_DIR / 'graph_schema.json'), 'w', encoding='utf-8') as f:
        json.dump(schema_graph, f, indent=2, ensure_ascii=False)

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


