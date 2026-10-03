#!/usr/bin/env bash
#Builds the image, runs it under the Lambda runtime emulator and sends one event: [PORT=9100] scripts/local.sh ['{"action":"ping"}'].
#Anything but ping needs AWS credentials and FAILOVER_SECRET_ARN in the environment; they are passed through.
set -euo pipefail
EVENT=${1:-'{"action":"ping"}'}
PORT=${PORT:-9000}
NAME=of-failover-local
docker build -t "$NAME" . >&2
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d -p "$PORT:8080" --name "$NAME" \
  -e AWS_REGION -e AWS_DEFAULT_REGION -e AWS_PROFILE -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_SESSION_TOKEN \
  -e FAILOVER_SECRET_ARN -v "${HOME}/.aws:/root/.aws:ro" "$NAME" >/dev/null
trap 'docker rm -f "$NAME" >/dev/null' EXIT
curl -fsS --retry 10 --retry-all-errors --retry-delay 1 -d "$EVENT" \
  "localhost:$PORT/2015-03-31/functions/function/invocations" | python3 -m json.tool
