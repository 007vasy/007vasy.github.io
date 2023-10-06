import requests
from bs4 import BeautifulSoup
import json

def extract_ccip_info(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    data = {"nodes": [], "links": []}
    raw_lanes = []
    for section in soup.find_all('section'):
        for a in section.find_all('a'):
            url = a['href']
            if "--" in url:
                raw_lanes.append(url.replace("#","").replace("-lane","").split('--'))

    # add nodes from raw_lanes
    nodes = []
    links = []

    for lane_source, lane_target  in raw_lanes:
        if lane_source not in nodes:
            nodes.append(lane_source)
        if lane_target not in nodes:
            nodes.append(lane_target)

    for id, node in enumerate(nodes):
        data["nodes"].append({"id": id, "name": node, "url": f"https://docs.chain.link/ccip/supported-networks/#{node}"})

    # add links from raw_lanes
    for lane_source, lane_target in raw_lanes:
        source = nodes.index(lane_source)
        target = nodes.index(lane_target)
        data["links"].append(
            {
                "source": source,
                "target": target,
                "name": f"{lane_source} -->> {lane_target}",
                "url": f"https://docs.chain.link/ccip/supported-networks/#{lane_source}--{lane_target}-lane",
                "curvature": 0.2,
                "rotation": 0.5
            }
            )

    with open('ccip_info.json', 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == '__main__':

    url = 'https://docs.chain.link/ccip/supported-networks'
    extract_ccip_info(url)
