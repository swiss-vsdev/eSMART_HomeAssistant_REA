#!/bin/sh
# Stops the eSMART bridge and the HomeKit bridge.
cd "$(dirname "$0")" || exit 1
exec python3 esmart.py stop "$@"
