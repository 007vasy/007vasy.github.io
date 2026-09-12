# 007vasy.github.io

## /tech-tree

based on the https://foresight.org/tech-tree/

### list of trees as of 02/2023
* https://foresight.org/ext/ForesightNanotechTree/
* https://foresight.org/ext/ForesightNeurotechTree/
* https://foresight.org/ext/ForesightIntcoopTree/
* https://foresight.org/ext/ForesightSpaceTree/
* https://foresight.org/ext/ForesightTechTree/

### pre processing code in the /scraper folder

## /defi
visualise the defi universe based on the defillama endpoint 

### Defillama endpoint used

https://api.llama.fi/protocols
https://api.llama.fi/protocol/:slug

## /brilliant

3d viz of brilliant courses

## /cosmere

WIP 3d viz of the great Brian Sanderson's fantasy universe

## /ccip

visulisation of CCIP lanes, go for [https://docs.chain.link/ccip/supported-networks](https://docs.chain.link/ccip/supported-networks) for up-to-date information

## /podcast-hops

shortest path between people via podcast guest appearances. Default: Chiara Marletto from Eric Smith. Guests are extracted with spaCy (`en_core_web_sm`) plus title parsers. Weekly GitHub Action (`.github/workflows/update-podcast-hops.yml`) only NER’s new RSS items and keeps `docs/podcast-hops/episodes.json` as incremental state.

```bash
python scraper/podcast_hops.py            # reuse cached episodes
python scraper/podcast_hops.py --full-refresh
```

## Local dev
```bash
nodemon index.js
```
