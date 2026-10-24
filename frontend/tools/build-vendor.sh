#!/bin/sh
# Rebuilds frontend/js/vendor/genlayer.js: genlayer-js (and viem) bundled for the browser, so the site does not load the SDK
# from a CDN. Needs Node.js and network access to npm. Change the version below to upgrade the SDK, then re-test the site.
set -e
cd "$(dirname "$0")"
mkdir -p .build && cd .build
npm init -y >/dev/null 2>&1
npm i --silent genlayer-js@1.1.8 esbuild
cp ../vendor-entry.js entry.js
npx esbuild entry.js --bundle --format=esm --platform=browser --minify --target=es2020 \
  --define:process.env.NODE_ENV='"production"' --outfile=../../js/vendor/genlayer.js
echo "wrote frontend/js/vendor/genlayer.js"
