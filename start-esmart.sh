#!/bin/sh
# Starts the eSMART bridge in the background
# (plus the HomeKit bridge if Node.js is installed).
cd "$(dirname "$0")" || exit 1
exec python3 esmart.py start "$@"
