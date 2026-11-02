#!/usr/bin/env bash
# Publish the personal branch to Forgejo and refresh the generic branch for GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."

git push forgejo personal

git checkout main
git merge personal --no-edit
if git ls-files --error-unmatch personal/README.md >/dev/null 2>&1; then
    git rm -r --cached personal >/dev/null
    rm -rf personal
    git commit -m "chore: keep the personal overlay off the public branch"
fi
git push origin main
git checkout personal
