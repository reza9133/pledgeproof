# PledgeProof frontend

Static multi-page frontend for PledgeProof. No build step for the site itself.

- Pages: Home, Campaigns (live from chain), Campaign detail (`campaign.html?id=N`), My pledges, Launch, How it works
- Reads the `PledgeVault` contract directly through `genlayer-js`; no backend
- Writes are signed by the user's wallet: back, withdraw, cancel, close funding, submit proof, review, declare default, claim refund, launch
- Themes: Light, Dim, Dark (saved in localStorage)
- Wallets: discovered through EIP-6963; the Studio network (chain id 61999) is added to the wallet when needed
- The contract address, RPC and explorer links live in `js/config.js`

## No CDN dependencies

Everything the pages need is in this folder:

- `js/vendor/genlayer.js`: the SDK, bundled for the browser (rebuild with `tools/build-vendor.sh`)
- `js/vendor/three.min.js`: only loaded on the home page, only when motion is allowed; the page works without it
- `assets/fonts/`: the two fonts as WOFF2 (latin subset)

Licenses are listed in `js/vendor/LICENSES.md`.

## What the pages do to stay honest

- **Transaction links.** After every transaction the hash is shown with a "Copy hash" button and a link to the explorer. The link
  comes from `explorerTx` in `js/config.js` (`{hash}` is replaced by the hash). If the explorer uses another path, change it there.
- **Time.** The contract decides deadlines with the transaction's timestamp. The pages measure the visitor's device clock against
  the `Date` header of the web server that served the site and correct for it. A note appears when the device is off by 2 minutes
  or more. If the clock cannot be checked (for example the site is opened from `file://`), the "Run validator review" button is not
  locked and the contract has the final say.
- **Old data.** If the RPC does not answer after several tries, the last answer saved in this tab (sessionStorage) is shown, with a
  notice at the top of the page saying when it was saved and a Retry button.
- **Numbers.** Amounts accept Persian/Arabic digits and `٫` or `,` as the decimal separator.

## Run locally

```
python3 -m http.server 8000
```

Open http://localhost:8000. Deploy to GitHub Pages or any static host (the host must send a `Date` header, which all common hosts do).
