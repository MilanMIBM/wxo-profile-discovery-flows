#!/usr/bin/env bash
#
# Imports the postgres-conn-string connection and sets its credentials from .env.
#
# Reads from .env (at least one of the two must be set):
#   POSTGRESQL_ENDPOINT         -- full postgres:// URL for the public endpoint
#                                  (interpolates POSTGRESQL_USERNAME / POSTGRESQL_PASSWORD /
#                                  POSTGRESQL_HOST, hence the sourcing below)
#   POSTGRESQL_ENDPOINT_PRIVATE -- optional; same, for the private/VPE endpoint
#
# Usage:
#   ./src/data/connections/import_postgres_connection.sh [-e .env] [-E draft|live] [-s]
#     -e  path to the env file           (default: config/.env in the repo root)
#     -E  target wxo environment         (default: draft)
#     -s  skip the spec import; only set credentials
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

ENV_FILE="${REPO_ROOT}/config/.env"
WXO_ENV="draft"
SPEC_FILE="${SCRIPT_DIR}/postgres-conn-string.yaml"
SKIP_IMPORT=0

while getopts ":e:E:sh" opt; do
    case "${opt}" in
        e) ENV_FILE="${OPTARG}" ;;
        E) WXO_ENV="${OPTARG}" ;;
        s) SKIP_IMPORT=1 ;;
        h) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "unknown option: -${OPTARG}" >&2; exit 2 ;;
    esac
done

if [[ "${WXO_ENV}" != "draft" && "${WXO_ENV}" != "live" ]]; then
    echo "error: -E must be 'draft' or 'live' (got '${WXO_ENV}')" >&2
    exit 2
fi

[[ -f "${ENV_FILE}" ]] || { echo "error: env file not found: ${ENV_FILE}" >&2; exit 1; }
command -v orchestrate >/dev/null 2>&1 || {
    echo "error: 'orchestrate' not on PATH -- activate the venv holding the ADK." >&2
    exit 1
}

# Source rather than parse: POSTGRESQL_ENDPOINT is written in terms of
# $POSTGRESQL_USERNAME, $POSTGRESQL_PASSWORD and $POSTGRESQL_HOST, so only the shell
# resolves it to a real URL.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

PG_PUBLIC="${POSTGRESQL_ENDPOINT:-}"
PG_PRIVATE="${POSTGRESQL_ENDPOINT_PRIVATE:-}"

if [[ -z "${PG_PUBLIC}" && -z "${PG_PRIVATE}" ]]; then
    echo "error: set POSTGRESQL_ENDPOINT and/or POSTGRESQL_ENDPOINT_PRIVATE in ${ENV_FILE}" >&2
    exit 1
fi

[[ -n "${PG_PRIVATE}" ]] || echo "warning: POSTGRESQL_ENDPOINT_PRIVATE unset -- only the public string will be set." >&2
[[ -n "${PG_PUBLIC}" ]] || echo "warning: POSTGRESQL_ENDPOINT unset -- only the private string will be set." >&2

if [[ "${SKIP_IMPORT}" -eq 0 ]]; then
    echo "==> importing ${SPEC_FILE}"
    orchestrate connections import -f "${SPEC_FILE}"
fi

echo "==> setting credentials for postgres-conn-string (--env ${WXO_ENV})"
creds=()
if [[ -n "${PG_PUBLIC}" ]]; then
    creds+=(-e "POSTGRES_CONN_STRING_PUBLIC=${PG_PUBLIC}")
fi
if [[ -n "${PG_PRIVATE}" ]]; then
    creds+=(-e "POSTGRES_CONN_STRING_PRIVATE=${PG_PRIVATE}")
fi

orchestrate connections set-credentials -a postgres-conn-string --env "${WXO_ENV}" "${creds[@]}"

echo "==> done. Verify with: orchestrate connections list"
