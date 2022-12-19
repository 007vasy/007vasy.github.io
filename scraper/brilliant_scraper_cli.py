import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path
import time

def site_content_as_text(url):
    reqs = requests.get(url)
    return BeautifulSoup(reqs.text, 'html.parser')

def create_full_link(partial_link):
    return f"https://brilliant.org{partial_link}"

def save_json(content,file_path:Path):
    with open(file_path, 'w') as f:
        json.dump(content, f, indent=4)

def main():
    url = 'https://brilliant.org/courses/'

    soup = site_content_as_text(url)
    
    nodes = []
    edges = []

    print(">> Grabbing Nodes")
    for container in soup.find_all('div', {"class":"container"}):
        h3 = container.find('h3',recursive=False)
        if h3 is not None:
            h3_text = h3.text.strip()
            print(f"Doing category {h3_text}")

            for link in container.find_all('a'):
                node_url = link.get('href')
                if node_url is not None and '/courses/' in node_url and "/#/" not in node_url and node_url != url:
                    nodes.append({
                        "id":create_full_link(node_url),
                        "name":link.text.strip(),
                        "type":h3_text
                    })

    print(f"Found {len(nodes)} nodes")

    print(">> Grabbing Edges")
    for node in nodes:
        max_tries = 10
        prev_edge_count = len(edges)
        node_url = node['id']
        tries = 0

        while tries <= max_tries and prev_edge_count == len(edges):
            
            if tries != 0:
                time.sleep(1    )

            course_page = site_content_as_text(node_url)
            print(f"Doing try {tries} >> {node_url} {len(edges)}")

            course_maps = course_page.find_all('div', {"class":"map-item"})

            if len(course_maps) == 0:
                print(f"{node_url} needs retry")



            for course_map in course_maps:
                #print(course_map)
                h5 = course_map.find('h5')
                conn_cat = h5.text.strip()

                for link in course_map.find_all('a', {"class":"course"}):
                    conn_url = create_full_link(link.get('href'))

                    if conn_cat == 'Prerequisites':
                        edge_type = 'PreReqOf'


                        edges.append({
                            "source":conn_url,
                            "target":node_url,
                            "type":edge_type,
                            "curvature":0.1,
                            "rotation":0.1
                        })
                    
                    elif conn_cat == 'Next steps':
                        edge_type = 'NextStep'


                        edges.append({
                            "source":node_url,
                            "target":conn_url,
                            "type":edge_type,
                            "curvature":-0.2,
                            "rotation":-0.2
                        })
                    
                    
                    else:
                        print(f"wrong state at {node_url}")

            tries += 1 

    print(f"Found {len(edges)} edges")

    graph = {
        "nodes":nodes,
        "links":edges
    }

    save_json(graph, Path(__file__).parent/'brilliant_temp.json')



if __name__ == "__main__":
    main()