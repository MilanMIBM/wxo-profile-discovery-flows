#!/usr/bin/env bash
# Register the watsonx Orchestrate environment from config/.env
set -euo pipefail

ENV_FILE="${WXO_ENV_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/config/.env}"
[ -f "$ENV_FILE" ] || { echo "missing env file: $ENV_FILE" >&2; exit 1; }

set -a; . "$ENV_FILE"; set +a

orchestrate env add -n "$WXO_ENV_NAME" -u "$WXO_ENDPOINT"
