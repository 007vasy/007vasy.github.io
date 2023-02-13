
from utils import save_json
from pathlib import Path
import json

TECH_TREE_FOLDER = Path(__file__).parent /"tech_tree_raw_data"

def convert_color_hash_to_rgb(color_hash, subtree):
    color_palette = {
        'spacetree': 'rgb(50, 205, 50)',
        'nanotech': 'rgb(30, 144, 255)',
        'intcoop': 'rgb(255, 165, 0)',
        'neurotech': 'rgb(255, 192, 203)',
        'longevity': 'rgb(107, 142, 35)'
    }

    if subtree is not None:
        rgb_color = color_palette.get(subtree, 'rgb(255,0,0)')

    if color_hash is not None:
        # color_hash is in format #RRGGBB
        r = int(color_hash[1:3], 16)
        g = int(color_hash[3:5], 16)
        b = int(color_hash[5:7], 16)
        rgb_color = f'rgb({r},{g},{b})'

    return rgb_color

def main():

    processed_data = {
        'nodes':[],
        'links':[]
    }
    
    offset = 0

    # list all files in tech_tree folder
    for file in TECH_TREE_FOLDER.glob("*.graph"):
        raw_data = None
        with open(file, 'r') as f:
            raw_data = json.load(f)

        print(file) 

        short_name = file.stem.replace('.graph','')

        if raw_data is not None:

            max_id = 0
            for item in raw_data['items']:
                if item['kind'] == 'node':
                    new_id = item['id']+offset
                    max_id = max(max_id, item['id']+offset)
                    processed_data['nodes'].append({
                        'id':new_id,
                        'label':item['label'],
                        'fill':convert_color_hash_to_rgb(item.get('fill'),short_name),
                        'desc':item['desc'],
                        'tags':item['tags'],
                        'subtree':short_name
                    })
                    

                    if item['parent'] is not None:
                        processed_data['links'].append({
                            'source':new_id,
                            'target':item['parent']+offset,
                            'shape':'ortho',
                            'weight':10,
                            'directed':True,
                        })


                elif item['kind'] == 'edge':
                    if item.get('fromId') is None or item.get('toId') is None:
                        print(f'Edge fromId or toId is None: {item}')
                    else:
                        processed_data['links'].append({
                            'source':item['fromId']+offset,
                            'target':item['toId']+offset,
                            'shape':item['shape'],
                            'weight':item['weight'],
                            'directed':item['directed'],
                        })

                else:
                    print(f'Unknow item kind: {item["kind"]}')

            offset = max_id+1
        else:
            print(f'Raw data is None: {file}')
    
    degree_info = {}

    for edge in processed_data['links']:
        if edge['source'] not in degree_info:
            degree_info[edge['source']] = 0
        if edge['target'] not in degree_info:
            degree_info[edge['target']] = 0

        degree_info[edge['source']] += 1
        degree_info[edge['target']] += 1

    for node in processed_data['nodes']:
        node['degree'] = degree_info.get(node['id'], 0)

    save_json(processed_data, Path(__file__).parent/'tech_tree.json')        

if __name__ == "__main__":
    main()
