#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 http://IPHONE:8090 GIT_URL [REF] [SUBDIR]" >&2
  exit 2
fi

BASE_URL=$1
GIT_URL=$2
REF=${3:-}
SUBDIR=${4:-.}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

PAYLOAD="{\"git_url\":\"$(json_escape "$GIT_URL")\",\"subdir\":\"$(json_escape "$SUBDIR")\",\"wait_seconds\":3"
if [ -n "$REF" ]; then
  PAYLOAD="$PAYLOAD,\"ref\":\"$(json_escape "$REF")\""
fi
PAYLOAD="$PAYLOAD}"

curl -sS -X POST "$BASE_URL/run" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD"

