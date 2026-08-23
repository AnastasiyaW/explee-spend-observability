#!/bin/bash
# Publish what the collector produced to the orphan `data` branch.
#
# Two files, not one. data.json is what the dashboard reads; alerts.jsonl is a
# deliverable in its own right, and for most of this run it existed only on the
# collector host - which meant the README linked to a 404 and the alert log was,
# in practice, undeliverable. A file nobody can fetch is not published.
#
# Plain fast-forward commits: rewriting a published branch is a destructive
# operation and this snapshot is not worth one. The cost is history growth on a
# throwaway branch, which is the cheaper side of that trade.
set -euo pipefail

HOME_DIR=${EXPLEE_HOME:-$HOME/explee-monitor}
# docs/, matching the collector's own default. These two defaults were
# allowed to disagree once: the collector was pointed at docs/ and this
# script kept copying dashboard/, so the site served a three-hour-old
# snapshot while both halves reported success.
SNAPSHOT=${EXPLEE_SNAPSHOT:-$HOME_DIR/docs/data.json}
ALERTS=${EXPLEE_ALERTS:-$HOME_DIR/alerts.jsonl}
WORKTREE=$HOME_DIR/publish

[ -s "$SNAPSHOT" ] || exit 0
cd "$WORKTREE"

cp "$SNAPSHOT" data.json
# The alert log can legitimately be empty early in a run; publish it anyway, so
# "no alerts yet" is a fact a reader can check rather than a missing file.
if [ -f "$ALERTS" ]; then
  cp "$ALERTS" alerts.jsonl
else
  : > alerts.jsonl
fi

git add data.json alerts.jsonl
git diff --cached --quiet && exit 0
git commit -q -m "spend snapshot"
GIT_SSH_COMMAND="ssh -i ~/.ssh/explee_deploy_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  git push -q origin data
