
FILE = "cosmo_test.csv"

import csv
import json
from tqdm import tqdm

# CSV schema:
# target,target,size,time
# cryptojamie7,0xRacerAlt,4,1691704263000

# JSON schema:
# {
#   "nodes": [
#     {
#       "id": 0,
#       "name": "Banteg",
#       "type": "User",
#     },
#   ]
#   "links": [
#     {
#       "source": 0,
#       "target": 11,
#       "type": "Follows",
#       "time": 1691704263000,
#     },
#   ]
# }
def add_user_to_force_3d_graph_json(id, user, force_3d_graph):

    force_3d_graph['nodes'].append({
        "id": id,
        "name": user,
        "type": "User",
    })

    return force_3d_graph

def cosmo_csv_to_force_3d_graph_json(file):

    force_3d_graph = {
        "nodes": [],
        "links": []
    }
    
    users = {}

    with open(file, 'r') as f:
        reader = csv.reader(f)
        
        for i, row in enumerate(tqdm(reader)):
            if i == 0:
                continue

            source = row[0]
            target = row[1]
            time = row[3]

            if source == target:
                continue

            if source not in users:
                users[source] = users.__len__()
                force_3d_graph = add_user_to_force_3d_graph_json(users[source], source, force_3d_graph)
            
            if target not in users:
                users[target] = users.__len__()
                force_3d_graph = add_user_to_force_3d_graph_json(users[target], target, force_3d_graph)

            # Add link
            force_3d_graph['links'].append({
                "source": users[source],
                "target": users[target],
                "type": "Follows",
                "time": time,
            })

    with open('../docs/banteg-friend-tech-3d/cosmo_test.json', 'w') as f:
        json.dump(force_3d_graph, f, indent=4)




def main():
    cosmo_csv_to_force_3d_graph_json(FILE)

if __name__ == "__main__":
    main()