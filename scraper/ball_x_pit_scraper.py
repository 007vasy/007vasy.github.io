import os
import re
import time
import json
import csv
import pathlib
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

    def get_or_create_node(name: str, label: str, page_url: str, icon_url: Optional[str]) -> str:
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
            "properties": {"url": page_url, "imagePath": image_path_rel or ""},
            "style": {},
        })
        return node_id

    def schema_get_or_create(name: str, label: str, page_url: str, icon_url: Optional[str]) -> str:
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
            "properties": {"url": page_url, "imagePath": image_path_rel or ""}
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
                if val['name']:
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
        fieldnames = ['name', 'page_url', 'icon', 'ball', 'passive', 'evolutions', 'combinations']
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
            # try fallback icon from character page if missing
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            char_id = get_or_create_node(char_name, 'Character', page_url, icon)
            schema_get_or_create(char_name, 'Character', page_url, icon)
            ball_name = (row.get('ball') or '').strip()
            if ball_name:
                ball_id = get_or_create_node(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                add_edge(char_name, ball_name, 'Starts With')
                # schema
                schema_get_or_create(ball_name, 'Ball', BASE_WIKI_URL + 'Balls', None)
                schema_add_rel(char_name, ball_name, 'Starts With')
    except Exception:
        pass

    # Parse Balls
    try:
        ball_rows = parse_table('Balls')
        dump_rows_to_csv('Balls', ball_rows)
        for row in ball_rows:
            ball_name = row.get('name')
            icon = row.get('icon')
            page_url = row.get('page_url') or (BASE_WIKI_URL + 'Balls')
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            get_or_create_node(ball_name, 'Ball', page_url, icon)
            schema_get_or_create(ball_name, 'Ball', page_url, icon)
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
        pass

    # Parse Passives
    try:
        passive_rows = parse_table('Passives')
        dump_rows_to_csv('Passives', passive_rows)
        for row in passive_rows:
            passive_name = row.get('name')
            icon = row.get('icon')
            page_url = row.get('page_url') or (BASE_WIKI_URL + 'Passives')
            if not icon and row.get('link_title'):
                try:
                    icon = find_infobox_image(fetch_html(row['link_title']))
                except Exception:
                    icon = None
            get_or_create_node(passive_name, 'Passive', page_url, icon)
            schema_get_or_create(passive_name, 'Passive', page_url, icon)
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
        pass

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


