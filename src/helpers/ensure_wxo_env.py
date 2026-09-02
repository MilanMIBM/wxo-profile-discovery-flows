from dotenv import load_dotenv
import subprocess
import os


def ensure_wxo_env(env_file="config/.env", reactivate=False, verbose=True):
    """Make sure a watsonx Orchestrate environment exists and is active.

    Reads WXO_ENV_NAME / WXO_APIKEY / WXO_ENDPOINT from `env_file` -- the same
    values src/utils/wxo_env_setup.sh uses -- and runs `orchestrate env add`
    when the wanted environment isn't registered yet, then
    `orchestrate env activate` unless it is already the active one. This is the
    Python equivalent of running that script, so the CLI calls made from other
    cells (tools import, etc.) land in the right environment.

    Args:
        env_file: Path to the .env holding WXO_ENV_NAME, WXO_APIKEY and
            (for first-run registration) WXO_ENDPOINT.
        reactivate: Activate even when the environment is already active.
        verbose: Print what was found and done.

    Returns:
        dict with `env_name`, `active` (name the CLI reports as active, or
        None), `already_active`, `activated` (whether this call ran
        `env activate`), and `added` (whether this call ran `env add`).
    """
    # Load into os.environ so WXO_* are readable here and inherited by any subprocess. override=True keeps the file authoritative over stale values.
    load_dotenv(env_file, override=True)
    env_name = os.getenv("WXO_ENV_NAME")
    api_key = os.getenv("WXO_APIKEY")
    endpoint = os.getenv("WXO_ENDPOINT")
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
    shown_names = []
    for line in listed.stdout.splitlines():
        parts = line.split()
        # Skip the table's border/header rows; a data row starts with the env name.
        if not parts or set(line.strip()) <= set("-+=| "):
            continue
        name = parts[0].strip("|")
        if not name or name.lower() in {"name", "environment"}:
            continue
        shown_names.append(name)
        if "(active)" in line:
            active = name

    def matches(shown, wanted):
        if shown is None:
            return False
        stem = shown.rstrip("…")
        return wanted == shown or (shown.endswith("…") and wanted.startswith(stem))

    # First run against a fresh CLI config: register the environment before trying to activate it, mirroring src/utils/wxo_env_setup.sh.
    added = False
    if not any(matches(shown, env_name) for shown in shown_names):
        if not endpoint:
            raise RuntimeError(
                f"wxo environment {env_name!r} is not registered and {env_file} "
                f"defines no WXO_ENDPOINT to register it with"
            )
        if verbose:
            print(f"registering wxo environment {env_name!r} at {endpoint}")
        created = run(["env", "add", "-n", env_name, "-u", endpoint])
        if created.returncode != 0:
            raise RuntimeError(
                f"`orchestrate env add -n {env_name} -u {endpoint}` failed "
                f"({created.returncode}): "
                f"{(created.stderr or created.stdout).strip()}"
            )
        if verbose and created.stdout.strip():
            print(created.stdout.strip())
        added = True

    already_active = matches(active, env_name)
    if already_active and not reactivate:
        if verbose:
            print(f"wxo environment already active: {active}")
        return {
            "env_name": env_name,
            "active": active,
            "already_active": True,
            "activated": False,
            "added": added,
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
        "added": added,
    }
