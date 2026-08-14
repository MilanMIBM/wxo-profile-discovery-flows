# Import a flow's Python tools before the flow itself.
#
# A compiled flow spec references tool nodes BY NAME only -- `{"kind": "tool",
# "tool": "fetch_url_data"}`. The tool's source is not in the spec (script nodes
# carry their bodies inline, tool nodes do not), so `orchestrate tools import -k
# flow` ships a flow whose tool node points at nothing unless a tool of that name
# is already registered in the environment.
#
# Dependencies are a separate matter again: they never travel with the flow. pip
# runs server-side at deployment, per environment, from a requirements file
# attached to the TOOL import via `-r`. So a tool needing docling has to declare
# it, and the requirements file has to be passed when that tool is imported.
#
# Rather than keep a requirements.txt in sync with each tool by hand, the tool
# declares its own dependencies inline, in a PEP 723-style block anywhere in the
# tool's source:
#
#     # ///
#     # dependencies = [
#     #     "docling==2.55.1",
#     # ]
#     # ///
#
# `import_tools_to_wxo` parses those blocks out, writes a temporary
# requirements.txt per tool, and imports each tool with it. Nothing permanent is
# written to the repo -- the temp file lives only for the length of the import.

import re
import subprocess
import sys
import tempfile
from pathlib import Path

# The block is written as comments so it survives in a normal .py file and in a
# marimo cell. Matches `# ///` ... `# ///` and pulls the quoted entries out of
# whatever sits between, so both one-per-line and inline lists work.
_BLOCK = re.compile(
    r"^[ \t]*#[ \t]*///[ \t]*\n(.*?)^[ \t]*#[ \t]*///[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_DEPENDENCIES = re.compile(r"dependencies[ \t]*=[ \t]*\[(.*?)\]", re.DOTALL)
_ENTRY = re.compile(r"""["']([^"']+)["']""")


def parse_dependencies(source):
    """Pull dependency specs out of a tool's inline `# ///` block(s).

    Args:
        source: The tool file's text.

    Returns:
        list[str]: The specs, in declaration order, deduplicated. Empty when the
        file declares no block -- which is normal for a tool with no third-party
        dependencies, and means no `-r` is passed for it.
    """
    found = []
    for block in _BLOCK.findall(source or ""):
        # Strip the leading `#` from each commented line before reading the list.
        uncommented = "\n".join(
            re.sub(r"^[ \t]*#[ \t]?", "", line) for line in block.splitlines()
        )
        for group in _DEPENDENCIES.findall(uncommented):
            found.extend(_ENTRY.findall(group))

    seen = {}
    for spec in found:
        spec = spec.strip()
        if spec and spec not in seen:
            seen[spec] = True
    return list(seen)


def import_tools_to_wxo(tool_paths, dry_run=False, extra_args=None):
    """Import each tool, passing a temp requirements.txt built from its own block.

    Runs BEFORE the flow import: the flow's tool nodes resolve by name, so the
    tools have to exist in the environment first. Re-importing an existing tool
    overwrites it, so this is safe to run on every import-button click.

    Args:
        tool_paths: Paths to the tool source files. A marimo notebook works --
            `@app.function` puts the @tool at module level -- as does a plain
            module.
        dry_run: Parse and report without calling the CLI.
        extra_args: Appended to every `orchestrate tools import` call, e.g.
            ["-a", "my_app"] for a connection app-id.

    Returns:
        list[dict]: One entry per tool -- path, dependencies, and the
        CompletedProcess (None on dry_run).
    """
    results = []

    for tool_path in tool_paths:
        tool_path = Path(tool_path)
        if not tool_path.exists():
            raise FileNotFoundError(f"tool source not found: {tool_path}")

        dependencies = parse_dependencies(tool_path.read_text())
        command = [
            "orchestrate",
            "tools",
            "import",
            "-k",
            "python",
            "-f",
            str(tool_path),
        ]

        # The temp file has to outlive the subprocess call, so it is written into
        # a temp DIRECTORY that is cleaned up after, rather than a NamedTemporary
        # file whose lifetime is harder to reason about across platforms.
        with tempfile.TemporaryDirectory() as tmp:
            if dependencies:
                requirements = Path(tmp) / "requirements.txt"
                requirements.write_text("\n".join(dependencies) + "\n")
                command += ["-r", str(requirements)]

            if extra_args:
                command += list(extra_args)

            print(f"{tool_path.name}: dependencies {dependencies or '(none)'}")

            if dry_run:
                print("  would run:", " ".join(command))
                results.append(
                    {
                        "path": tool_path,
                        "dependencies": dependencies,
                        "proc": None,
                    }
                )
                continue

            proc = subprocess.run(command, capture_output=True, text=True)

        print(proc.stdout or "")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        if proc.returncode != 0:
            print(
                f"  !! {tool_path.name} import failed (exit {proc.returncode}); "
                f"the flow's tool node will not resolve",
                file=sys.stderr,
            )

        results.append(
            {"path": tool_path, "dependencies": dependencies, "proc": proc}
        )

    return results
