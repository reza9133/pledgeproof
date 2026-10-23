#!/usr/bin/env bash
# One-command runner for GitHub Codespaces (or any Linux/macOS shell with Python 3.12+).
#
#   bash scripts/codespaces_live.sh                 # offline gate, then the live Studionet E2E
#   bash scripts/codespaces_live.sh --skip-tests    # only the live E2E
#   bash scripts/codespaces_live.sh --only happy,cancel
#   bash scripts/codespaces_live.sh --long          # also the ~65 minute goal-missed flow
#
# Every other flag is passed to scripts/live_e2e.py (see --help there).
set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_TESTS=0
PASS=()
for arg in "$@"; do
  if [[ "$arg" == "--skip-tests" ]]; then SKIP_TESTS=1; else PASS+=("$arg"); fi
done

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

PY="${PYTHON:-python3}"
"$PY" - <<'PYCHECK'
import sys
if sys.version_info < (3, 12):
    sys.exit("Python 3.12+ is required (genlayer-py needs it). Found %s" % sys.version.split()[0])
PYCHECK

say "1/4  bundle the contract"
"$PY" scripts/bundle.py

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  say "2/4  offline gate: lint + the full test suite"
  if [[ ! -d .venv ]]; then "$PY" -m venv .venv; fi
  # shellcheck disable=SC1091
  . .venv/bin/activate
  pip install -q -r requirements-dev.txt
  # genlayer-test's direct mode downloads a GenVM release. GitHub's "latest" release can be a
  # pre-release without the file it needs (it answers 404), so pre-seed the cache with a
  # release that has it.
  CACHE="$HOME/.cache/gltest-direct"
  TARBALL="$CACHE/genvm-universal-v0.2.16.tar.xz"
  if [[ ! -s "$TARBALL" ]]; then
    mkdir -p "$CACHE"
    echo "downloading GenVM v0.2.16 test runtime (~200 MB, once)..."
    curl -fL --retry 3 -o "$TARBALL.part" \
      "https://github.com/genlayerlabs/genvm/releases/download/v0.2.16/genvm-universal.tar.xz"
    mv "$TARBALL.part" "$TARBALL"
  fi
  genvm-lint check dist/pledge_vault.bundle.py
  PP_FUZZ_SEEDS="${PP_FUZZ_SEEDS:-60}" pytest tests -q -p no:cacheprovider
  deactivate
else
  say "2/4  offline gate skipped"
fi

say "3/4  live environment (genlayer-py)"
if [[ ! -d .venv-live ]]; then "$PY" -m venv .venv-live; fi
# shellcheck disable=SC1091
. .venv-live/bin/activate
pip install -q -r requirements-live.txt

say "4/4  live end-to-end on Studionet"
echo "Accounts are throw-away testnet keys stored in .live_accounts.json (git-ignored)."
python scripts/live_e2e.py "${PASS[@]+"${PASS[@]}"}"
