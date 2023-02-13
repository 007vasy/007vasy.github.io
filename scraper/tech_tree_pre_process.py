
from utils import save_json
from pathlib import Path
import json

TECH_TREE_FOLDER = Path(__file__).parent /"tech_tree_raw_data"

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
                        'fill':item.get('fill','red'),
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

    save_json(processed_data, Path(__file__).parent/'tech_tree.json')        

if __name__ == "__main__":
    main()
