import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

class PhysLeanGraphBuilder:
    def __init__(self, physlean_path: str, output_path: str):
        self.physlean_path = Path(physlean_path)
        self.output_path = Path(output_path)
        self.nodes = []
        self.links = []
        self.node_id_counter = 0
        self.node_id_map = {}  # Maps node identifiers to numeric IDs
        
        # Regex patterns for parsing Lean files
        self.namespace_pattern = re.compile(r'namespace\s+([A-Za-z0-9_\.]+)')
        self.abbrev_pattern = re.compile(r'abbrev\s+([A-Za-z0-9_\.]+)')
        self.structure_pattern = re.compile(r'structure\s+([A-Za-z0-9_\.]+)')
        self.import_pattern = re.compile(r'import\s+([A-Za-z0-9_\.]+)')
        self.open_pattern = re.compile(r'open\s+([A-Za-z0-9_\.]+)')

    def get_or_create_node_id(self, identifier: str, node_type: str, name: str = None, parent_path: str = None) -> int:
        """Get existing node ID or create a new one."""
        if identifier in self.node_id_map:
            return self.node_id_map[identifier]
        
        node_id = self.node_id_counter
        self.node_id_counter += 1
        self.node_id_map[identifier] = node_id
        
        # Create the node
        node = {
            "id": node_id,
            "name": name or identifier.split('/')[-1] if '/' in identifier else identifier,
            "type": node_type,
            "identifier": identifier
        }
        
        if parent_path:
            node["parent"] = parent_path
            
        self.nodes.append(node)
        return node_id

    def scan_directory(self, directory: Path) -> None:
        """Recursively scan directory for Lean files and build graph nodes."""
        for item in directory.iterdir():
            if item.is_dir():
                # Add directory as node
                rel_path = item.relative_to(self.physlean_path)
                dir_id = self.get_or_create_node_id(str(rel_path), 'directory', item.name)
                
                # Create parent-child relationship if not root
                if rel_path.parent != Path('.'):
                    parent_id = self.get_or_create_node_id(str(rel_path.parent), 'directory')
                    self.links.append({
                        "source": parent_id,
                        "target": dir_id,
                        "type": "contains",
                        "curvature": 0.1,
                        "rotation": 0.1
                    })
                
                self.scan_directory(item)
                
            elif item.suffix == '.lean':
                # Add file as node
                rel_path = item.relative_to(self.physlean_path)
                file_id = self.get_or_create_node_id(str(rel_path), 'file', item.stem)
                
                # Create parent-child relationship with directory
                parent_dir = rel_path.parent
                if parent_dir != Path('.'):
                    parent_id = self.get_or_create_node_id(str(parent_dir), 'directory')
                    self.links.append({
                        "source": parent_id,
                        "target": file_id,
                        "type": "contains",
                        "curvature": 0.1,
                        "rotation": 0.1
                    })
                
                self.process_lean_file(item)

    def process_lean_file(self, file_path: Path) -> None:
        """Process a Lean file to extract namespaces, abbreviations, and structures."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Skip files that can't be decoded
            return
            
        rel_path = file_path.relative_to(self.physlean_path)
        file_id = self.node_id_map[str(rel_path)]
        
        # Extract namespaces
        for match in self.namespace_pattern.finditer(content):
            namespace = match.group(1)
            namespace_id = self.get_or_create_node_id(f"{rel_path}:namespace:{namespace}", 'namespace', namespace, str(rel_path))
            self.links.append({
                "source": file_id,
                "target": namespace_id,
                "type": "defines",
                "curvature": 0.2,
                "rotation": 0.2
            })
            
        # Extract abbreviations
        for match in self.abbrev_pattern.finditer(content):
            abbrev = match.group(1)
            abbrev_id = self.get_or_create_node_id(f"{rel_path}:abbrev:{abbrev}", 'abbrev', abbrev, str(rel_path))
            self.links.append({
                "source": file_id,
                "target": abbrev_id,
                "type": "defines",
                "curvature": 0.2,
                "rotation": 0.2
            })
            
        # Extract structures
        for match in self.structure_pattern.finditer(content):
            structure = match.group(1)
            structure_id = self.get_or_create_node_id(f"{rel_path}:structure:{structure}", 'structure', structure, str(rel_path))
            self.links.append({
                "source": file_id,
                "target": structure_id,
                "type": "defines",
                "curvature": 0.2,
                "rotation": 0.2
            })
            
        # Extract imports and opens
        for match in self.import_pattern.finditer(content):
            imported = match.group(1)
            # Create a reference node for the imported module
            import_id = self.get_or_create_node_id(f"import:{imported}", 'import', imported)
            self.links.append({
                "source": file_id,
                "target": import_id,
                "type": "imports",
                "curvature": -0.3,
                "rotation": -0.3
            })
            
        for match in self.open_pattern.finditer(content):
            opened = match.group(1)
            # Create a reference node for the opened module
            open_id = self.get_or_create_node_id(f"open:{opened}", 'open', opened)
            self.links.append({
                "source": file_id,
                "target": open_id,
                "type": "opens",
                "curvature": -0.2,
                "rotation": -0.2
            })

    def save_json(self) -> None:
        """Save the graph data as JSON in force3dgraph format."""
        graph_data = {
            "nodes": self.nodes,
            "links": self.links
        }
        
        # Ensure output directory exists
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save JSON file
        with open(self.output_path, 'w', encoding='utf-8') as f:
            json.dump(graph_data, f, indent=2, ensure_ascii=False)
        
        print(f"Graph saved to {self.output_path}")
        print(f"Total nodes: {len(self.nodes)}")
        print(f"Total links: {len(self.links)}")

def main():
    ROOT_DIR = Path(__file__).parent.parent
    physlean_path = ROOT_DIR.parent / Path('PhysLean/PhysLean')
    output_path = ROOT_DIR / Path('docs/physlean/physlean_graph.json')
    
    if not physlean_path.exists():
        print(f"Error: PhysLean path does not exist: {physlean_path}")
        return
    
    builder = PhysLeanGraphBuilder(physlean_path, output_path)
    print("Scanning PhysLean repository...")
    builder.scan_directory(physlean_path)
    print("Saving graph data...")
    builder.save_json()

if __name__ == '__main__':
    main()
