#!/usr/bin/env bash
# Publish the personal branch to Forgejo and refresh the generic branch for GitHub.
set -euo pipefail
cd "$(dirname "$0")/.."

git push --force-with-lease forgejo personal

git checkout main
set +e
git merge personal --no-edit
merge_status=$?
set -e
if [ "$merge_status" -ne 0 ]; then
    # The overlay is deleted on main and changed on personal: keep the deletion.
    git rm -r --cached personal >/dev/null 2>&1 || true
    rm -rf personal
    git commit --no-edit
fi
if git ls-files --error-unmatch personal/README.md >/dev/null 2>&1; then
    git rm -r --cached personal >/dev/null
    rm -rf personal
    git commit -m "chore: keep the personal overlay off the public branch"
fi
git push origin main
git push forgejo main
git checkout personal
