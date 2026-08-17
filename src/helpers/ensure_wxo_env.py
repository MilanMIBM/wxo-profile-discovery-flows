from dotenv import load_dotenv
import subprocess
import os


def ensure_wxo_env(env_file="config/.env", reactivate=False, verbose=True):
    """Make sure a watsonx Orchestrate environment is active, activating it if not.

    Reads WXO_ENV_NAME / WXO_APIKEY from `env_file` -- the same pair
    src/utils/wxo_env_activate.sh uses -- and runs `orchestrate env activate`
    only when the wanted environment isn't already the active one. This is the
    Python equivalent of sourcing that script, so the CLI calls made from other
    cells (tools import, etc.) land in the right environment.

    Args:
        env_file: Path to the .env holding WXO_ENV_NAME and WXO_APIKEY.
        reactivate: Activate even when the environment is already active.
        verbose: Print what was found and done.

    Returns:
        dict with `env_name`, `active` (name the CLI reports as active, or
        None), `already_active`, and `activated` (whether this call ran
        `env activate`).
    """
    # Load into os.environ so WXO_* are readable here and inherited by any subprocess. override=True keeps the file authoritative over stale values.
    load_dotenv(env_file, override=True)
    env_name = os.getenv("WXO_ENV_NAME")
    api_key = os.getenv("WXO_APIKEY")
    if not env_name or not api_key:
        raise RuntimeError(
            f"{env_file} must define WXO_ENV_NAME and WXO_APIKEY "
            f"(got env_name={env_name!r}, api_key={'set' if api_key else 'unset'})"
        )

    def run(args):
        return subprocess.run(["orchestrate", *args], capture_output=True, text=True)

    # `env list` renders a table, one env per line, with "(active)" appended to the current one. Long names are truncated with a trailing "…", so compare on the truncated stem rather than requiring an exact match.
    listed = run(["env", "list"])
    if listed.returncode != 0:
        raise RuntimeError(
            f"`orchestrate env list` failed ({listed.returncode}): "
            f"{(listed.stderr or listed.stdout).strip()}"
        )

    active = None
    for line in listed.stdout.splitlines():
        if "(active)" in line:
            parts = line.split()
            if parts:
                active = parts[0]
            break

    def matches(shown, wanted):
        if shown is None:
            return False
        stem = shown.rstrip("…")
        return wanted == shown or (shown.endswith("…") and wanted.startswith(stem))

    already_active = matches(active, env_name)
    if already_active and not reactivate:
        if verbose:
            print(f"wxo environment already active: {active}")
        return {
            "env_name": env_name,
            "active": active,
            "already_active": True,
            "activated": False,
        }

    if verbose:
        print(
            f"activating wxo environment {env_name!r}"
            + (f" (was {active!r})" if active else " (none active)")
        )
    activated = run(["env", "activate", env_name, "--api-key", api_key])
    if activated.returncode != 0:
        raise RuntimeError(
            f"`orchestrate env activate {env_name}` failed "
            f"({activated.returncode}): "
            f"{(activated.stderr or activated.stdout).strip()}"
        )
    if verbose and activated.stdout.strip():
        print(activated.stdout.strip())

    return {
        "env_name": env_name,
        "active": env_name,
        "already_active": already_active,
        "activated": True,
    }
