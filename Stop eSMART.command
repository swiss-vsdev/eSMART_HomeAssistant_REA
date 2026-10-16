#!/bin/bash
# Double-click me. Stops the eSMART bridge and the HomeKit bridge.
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed, so nothing can be running."
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

python3 esmart.py stop "$@"
echo
read -n 1 -s -r -p "Press any key to close this window..."
