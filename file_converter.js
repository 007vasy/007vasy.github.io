const fs = require("fs");

let rawdata = fs.readFileSync("defillama_sample.json");
let info_json = JSON.parse(rawdata);

// {
//     "nodes": [
//       {
//         "id": "4062045",
//         "user": "mbostock",
//         "description": "Force-Directed Graph"
//       },
//     ]
//     "links": [
//         { "source": "950642", "target": "4062045" },
//     ]
// }

converted_info_json = {
  nodes: [],
  links: [],
};

info_json.forEach(protocol => {
  // Creating Protocol Nodes
  converted_info_json.nodes.push(
    {
      id: protocol.id,
      slug: protocol.slug,
      name: protocol.name,
      tvl: protocol.tvl,
      type: "Protocol",
    }
  )
  
  if(protocol.hasOwnProperty('oracles')){
    protocol.oracles.forEach(oracle => {
      // Creating Oracle Nodes
      converted_info_json.nodes.push(
        {
          id: oracle,
          name: oracle,
          type: "Oracle"
        }
      )
  
      // Creating Protocol - Oracle edges
      converted_info_json.links.push(
        {
          source: oracle,
          target: protocol.id
        }
      )
  
      })
  }

  if(protocol.hasOwnProperty('chains')){
    protocol.chains.forEach(chain => {
      // Creating Oracle Nodes
      converted_info_json.nodes.push(
        {
          id: chain,
          name: chain,
          type: "Chain"
        }
      )
      // Creating Protocol - Oracle edges
      converted_info_json.links.push(
        {
          source: chain,
          target: protocol.id
        }
      )

  
      })
  }

})

function uniqByKeepFirst(a, key) {
  let seen = new Set();
  return a.filter((item) => {
    let k = key(item);
    return seen.has(k) ? false : seen.add(k);
  });
}

converted_info_json.nodes = uniqByKeepFirst(
  converted_info_json.nodes,
  (item) => item.id
);

let data = JSON.stringify(converted_info_json);
fs.writeFileSync("docs/blocks.json", data);
