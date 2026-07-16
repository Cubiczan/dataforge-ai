#!/usr/bin/env bash
# Push the DataForge AI repo to all three remotes.
#
# Prerequisites:
#   1. Create empty repos on each platform (do NOT initialize with README):
#        - https://github.com/new          -> Cubiczan/dataforge-ai        (private or public)
#        - https://github.com/new          -> Icohangar-Ops/dataforge-ai   (private or public)
#        - https://codeberg.org/repo/create -> Cubiczan/dataforge-ai       (or Icohangar-Ops)
#
#   2. Generate Personal Access Tokens with `repo` scope:
#        GitHub:  https://github.com/settings/tokens/new?scopes=repo
#        Codeberg: https://codeberg.org/user/settings/applications
#
#   3. Export them as env vars (don't commit them):
#        export GH_CUBICZAN_TOKEN=ghp_xxx
#        export GH_ICOHANGAR_TOKEN=ghp_yyy
#        export CODEBERG_TOKEN=zzz
#
#   4. Run this script from the repo root:
#        bash scripts/push_all.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

: "${GH_CUBICZAN_TOKEN:?Need to export GH_CUBICZAN_TOKEN}"
: "${GH_ICOHANGAR_TOKEN:?Need to export GH_ICOHANGAR_TOKEN}"
: "${CODEBERG_TOKEN:?Need to export CODEBERG_TOKEN}"

# Inject token into remote URLs (in-memory only; not persisted to .git/config)
git remote set-url origin    "https://Cubiczan:${GH_CUBICZAN_TOKEN}@github.com/Cubiczan/dataforge-ai.git"
git remote set-url mirror    "https://Icohangar-Ops:${GH_ICOHANGAR_TOKEN}@github.com/Icohangar-Ops/dataforge-ai.git"
git remote set-url codeberg  "https://Cubiczan:${CODEBERG_TOKEN}@codeberg.org/Cubiczan/dataforge-ai.git"

echo "==> [1/3] Pushing to GitHub / Cubiczan (origin)..."
git push -u origin main

echo "==> [2/3] Pushing to GitHub / Icohangar-Ops (mirror)..."
git push -u mirror main

echo "==> [3/3] Pushing to Codeberg (codeberg)..."
git push -u codeberg main

# Restore URLs to their clean (tokenless) form so we don't leak tokens in .git/config
git remote set-url origin    "https://github.com/Cubiczan/dataforge-ai.git"
git remote set-url mirror    "https://github.com/Icohangar-Ops/dataforge-ai.git"
git remote set-url codeberg  "https://codeberg.org/Cubiczan/dataforge-ai.git"

echo
echo "All three remotes pushed. URLs:"
echo "  https://github.com/Cubiczan/dataforge-ai"
echo "  https://github.com/Icohangar-Ops/dataforge-ai"
echo "  https://codeberg.org/Cubiczan/dataforge-ai"
