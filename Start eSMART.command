#!/bin/bash
# Double-click me. Starts the eSMART bridge in the background
# (plus the HomeKit bridge if Node.js is installed).
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed yet."
  echo
  echo "macOS can install it with one click: press Install in the dialog that"
  echo "opens, wait for it to finish, then double-click this file again."
  echo
  xcode-select --install 2>/dev/null
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

python3 esmart.py start "$@"
status=$?
echo
read -n 1 -s -r -p "Press any key to close this window..."
exit $status
