#!/usr/bin/env sh
# Start the FoE Alerting control panel (Linux / macOS).
#
# No install step on purpose: the alerter imports nothing outside the standard library, so all
# this does is point PYTHONPATH at src/ and run the module. Any argument you pass is handed to
# `bap-alert ui` — e.g. ./foe-alerting.sh --port 9000
#
# See docs/FOE_ALERTING_SETUP.md.

set -eu

cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
           >/dev/null 2>&1; then
            PY="$candidate"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3.11 or newer is required and was not found on PATH." >&2
    echo "Install it from https://www.python.org/downloads/ and run this again." >&2
    exit 1
fi

MAP_DATA="dataset/api_samples/map_data.volcano_archipelago.sample.json"
MAP_ARG=""
if [ -f "$MAP_DATA" ]; then
    # Gives the labels list its province dropdown; harmless when the file is absent.
    MAP_ARG="--map-data $MAP_DATA"
fi

echo "Starting the FoE Alerting panel with $($PY --version 2>&1)..."
echo "The URL below contains an access token - treat it like a password."
echo

# shellcheck disable=SC2086  # MAP_ARG is deliberately two words or none
PYTHONPATH=src exec "$PY" -m bap.alerting ui $MAP_ARG "$@"
