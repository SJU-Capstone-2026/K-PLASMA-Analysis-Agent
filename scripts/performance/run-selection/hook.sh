#!/bin/sh
set -eu
node scripts/performance/run-selection/browser.mjs "$1" "$2"
python3 scripts/performance/run-selection/api.py "$1" "$2"
python3 scripts/performance/run-selection/actions.py "$1" "$2"
