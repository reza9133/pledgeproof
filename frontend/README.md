# PledgeProof frontend

Static multi-page frontend for PledgeProof. No build step.

- Pages: Home, Campaigns (live from chain), Campaign detail (`campaign.html?id=N`), Launch, How it works
- Reads the `PledgeVault` contract directly through `genlayer-js` (loaded from esm.sh); no backend
- Writes are signed by the user's wallet: back, withdraw, cancel, close funding, submit proof, review, declare default, claim refund, launch
- Themes: Light, Dim, Dark (saved in localStorage)
- Wallets: discovered through EIP-6963; the Studio network (chain id 61999) is added to the wallet on connect
- The contract address and network settings live in `js/config.js`

## Run locally

```
python3 -m http.server 8000
```

Open http://localhost:8000. Deploy to GitHub Pages or any static host.
