#!/usr/bin/env bash
#
# wxo_import_python_tool.sh - Upload a Python tool (+ its requirements.txt) to a watsonx
# Orchestrate instance using the ADK CLI (`orchestrate`).
#
# Credentials are resolved, in order of precedence:
#   1. CLI flags (--api-key / --endpoint)
#   2. environment variables WXO_APIKEY / WXO_ENDPOINT / WXO_ENV_NAME
#   3. a .env file (default: <project_root>/config/.env, where <project_root> is the
#      nearest ancestor directory containing pyproject.toml; override with --env-file)
#
# Usage:
#   ./wxo_import_python_tool.sh -f <tool.py> -r <requirements.txt> [options]
#
# Options:
#   -f, --file <path>          Python tool file to import.               (required)
#   -r, --requirements <path>  requirements.txt for the tool.           (required)
#   -p, --package-root <path>  Package root for multi-file tools.       (optional)
#   -a, --app-id <id>          Connection app-id to bind (repeatable).  (optional)
#       --api-key <key>        WXO API key (overrides env/.env).
#   -u, --endpoint <url>       WXO instance URL (overrides env/.env).
#   -n, --env-name <name>      Name for the ADK environment entry. (default: wxo-import)
#   -e, --env-file <path>      .env file to source. (default: <project_root>/config/.env)
#       --orchestrate <cmd>    Path/command for the ADK CLI. (default: orchestrate,
#                              falling back to `uv run orchestrate` if not on PATH)
#   -h, --help                 Show this help and exit. 
#
# Example:
#   ./wxo_import_python_tool.sh \
#       -f render_jinja2_template.py \
#       -r render_jinja2_template_requirements.txt
#
# This script uses bash-only features ([[ ]], arrays, process substitution).
# If invoked under a non-bash shell (e.g. `sh script.sh` or `zsh script.sh`),
# re-exec ourselves under bash so those constructs parse correctly.
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

# Locate this script's own directory (bash: BASH_SOURCE; fall back to $0).
_self="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "$_self")" && pwd)"

# Walk up from this script's directory to the nearest ancestor holding pyproject.toml;
# that's the project root. Falls back to SCRIPT_DIR if no marker is found.
find_project_root() {
  local d="$SCRIPT_DIR"
  while [[ "$d" != "/" ]]; do
    [[ -f "$d/pyproject.toml" ]] && { printf '%s\n' "$d"; return 0; }
    d="$(dirname "$d")"
  done
  printf '%s\n' "$SCRIPT_DIR"
}
PROJECT_ROOT="$(find_project_root)"

# -------- defaults --------
FILE=""
REQUIREMENTS=""
PACKAGE_ROOT=""
API_KEY="${WXO_APIKEY:-}"
ENDPOINT="${WXO_ENDPOINT:-}"
ENV_NAME="${WXO_ENV_NAME:-}"
ENV_FILE="${PROJECT_ROOT}/config/.env"
ORCHESTRATE=""
APP_IDS=()

die() { echo "Error: $*" >&2; exit 1; }

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//; s/^#$//'; }

# -------- parse args --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)          FILE="$2"; shift 2 ;;
    -r|--requirements)  REQUIREMENTS="$2"; shift 2 ;;
    -p|--package-root)  PACKAGE_ROOT="$2"; shift 2 ;;
    -a|--app-id)        APP_IDS+=("$2"); shift 2 ;;
    --api-key)          API_KEY="$2"; shift 2 ;;
    -u|--endpoint)      ENDPOINT="$2"; shift 2 ;;
    -n|--env-name)      ENV_NAME="$2"; shift 2 ;;
    -e|--env-file)      ENV_FILE="$2"; shift 2 ;;
    --orchestrate)      ORCHESTRATE="$2"; shift 2 ;;
    -h|--help)          usage; exit 0 ;;
    *)                  die "Unknown argument: $1 (use --help)" ;;
  esac
done

# -------- load .env (only fills values not already set via flags/env) --------
# Pull a single KEY=value out of the .env file, stripping surrounding quotes.
# Uses a pipe (not process substitution) so the file stays parseable everywhere.
read_env_var() {
  local key="$1" line val
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$ENV_FILE" 2>/dev/null | tail -n 1 || true)"
  [[ -z "$line" ]] && return 0
  val="${line#*=}"
  # trim leading/trailing whitespace, then a single layer of matching quotes
  val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  printf '%s\n' "$val"
}

if [[ -f "$ENV_FILE" ]]; then
  [[ -z "$API_KEY"  ]] && API_KEY="$(read_env_var WXO_APIKEY)"
  [[ -z "$ENDPOINT" ]] && ENDPOINT="$(read_env_var WXO_ENDPOINT)"
  [[ -z "$ENV_NAME" ]] && ENV_NAME="$(read_env_var WXO_ENV_NAME)"
fi

# Never let the env name be empty: `env add --name ""` hangs/errors in the ADK CLI.
ENV_NAME="${ENV_NAME:-wxo-import}"

# -------- resolve the ADK CLI --------
if [[ -z "$ORCHESTRATE" ]]; then
  if command -v orchestrate >/dev/null 2>&1; then
    ORCHESTRATE="orchestrate"
  elif command -v uv >/dev/null 2>&1; then
    ORCHESTRATE="uv run orchestrate"
  else
    die "Could not find the 'orchestrate' CLI. Install the ADK or pass --orchestrate."
  fi
fi

# Resolve a path: use it as-is if it exists (relative to CWD or absolute),
# otherwise fall back to the same name relative to this script's directory.
# This lets `-f render_jinja2_template.py` work regardless of where you cd'd.
resolve_path() {
  local p="$1"
  if [[ -e "$p" ]]; then printf '%s\n' "$p"
  elif [[ -e "$SCRIPT_DIR/$p" ]]; then printf '%s\n' "$SCRIPT_DIR/$p"
  else printf '%s\n' "$p"  # return unchanged; validation below reports it
  fi
}

# -------- validate --------
[[ -n "$FILE"         ]] || die "--file is required."
FILE="$(resolve_path "$FILE")"
[[ -f "$FILE"         ]] || die "Tool file not found: $FILE"
[[ -n "$REQUIREMENTS" ]] || die "--requirements is required."
REQUIREMENTS="$(resolve_path "$REQUIREMENTS")"
[[ -f "$REQUIREMENTS" ]] || die "Requirements file not found: $REQUIREMENTS"
[[ -n "$ENDPOINT"     ]] || die "No endpoint. Set WXO_ENDPOINT in $ENV_FILE or pass --endpoint."
[[ -n "$API_KEY"      ]] || die "No API key. Set WXO_APIKEY in $ENV_FILE or pass --api-key."
if [[ -n "$PACKAGE_ROOT" ]]; then
  PACKAGE_ROOT="$(resolve_path "$PACKAGE_ROOT")"
  [[ -d "$PACKAGE_ROOT" ]] || die "Package root is not a directory: $PACKAGE_ROOT"
fi

echo ">> Endpoint : $ENDPOINT"
echo ">> Env name : $ENV_NAME"
echo ">> Tool     : $FILE"
echo ">> Reqs     : $REQUIREMENTS"
[[ -n "$PACKAGE_ROOT"      ]] && echo ">> Package  : $PACKAGE_ROOT"
[[ ${#APP_IDS[@]} -gt 0    ]] && echo ">> App IDs  : ${APP_IDS[*]}"

# -------- register + activate the environment --------
# Does `env list` already contain an entry with exactly this name?
# `env list` renders as columns and truncates long names with a unicode ellipsis,
# so compare on the first field and ignore any row whose name was elided --
# a truncated row can't be confirmed as an exact match either way.
env_exists() {
  $ORCHESTRATE env list 2>/dev/null \
    | awk -v want="$ENV_NAME" '
        { name=$1 }
        name ~ /…$/ { next }
        name == want { found=1; exit }
        END { exit !found }
      '
}

if env_exists; then
  echo ">> Environment '$ENV_NAME' already registered; skipping add."
else
  echo ">> Registering environment '$ENV_NAME'..."
  $ORCHESTRATE env add --name "$ENV_NAME" --url "$ENDPOINT" >/dev/null
fi

echo ">> Activating environment (authenticating)..."
# NOTE: the ADK CLI accepts the key only via --api-key (no env-var fallback);
# on a shared host this is briefly visible in `ps`. Acceptable for local dev.
$ORCHESTRATE env activate "$ENV_NAME" --api-key "$API_KEY"

# -------- build the import command --------
import_cmd=($ORCHESTRATE tools import --kind python --file "$FILE" --requirements-file "$REQUIREMENTS")
[[ -n "$PACKAGE_ROOT" ]] && import_cmd+=(--package-root "$PACKAGE_ROOT")
for app in "${APP_IDS[@]:-}"; do
  [[ -n "$app" ]] && import_cmd+=(--app-id "$app")
done

echo ">> Importing tool..."
"${import_cmd[@]}"

echo ">> Done. Verify with:  $ORCHESTRATE tools list"
