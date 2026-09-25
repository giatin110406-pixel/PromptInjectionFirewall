#!/usr/bin/env bash
set -euo pipefail

REMOTE_URL="${1:-https://github.com/giatin110406-pixel/PromptInjectionFirewall.git}"
BRANCH="${2:-main}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[ERROR] This is not a git repository. Run from the project root."
  exit 1
fi

if [ -z "$(git status --porcelain)" ]; then
  echo "[INFO] Working tree is clean. Nothing to commit."
else
  git add .
  git commit -m "chore: update project files"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "$REMOTE_URL"
else
  git remote set-url origin "$REMOTE_URL"
fi

git branch -M "$BRANCH"
git push -u origin "$BRANCH"

echo "[SUCCESS] Pushed to GitHub: $REMOTE_URL on branch $BRANCH"
