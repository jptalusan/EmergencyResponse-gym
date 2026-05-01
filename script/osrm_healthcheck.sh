#!/usr/bin/env bash
set -e

HOST="127.0.0.1"
PORT="5000"
COORD="-86.7816,36.1627"

# Open TCP connection
exec 3<>/dev/tcp/${HOST}/${PORT} || exit 1

# Send HTTP request
printf "GET /nearest/v1/driving/%s HTTP/1.1\r\nHost: localhost\r\n\r\n" "$COORD" >&3

# Read response (with timeout) and check result
if timeout 2 cat <&3 | grep -m1 '"code":"Ok"' > /dev/null; then
  exit 0
else
  exit 1
fi
