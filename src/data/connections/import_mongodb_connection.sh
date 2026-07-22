#!/usr/bin/env bash
#
# Imports the mongodb-conn-string connection and sets its credentials from .env.
#
# Reads from .env:
#   MONGODB_ENDPOINT      -- full mongodb:// URL (interpolates MONGODB_USERNAME /
#                            MONGODB_PASSWORD / MONGODB_HOSTS, hence the sourcing below)
#   IBMCLOUD_DB_CERT_PATH -- optional; path to the IBM Cloud CA cert, sent base64-encoded
#
# Usage:
#   ./src/helpers/connections/import_mongodb_connection.sh [-e .env] [-E draft|live] [-s]
#     -e  path to the env file           (default: .env in the repo root)
#     -E  target wxo environment         (default: draft)
#     -s  skip the spec import; only set credentials
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

ENV_FILE="${REPO_ROOT}/config/.env"
WXO_ENV="draft"
SPEC_FILE="${SCRIPT_DIR}/mongodb-conn-string.yaml"
SKIP_IMPORT=0

while getopts ":e:E:sh" opt; do
    case "${opt}" in
        e) ENV_FILE="${OPTARG}" ;;
        E) WXO_ENV="${OPTARG}" ;;
        s) SKIP_IMPORT=1 ;;
        h) sed -n '2,14p' "${BASH_SOURCE[0]}"; exit 0 ;;
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

# Source rather than parse: MONGODB_ENDPOINT is written in terms of $MONGODB_USERNAME,
# $MONGODB_PASSWORD and $MONGODB_HOSTS, so only the shell resolves it to a real URL.
set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

MONGODB_CONN_STRING="${MONGODB_ENDPOINT:-}"
[[ -n "${MONGODB_CONN_STRING}" ]] || {
    echo "error: MONGODB_ENDPOINT is unset or empty in ${ENV_FILE}" >&2
    exit 1
}

# The tool sandbox has no cert file on disk, so the CA travels base64-encoded and the
# tool writes it back out to a temp file at runtime.
CERT_PATH="${IBMCLOUD_DB_CERT_PATH:-}"
CA_CERT_BASE64=""
if [[ -n "${CERT_PATH}" && -f "${CERT_PATH}" ]]; then
    CA_CERT_BASE64="$(base64 < "${CERT_PATH}" | tr -d '\n')"
elif [[ -n "${CERT_PATH}" ]]; then
    echo "warning: IBMCLOUD_DB_CERT_PATH set but not found: ${CERT_PATH}" >&2
    echo "         continuing without MONGODB_CA_CERT_BASE64." >&2
else
    echo "warning: IBMCLOUD_DB_CERT_PATH unset -- continuing without a CA cert." >&2
fi

if [[ "${SKIP_IMPORT}" -eq 0 ]]; then
    echo "==> importing ${SPEC_FILE}"
    orchestrate connections import -f "${SPEC_FILE}"
fi

echo "==> setting credentials for mongodb-conn-string (--env ${WXO_ENV})"
creds=(-e "MONGODB_CONN_STRING=${MONGODB_CONN_STRING}")
if [[ -n "${CA_CERT_BASE64}" ]]; then
    creds+=(-e "MONGODB_CA_CERT_BASE64=${CA_CERT_BASE64}")
fi

orchestrate connections set-credentials -a mongodb-conn-string --env "${WXO_ENV}" "${creds[@]}"

echo "==> done. Verify with: orchestrate connections list"
