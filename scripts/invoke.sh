#!/usr/bin/env bash
#Invokes the deployed function and prints its response: scripts/invoke.sh [function-name] ['{"action":"status"}']; region from AWS_REGION, default us-west-2.
set -euo pipefail
FUNCTION=${1:-innovate-inc-failover-regional}
EVENT=${2:-'{"action":"status"}'}
OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT
aws lambda invoke --region "${AWS_REGION:-us-west-2}" --function-name "$FUNCTION" \
  --cli-binary-format raw-in-base64-out --payload "$EVENT" "$OUT" >&2
python3 -m json.tool "$OUT"
