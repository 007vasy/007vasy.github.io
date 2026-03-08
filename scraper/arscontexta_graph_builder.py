# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Build a 3D force-graph JSON from the arscontexta markdown vault."""

import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

VAULT_DIR = Path(__file__).resolve().parent.parent.parent / "arscontexta"
OUTPUT_FILE = Path(__file__).parent.parent / "docs" / "arscontexta" / "graph.json"
GITHUB_BASE = "https://github.com/agenticnotetaking/arscontexta/blob/main"
WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

FOLDER_COLORS = {
    "methodology": "rgb(160, 85, 178)",   # purple
    "reference": "rgb(65, 135, 245)",      # blue
    "skills": "rgb(75, 190, 95)",          # green
    "skill-sources": "rgb(45, 180, 160)",  # teal
    "platforms": "rgb(240, 165, 50)",      # orange
    "generators": "rgb(230, 85, 85)",      # red
    "presets": "rgb(200, 170, 80)",        # gold
    "agents": "rgb(255, 130, 180)",        # pink
    "hooks": "rgb(140, 140, 140)",         # gray
    "scripts": "rgb(100, 100, 180)",       # slate
}
DEFAULT_COLOR = "rgb(180, 180, 180)"


def parse_frontmatter(text: str) -> dict:
    """Extract YAML frontmatter from markdown text."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def extract_wiki_links(text: str) -> list[str]:
    """Extract all [[wiki-link]] targets from text."""
    return WIKI_LINK_RE.findall(text)


def stem(name: str) -> str:
    """Normalize a filename/link to a comparable key."""
    return name.removesuffix(".md").strip()


def main():
    md_files = sorted(VAULT_DIR.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files")

    # Build lookup: stem -> file path (relative)
    file_lookup: dict[str, Path] = {}
    for f in md_files:
        rel = f.relative_to(VAULT_DIR)
        key = stem(f.name).lower()
        file_lookup[key] = rel

    nodes = []
    links = []
    degree: dict[str, int] = defaultdict(int)

    # First pass: build nodes and raw links
    raw_links: list[tuple[str, str]] = []

    for f in md_files:
        rel = f.relative_to(VAULT_DIR)
        node_id = stem(f.name)
        folder = rel.parts[0] if len(rel.parts) > 1 else ""
        text = f.read_text(errors="replace")
        fm = parse_frontmatter(text)

        description = fm.get("description", "")
        kind = fm.get("type", fm.get("kind", ""))

        # Extract all wiki-links from the entire file
        targets = extract_wiki_links(text)
        for target in targets:
            target_key = target.strip().lower()
            if target_key in file_lookup:
                raw_links.append((node_id, stem(file_lookup[target_key].name)))

        url = f"{GITHUB_BASE}/{rel}"
        color = FOLDER_COLORS.get(folder, DEFAULT_COLOR)

        nodes.append({
            "id": node_id,
            "label": node_id,
            "desc": description[:120] if description else "",
            "folder": folder,
            "kind": kind,
            "fill": color,
            "url": url,
            "degree": 0,  # filled in second pass
        })

    # Build node-to-folder lookup
    node_folder = {n["id"]: n["folder"] for n in nodes}

    # Deduplicate links and compute degree
    seen_links = set()
    for source, target in raw_links:
        if source == target:
            continue
        key = (source, target)
        if key not in seen_links:
            seen_links.add(key)
            same_folder = node_folder.get(source) == node_folder.get(target)
            links.append({
                "source": source,
                "target": target,
                "type": "same-folder" if same_folder else "cross-folder",
            })
            degree[source] += 1
            degree[target] += 1

    # Update degree on nodes
    for node in nodes:
        node["degree"] = degree.get(node["id"], 0)

    graph = {"nodes": nodes, "links": links}

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(graph, indent=2))
    print(f"Wrote {len(nodes)} nodes, {len(links)} links to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
