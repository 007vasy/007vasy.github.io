# An Easy way to put data on a blockchain
 * __NOTE__: There are other ways
 * __NOTE__: This was written for a person who are in the Web2 world, but had not wandered into Web3, but would like to.

# Setup
 1. Get a *[web3 wallet](https://everyrealm.com/blog/education/set-up-metamask)* { [Metamask](https://metamask.io/) or [alternatives](https://www.g2.com/products/metamask/competitors/alternatives) }
 1. [Get some founds on mumbai](https://mumbaifaucet.com/) { for [gas](https://ethereum.org/en/developers/docs/gas/) on a testnet for example [polygon mumbai](https://mumbaifaucet.com/) }
 1. [Get some testnet LINK on mumbai](https://faucets.chain.link/mumbai) {you will need it to for putting data this way on-chain, is this example it's on Mumbai}
 1. [Fork the CL function repo](https://github.com/smartcontractkit/functions-hardhat-starter-kit/fork)
 1. [Get yourself whitelisted on CL Functions with your web3 wallet address on mumbai](https://functions.chain.link/) {currently you need this, later this step is not needed}
 1. [Follow the insturctions here in the CL Function repo for the setup](https://github.com/smartcontractkit/functions-hardhat-starter-kit#quickstart)

# Putting the data on chain
 * edit the [calculation-example.js](https://github.com/smartcontractkit/functions-hardhat-starter-kit/blob/main/calculation-example.js) file to fetch an api
 * follow the deploy and setup instructions [there](https://github.com/smartcontractkit/functions-hardhat-starter-kit#quickstart)
 * ?
 * Profit

# Ask for help!

If you feel stuck and don't know who to ask try [ChatGPT](https://chat.openai.com/chat) or [Chainlink](https://discord.com/invite/59Zf9apMC8)

# Where to learn more

 * in general [freecodecamp.org](https://www.freecodecamp.org/) is great to learn Python, JS, Solidity
 * for solidity the best is [https://cryptozombies.io/](https://cryptozombies.io/) and later either:
    * [JS+Solidity](https://www.youtube.com/watch?v=gyMwXuJrbJQ)
    * [Python+Solidity](https://www.youtube.com/watch?v=M576WGiDBdQ)
 * More about [Chainlink functions by Patrick Collins](https://www.youtube.com/watch?v=kFmOef5jL7w)
 * [More resourrces](https://www.blockchain.education/learn#evm-chains)
 * [Some People say Vyper is the future, check it out, it's more pythonic](https://learn.vyperlang.org/#/)

# Security

* *Audits* if you plan to run your project on mainnets, it's recommended to run an [audit](https://consensys.net/diligence/)
* *Multisig* on the same note, it's recommended to think about using [multi sig](https://github.com/safe-global/safe-contracts) on your project
* *Hardware wallet* thirdly, hot wallets are great, but you should have also a hardware wallet, [Trezor](https://trezor.io/compare) or [Ledger](https://www.ledger.com/) to secure your funds better


# FAQ
*+1 DANGER* this is how you can export your [dev private key wallet](https://support.metamask.io/hc/en-us/articles/360015289632-How-to-export-an-account-s-private-key)
(__*USE A SEPARATE WALLET FOR DEVELOPMENT!!!*__)[https://www.gemini.com/cryptopedia/crypto-wallets-hot-cold#section-hot-wallets-pros-and-cons]








