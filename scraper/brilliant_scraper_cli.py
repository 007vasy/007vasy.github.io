import requests
from bs4 import BeautifulSoup
import json
from pathlib import Path

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
    links = []

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

    print(">> Grabbing Edges")
    for node in nodes:
        node_url = node['id']
        course_page = site_content_as_text(node_url)
        print(f"Doing >> {node_url}")
        for course_map in course_page.find_all('div', {"class":"map-item"}):
            #print(course_map)
            h5 = course_map.find('h5')
            conn_cat = h5.text.strip()

            for link in course_map.find_all('a'):
                conn_url = create_full_link(link.get('href'))

                if conn_cat == 'Prerequisites':
                    edge_type = 'PreReqOf'


                    links.append({
                        "source":conn_url,
                        "target":node_url,
                        "type":edge_type,
                        "curvature":0.1,
                        "rotation":0.1
                    })
                
                elif conn_cat == 'Next steps':
                    edge_type = 'NextStep'


                    links.append({
                        "source":node_url,
                        "target":conn_url,
                        "type":edge_type,
                        "curvature":-0.2,
                        "rotation":-0.2
                    })
                
                
                else:
                    print(f"wrong state at {node_url}")


    graph = {
        "nodes":nodes,
        "links":links
    }

    save_json(graph, Path(__file__).parent/'brilliant_temp.json')



if __name__ == "__main__":
    main()