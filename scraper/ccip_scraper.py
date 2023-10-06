import requests
from bs4 import BeautifulSoup
import json

def extract_ccip_info(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    data = {"nodes": [], "links": []}
    node_id = 1
    for section in soup.find_all('section'):
        print(section.prettify())

    with open('ccip_info.json', 'w') as f:
        json.dump(data, f, indent=2)

if __name__ == '__main__':

    url = 'https://docs.chain.link/ccip/supported-networks'
    extract_ccip_info(url)
