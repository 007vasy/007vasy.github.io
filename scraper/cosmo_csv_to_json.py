
FILE = "cosmo_test.csv"

import csv
import json

# CSV schema:
# source,target,size,time
# cryptojamie7,0xRacerAlt,4,1691704263000

# JSON schema:
# {
#   "nodes": [
#     {
#       "id": 0,
#       "url": "https://brilliant.org/courses/pre-algebra/",
#       "name": "Solving Equations",
#       "type": "Algebra",
#       "inDegree": 1,
#       "outDegree": 2
#     },
#   ]
#   "links": [
#     {
#       "source": 0,
#       "target": 11,
#       "type": "NextStep",
#       "curvature": -0.2,
#       "rotation": -0.2
#     },
#   ]
# }

def cosmo_csv_to_force_3d_graph_json(file):

    with open(file, 'r') as f:
        reader = csv.reader(f)
        
        for row in next(reader):
            print(row)


def main():
    cosmo_csv_to_force_3d_graph_json(FILE)

if __name__ == "__main__":
    main()