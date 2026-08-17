# Import a flow's Python tools before the flow itself. A compiled flow spec references tool nodes by name only, and the tool's source is not in the spec, so `orchestrate tools import -k flow` ships a flow whose tool node points at nothing unless a tool of that name is already registered in the environment.

# Dependencies never travel with the flow either: pip runs server-side at deployment, per environment, from a requirements file attached to the TOOL import via `-r`. Rather than keep a requirements.txt in sync by hand, each tool declares its own dependencies inline in a PEP 723-style `# ///` block, and `import_tools_to_wxo` parses those out into one `<tool>_requirements.txt` per tool in src/flow_specs/, then imports with `-r` pointing at it. That file is rewritten only when the parsed block differs from what is on disk, because the server-side venv is cached by the requirements hash and a needless rebuild is what makes a tool answer 424 while pip runs.

import ast
import re
import subprocess
import sys
from pathlib import Path

# The block is written as comments so it survives in a normal .py file and in a marimo cell. Matches `# ///` ... `# ///` and pulls the quoted entries out of whatever sits between, so both one-per-line and inline lists work.
_BLOCK = re.compile(
    r"^[ \t]*#[ \t]*///[ \t]*\n(.*?)^[ \t]*#[ \t]*///[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_DEPENDENCIES = re.compile(r"dependencies[ \t]*=[ \t]*\[(.*?)\]", re.DOTALL)
_ENTRY = re.compile(r"""["']([^"']+)["']""")


def _is_tool(node):
    """True when a function node carries an @tool decorator.

    Matches `@tool`, `@tool(...)` and dotted forms like `@tools.tool(...)`, so a
    renamed import still registers.
    """
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "attr", None) or getattr(target, "id", None)
        if name == "tool":
            return True
    return False


def _specs_in(text):
    """Extract dependency specs from every `# ///` block in a chunk of source."""
    found = []
    for block in _BLOCK.findall(text or ""):
        # Strip the leading `#` from each commented line before reading the list.
        uncommented = "\n".join(
            re.sub(r"^[ \t]*#[ \t]?", "", line) for line in block.splitlines()
        )
        for group in _DEPENDENCIES.findall(uncommented):
            found.extend(_ENTRY.findall(group))
    return found


def parse_dependencies(source, tool_name=None):
    """Pull dependency specs out of the `# ///` block inside @tool functions.

    Scoped to the tool function bodies, not the whole file: a notebook holds logic
    blocks, prompt nodes and prose alongside the tool, and a `# ///` block
    belonging to one of those must not end up in another tool's requirements. Falls
    back to scanning the whole file when the source will not parse, so a syntax
    error downgrades the scope rather than silently dropping the dependencies.

    Args:
        source: The tool file's text.
        tool_name: Restrict to this function (or @tool(name=...)). None reads every
            @tool in the file, which is what a whole-file import needs since one
            import ships them all.

    Returns:
        list[str]: The specs, in declaration order, deduplicated. Empty when no
        @tool declares a block, which is normal for a tool with no third-party
        dependencies and means no `-r` is passed for it.
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return _dedupe(_specs_in(source))

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_tool(node):
            continue
        if tool_name and not _matches_name(node, tool_name):
            continue

        # The block sits inside the function body, so slice the function's own source rather than the file's. `# ///` is a comment and therefore absent from the AST, which is why this is a text scan of that slice.
        segment = ast.get_source_segment(source, node)
        found.extend(_specs_in(segment))

    return _dedupe(found)


def _matches_name(node, tool_name):
    """Match a @tool function by its def name or its @tool(name=...) override."""
    if node.name == tool_name:
        return True
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                if keyword.value.value == tool_name:
                    return True
    return False


def _declared_name(node):
    """The tool's registered name: @tool(name=...) if given, else the def name."""
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                return keyword.value.value
    return node.name


def tools_in_source(source):
    """Every @tool in a file, as {tool_name: [dependency specs]}.

    Keyed by the name the tool registers under -- `@tool(name=...)` when given,
    otherwise the function name -- because that is what the flow's tool node
    references, and so what the requirements file should carry. A file may define
    several tools, each with its own block; this keeps them apart rather than
    merging them into one set.
    """
    try:
        tree = ast.parse(source or "")
    except SyntaxError:
        return {}

    tools = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_tool(node):
            continue
        segment = ast.get_source_segment(source, node)
        tools[_declared_name(node)] = _dedupe(_specs_in(segment))
    return tools


def _dedupe(specs):
    seen = {}
    for spec in specs:
        spec = (spec or "").strip()
        if spec and spec not in seen:
            seen[spec] = True
    return list(seen)


def tool_names_in_flow(aflow):
    """Every tool name the built flow references, including inside subflows.

    Reads the Flow object rather than the compiled spec: same information, but
    available before compile() and without re-parsing JSON. Foreach/parallel scopes
    are Flow subclasses holding their own `nodes`, so this recurses.

    Returns:
        list[str]: Tool names, in discovery order, deduplicated.
    """
    names = []

    def walk(scope):
        for node in (getattr(scope, "nodes", None) or {}).values():
            spec = getattr(node, "spec", None)
            tool = getattr(spec, "tool", None)
            if tool:
                # `tool` is the name, or a ToolSpec carrying one.
                names.append(getattr(tool, "name", tool))
            # Subflow scopes (foreach, parallel, ...) nest their own nodes.
            if getattr(node, "nodes", None):
                walk(node)

    walk(aflow)
    return _dedupe(names)


def resolve_tool_sources(aflow, namespace):
    """Map the flow's tool nodes back to the files that define them.

    The flow records a tool by name only, so the path comes from the object the
    notebook imported under that name, via inspect. Pass `globals()` from the
    calling cell as `namespace`.

    Args:
        aflow: The built Flow.
        namespace: Mapping to resolve names in, normally `globals()`.

    Returns:
        tuple[list[Path], list[str]]: (resolved source files, unresolved names).
        Unresolved names are the ones to warn about, since the flow will import with
        a tool node pointing at a tool that may not exist in the environment.
    """
    import inspect

    paths = []
    unresolved = []

    for name in tool_names_in_flow(aflow):
        obj = (namespace or {}).get(name)
        # @tool wraps the function, so unwrap to reach the original if needed.
        target = getattr(obj, "fn", None) or getattr(obj, "__wrapped__", None) or obj
        try:
            path = Path(inspect.getfile(target))
        except TypeError, OSError:
            unresolved.append(name)
            continue
        if path not in paths:
            paths.append(path)

    return paths, unresolved


# Generated requirements files live alongside the compiled flow specs, so both artefacts of an import sit together and are reviewable in version control.
REQUIREMENTS_DIR = Path("src/flow_specs")

# The ADK has to be in the tool's server-side venv: the generated module imports `ibm_watsonx_orchestrate.agent_builder.tools`, so a venv without it fails at import, before the tool body ever runs.
WXO_ADK_PACKAGE = "ibm-watsonx-orchestrate"
DEFAULT_WXO_ADK_VERSION = "2.14.0"

# A requirement line's package name, up to the first version specifier, extra or marker, so a pin in any spelling is recognised.
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9._-]+)")


def _normalise_package(name):
    """PEP 503 normalised form, so `_` and `-` spellings compare equal."""
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


def _declares_package(specs, package):
    """True when `specs` already carries a requirement for `package`.

    Compares normalised names and ignores the version, since the point is to leave
    an existing pin alone whatever it pins to. Matches on the whole name rather
    than a prefix: `ibm-watsonx-orchestrate-sdk` is a different package.
    """
    target = _normalise_package(package)
    for spec in specs:
        match = _REQUIREMENT_NAME.match((spec or "").strip())
        if match and _normalise_package(match.group(1)) == target:
            return True
    return False


def ensure_wxo_adk(specs, append_wxo_adk=True, wxo_adk_version=DEFAULT_WXO_ADK_VERSION):
    """Prepend the ADK pin to `specs` unless the tool already declares one.

    Prepended rather than appended so the runtime dependency reads first in the
    file, above the tool's own. Skipped when the tool already declares
    `ibm-watsonx-orchestrate` at any version, since an explicit pin in the `# ///`
    block is the author's choice and is never overwritten.

    Note the CLI injects a pin of its own from the INSTALLED ADK version, stripping
    any `ibm-watsonx-orchestrate` line out of the file first unless the
    environment's registry type is `skip` (`get_requirement_lines`, ADK 2.14.0). So
    on a `pypi` registry this pin does not reach the uploaded bundle; it matters
    under `skip`, and either way it keeps the intended version explicit and
    reviewable in the generated file.

    Args:
        specs: Dependency specs parsed from the tool's block.
        append_wxo_adk: False disables this entirely and returns `specs` as given.
        wxo_adk_version: Version to pin. None or "" leaves it unpinned for pip to
            resolve.

    Returns:
        list[str]: The specs, with the ADK pin first when one was added.
    """
    specs = list(specs or [])
    if not append_wxo_adk:
        return specs
    if _declares_package(specs, WXO_ADK_PACKAGE):
        return specs

    version = (wxo_adk_version or "").strip()
    pin = f"{WXO_ADK_PACKAGE}=={version}" if version else WXO_ADK_PACKAGE
    return [pin] + specs


def requirements_name(source_stem, tool_name):
    """`<tool_name>_requirements.txt`, matching the generated `<tool_name>.py`.

    Keyed on the tool alone, deliberately. An earlier version prefixed the
    authoring file's stem to keep two flows that both define, say, a
    `fetch_url_data` from overwriting each other's dependencies -- but that is
    not a conflict the file naming can resolve. The tool file is now
    `<tool_name>.py` (the binding is derived from it, so it cannot be renamed
    freely) and would collide first; and the platform registers tools by name, so
    two different `fetch_url_data` implementations are one tool in the
    environment regardless of what the local files are called. The collision is
    real, but it belongs upstream: give the tools distinct names.

    `source_stem` is accepted and ignored so callers need not change.
    """
    return f"{tool_name}_requirements.txt"


def write_requirements(
    dependencies, tool_name, directory=REQUIREMENTS_DIR, source_stem=None
):
    """Write the tool's requirements file, but only when the content changed.

    The file is a build artefact of the tool's inline `# ///` block, kept on disk
    rather than in a temp dir so the dependency set is reviewable and diffable
    next to the flow spec it belongs to.

    Rewriting it unconditionally would be worse than pointless: the server-side
    venv is cached by the hash of the requirements file, so an identical-content
    rewrite still looks like a change to anything tracking mtime, and a genuinely
    new hash forces a full rebuild -- which is what leaves a tool answering 424
    "configuring in the background" while pip reinstalls.

    Args:
        dependencies: Specs parsed from the tool's block.
        tool_name: The name the tool registers under.
        directory: Where to write. Created if absent.
        source_stem: Filename stem of the defining source, which prefixes the
            name so two files defining a same-named tool cannot collide.

    Returns:
        tuple[Path | None, bool]: (path, changed). Path is None when there are no
        dependencies -- nothing is written and no `-r` should be passed. `changed`
        is False when an identical file was already there.
    """
    if not dependencies:
        return None, False

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / requirements_name(source_stem, tool_name)

    content = "\n".join(dependencies) + "\n"
    if path.exists() and path.read_text() == content:
        return path, False

    path.write_text(content)
    return path, True


def extract_tool_source(source, tool_name=None, instrument=False):
    """Lift the @tool definitions out of their file as a standalone module.

    The tool is authored inside a marimo notebook, where it is wrapped in
    `@app.function` and surrounded by cells, SQL, UI widgets and other nodes.
    Importing that file directly ships all of it: the ADK would receive the
    notebook's own imports (marimo, pandas, sqlalchemy, pymongo) alongside the
    one function it wants.

    This rebuilds a plain module holding only what the tool needs -- module-level
    imports, any BaseModel schema classes, and the @tool functions themselves,
    with marimo's `@app.*` decorators stripped.

    Args:
        source: The authoring file's text.
        tool_name: Emit only this tool. None emits every @tool in the file.
        instrument: Wrap each tool body in SpanLogger entry/exit/failure logging.
            Off by default -- it changes the shipped code, so it is a debugging
            aid. Worth turning on when a tool fails with no message: logs flush
            only on a completed or HANDLED exception, so an uninstrumented crash
            leaves nothing but an exit code.

    Returns:
        str: Module source, or "" when the file holds no @tool.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    def with_decorators(node):
        """Source for a def/class INCLUDING its decorators, minus marimo's.

        `ast.get_source_segment` starts at `node.lineno`, which points at the
        `def`/`class` line -- decorators sit above it and are excluded. They have
        to be sliced separately and prepended, or the emitted tool loses its
        @tool decorator and stops being a tool at all.
        """
        lines = source.splitlines()
        kept = []
        for decorator in node.decorator_list:
            if _is_app_decorator(decorator):
                continue
            start = decorator.lineno - 1
            end = decorator.end_lineno
            kept.append("@" + "\n".join(lines[start:end]).lstrip("@ \t"))
        body = ast.get_source_segment(source, node)
        return "\n".join(kept + [body]) if body else None

    imports, models, tools = [], [], []

    for node in ast.walk(tree):
        # marimo puts the shared imports in a `with app.setup:` block; a plain module has them at top level. Take both, then filter below.
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
        elif isinstance(node, ast.ClassDef):
            # Schema classes the tool's signature refers to.
            segment = with_decorators(node)
            if segment:
                models.append((node.name, segment))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not _is_tool(node):
                continue
            if tool_name and not _matches_name(node, tool_name):
                continue
            tools.append(with_decorators(node))

    if not tools:
        return ""

    # Only keep the schema classes the emitted tools actually mention, so an unrelated class from elsewhere in the notebook does not ride along.
    body = "\n".join(tools)
    kept = [seg for name, seg in models if name in body]

    # Same for imports, but pruned per NAME rather than per statement: a notebook writes `from typing import List, Union` for its own use, and keeping the whole line because `List` is referenced would drag `Union` along unused. Rebuilding each statement from only its used aliases avoids that, and drops the statement entirely when nothing it binds is referenced -- which is what keeps marimo, pandas, sqlalchemy and the rest out of the emitted file.
    referenced = body + "\n" + "\n".join(kept)

    # A name a tool imports INSIDE its own body needs no module-level import, and hoisting one is actively harmful for a heavy dependency: a standalone tool spawns a process per invocation, so a module-scope `import docling` pays the torch/transformers load on every cold start, where a function-local one pays it only when the function actually runs. Drop such names unless something outside the function bodies -- a schema class, a decorator argument -- also needs them.
    local_only = _locally_imported_names(tools)
    outside = (
        "\n".join(kept) + "\n" + "\n".join(_strip_function_bodies(t) for t in tools)
    )

    rendered = []
    for node in imports:
        line = _render_import(
            node,
            referenced,
            skip={n for n in local_only if not _name_used(n, outside)},
        )
        if line and line not in rendered:
            rendered.append(line)
    imports = rendered

    if instrument:
        imports.append("from ibm_watsonx_orchestrate.run.logging import SpanLogger")
        tools = [_instrument_tool(t) for t in tools]

    parts = [
        "# Generated from the authoring notebook by src/helpers/tool_import.py.",
        "# Edit the tool in its notebook, not here -- this file is overwritten on",
        "# every import whose parsed content differs from what is already on disk.",
        "",
        "\n".join(imports),
        "",
        "\n\n\n".join(kept),
        "",
        "\n\n\n".join(tools),
    ]
    return "\n".join(p for p in parts if p is not None).rstrip() + "\n"


# Injected as the first statements of the function body when instrument=True. Logs are buffered in memory and only flushed when the invocation completes -- successfully or with a HANDLED exception -- so a process that dies mid-run leaves nothing behind but an exit code. Wrapping the body in try/except turns an unhandled crash into a handled one, which is what gets the trail written.
_INSTRUMENT_HEAD = """    _log = SpanLogger(__name__)
    _log.info("ENTER {name} args=%s", {args})
"""

_INSTRUMENT_TAIL = """    except BaseException as _exc:
        _log.error("FAILED {name}: %s: %s", type(_exc).__name__, _exc)
        raise
"""


def _instrument_tool(text):
    """Wrap a tool body in SpanLogger entry/exit/failure logging.

    Rewrites the source rather than the AST so the emitted file stays readable.
    The body is indented one level under a `try:`, with the original signature,
    decorators and docstring left where they are.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    fn = next(
        (
            n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ),
        None,
    )
    if fn is None:
        return text

    lines = text.splitlines()
    body = fn.body
    # Keep a leading docstring outside the try, so help() still finds it.
    start = body[0]
    if (
        isinstance(start, ast.Expr)
        and isinstance(start.value, ast.Constant)
        and isinstance(start.value.value, str)
    ):
        first = body[1].lineno if len(body) > 1 else start.end_lineno + 1
    else:
        first = start.lineno

    head = lines[: first - 1]
    rest = lines[first - 1 :]

    args = (
        "{"
        + ", ".join(f'"{a.arg}": {a.arg}' for a in fn.args.args if a.arg != "self")
        + "}"
    )

    return "\n".join(
        head
        + [
            _INSTRUMENT_HEAD.format(name=fn.name, args=args).rstrip(),
            "    try:",
        ]
        + ["    " + line if line.strip() else line for line in rest]
        + [_INSTRUMENT_TAIL.format(name=fn.name).rstrip()]
    )


def _is_app_decorator(node):
    """True for marimo's `@app.function` / `@app.cell(...)` / `@app.class_definition`.

    Deliberately narrow: it matches the `app.` prefix only, so `@tool(...)` and
    any other decorator on the same function survive the strip.
    """
    target = node.func if isinstance(node, ast.Call) else node
    return (
        isinstance(target, ast.Attribute) and getattr(target.value, "id", None) == "app"
    )


def _locally_imported_names(tool_sources):
    """Names imported inside EVERY given function body.

    Only names satisfied by all of them are safe to drop from module scope --
    if one tool imports `docling` locally and another relies on the module-level
    import, hoisting still has to happen.
    """
    per_tool = []
    for text in tool_sources:
        names = set()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        names.add(alias.asname or alias.name.split(".")[0])
        per_tool.append(names)

    if not per_tool:
        return set()
    return set.intersection(*per_tool)


def _strip_function_bodies(text):
    """The source with function bodies removed, leaving signatures/decorators.

    Used to test whether a name is needed OUTSIDE the bodies -- an annotation or
    a decorator argument still requires a module-level import even when the body
    imports the same name locally.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text

    lines = text.splitlines()
    drop = set()
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in fn.body:
                for n in range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1):
                    drop.add(n)
    return "\n".join(line for i, line in enumerate(lines, 1) if i not in drop)


def _render_import(node, referenced, skip=()):
    """Re-emit an import keeping only the aliases `referenced` actually uses.

    Returns "" when nothing it binds is used, so the statement is dropped.
    Rebuilt from the AST rather than sliced from source, so a multi-name import
    can be narrowed rather than kept or dropped whole. Names in `skip` are
    omitted even when referenced -- that is how a function-local import wins.
    """
    used = []
    for alias in node.names:
        # `import a.b` binds `a`; an alias binds the alias.
        bound = alias.asname or alias.name.split(".")[0]
        if bound in skip:
            continue
        if _name_used(bound, referenced):
            used.append(
                f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            )

    if not used:
        return ""

    if isinstance(node, ast.ImportFrom):
        module = "." * (node.level or 0) + (node.module or "")
        return f"from {module} import {', '.join(used)}"
    return f"import {', '.join(used)}"


def _name_used(name, text):
    """True when `name` is actually referenced as code in `text`.

    Parses rather than greps: a docstring or a description string may well
    contain the word (`from sqlalchemy import text` vs "converts it to plain
    text"), and a text search cannot tell those apart -- it would keep an import
    the emitted module never uses. Falls back to a word-boundary search only when
    the fragment does not parse.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return re.search(rf"\b{re.escape(name)}\b", text) is not None

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == name:
            return True
        # Decorators and annotations reach names via attribute access too.
        if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == name:
            return True
    return False


def write_tool_source(
    source_text, tool_name, directory=REQUIREMENTS_DIR, source_stem=None
):
    """Write `<tool_name>.py`, but only when the content changed.

    Named after the TOOL, not the authoring notebook, because the ADK derives the
    tool's binding from this filename: `orchestrate` computes
    `<path relative to cwd>:<function>` at import time, so a file called
    `fetch_url_data.py` imported with cwd set to its own directory binds as
    `fetch_url_data:fetch_url_data` -- flat, matching a hand-written standalone
    tool. A name carrying the notebook's stem, or a file imported from the repo
    root, would bind as `src.flow_specs.<notebook>_<tool>:...`, a dotted path
    whose packages do not exist on the server (there is no __init__.py anywhere
    under src/).

    Returns:
        tuple[Path | None, bool]: (path, changed). Path is None when nothing was
        extracted.
    """
    if not source_text:
        return None, False

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{tool_name}.py"

    if path.exists() and path.read_text() == source_text:
        return path, False

    path.write_text(source_text)
    return path, True


def import_tools_to_wxo(
    tool_paths,
    dry_run=False,
    extra_args=None,
    requirements_dir=REQUIREMENTS_DIR,
    extract=True,
    instrument=False,
    append_wxo_adk=True,
    wxo_adk_version=DEFAULT_WXO_ADK_VERSION,
):
    """Import each tool, passing the requirements.txt built from its own block.

    Runs BEFORE the flow import: the flow's tool nodes resolve by name, so the
    tools have to exist in the environment first. Re-importing an existing tool
    overwrites it, so this is safe to run on every import-button click.

    Args:
        tool_paths: Paths to the tool source files. A marimo notebook works --
            `@app.function` puts the @tool at module level -- as does a plain
            module. An entry may instead be a (path, tool_name) pair to read only
            that tool's dependency block; bare paths read every @tool in the
            file, which is what a whole-file import needs since one import ships
            them all.
        dry_run: Parse and report without calling the CLI.
        extra_args: Appended to every `orchestrate tools import` call, e.g.
            ["-a", "my_app"] for a connection app-id.
        requirements_dir: Where `<tool>_requirements.txt` is written, defaulting
            to the flow-spec directory so both import artefacts sit together.
        instrument: Emit the tools with SpanLogger tracing wrapped around each
            body. Default False; turn on to diagnose a tool that fails without a
            message, since an unhandled crash flushes no logs at all.
        append_wxo_adk: Prepend `ibm-watsonx-orchestrate==<wxo_adk_version>` to
            each generated requirements file unless the tool's `# ///` block
            already declares the package at some version. Default True. False
            skips the step entirely. See `ensure_wxo_adk` for how this interacts
            with the CLI's own injection.
        wxo_adk_version: Version for that pin, defaulting to
            DEFAULT_WXO_ADK_VERSION. None or "" pins nothing and lets pip resolve.

    Returns:
        list[dict]: One entry per tool ACTUALLY imported -- path, dependencies,
        the requirements file (None when there are none), whether that file was
        rewritten, and the CompletedProcess (None on dry_run). Duplicates are
        skipped, so this can be shorter than `tool_paths`.

    A file is imported at most once per call. One `-k python` import ships every
    @tool in the file, so importing the same file twice is wasted work at best
    and, since each import re-triggers the server-side venv build, a way to hold
    a tool in "configuring" longer than necessary. Paths are compared resolved,
    so a relative and an absolute reference to the same file count as one.
    """
    results = []
    seen = {}

    for entry in tool_paths:
        # Accept a bare path or a (path, tool_name) pair.
        if isinstance(entry, (tuple, list)):
            tool_path, tool_name = entry
        else:
            tool_path, tool_name = entry, None

        tool_path = Path(tool_path)
        if not tool_path.exists():
            raise FileNotFoundError(f"tool source not found: {tool_path}")

        # resolve() collapses relative/absolute and symlinked spellings of the same file, which a plain string or Path comparison would miss.
        key = tool_path.resolve()
        if key in seen:
            print(f"{tool_path.name}: already imported this run, skipping")
            continue
        seen[key] = True

        # One requirements file per TOOL, named after the tool rather than the file, since that is the name the flow's tool node references. A file holding several tools therefore yields several files.
        declared = tools_in_source(tool_path.read_text())
        if tool_name:
            declared = {
                name: specs for name, specs in declared.items() if name == tool_name
            }

        # The file that actually gets imported. By default the tool is extracted out of its authoring notebook into src/flow_specs/ first, so the ADK receives a plain module holding the tool and nothing else, rather than the notebook's cells, SQL and UI widgets. Set extract=False to import the authoring file verbatim.
        import_path = tool_path
        extracted, extracted_changed = None, False
        if extract:
            for name in declared:
                if tool_name and name != tool_name:
                    continue
                text = extract_tool_source(
                    tool_path.read_text(), name, instrument=instrument
                )
                extracted, extracted_changed = write_tool_source(
                    text, name, requirements_dir, source_stem=tool_path.stem
                )
                if extracted:
                    import_path = extracted
                    print(
                        f"  extracted -> {extracted.name}"
                        f"{' (rewritten)' if extracted_changed else ' (unchanged)'}"
                    )
                # One import per file; if several tools are declared the last extraction wins, so extract them individually via (path, name).
                break

        # The ADK computes the tool's binding as `<path relative to cwd>:<func>`, so running the CLI from the artefact directory with a BARE filename is what produces the flat `fetch_url_data:fetch_url_data` binding that a hand-written standalone tool gets. Passing `src/flow_specs/x.py` from the repo root would instead bind `src.flow_specs.x:...`, a dotted path whose packages do not exist server-side.
        run_cwd = None
        if extract and extracted:
            run_cwd = str(extracted.parent)
            file_arg = extracted.name
        else:
            file_arg = str(import_path)

        command = [
            "orchestrate",
            "tools",
            "import",
            "-k",
            "python",
            "-f",
            file_arg,
        ]

        # Written next to the flow specs, and only rewritten when the parsed block differs from what is on disk.
        written = {}
        for name, specs in declared.items():
            # The ADK pin goes in before the file is written, so what lands on disk is exactly what pip is asked to install.
            specs = ensure_wxo_adk(specs, append_wxo_adk, wxo_adk_version)
            declared[name] = specs
            requirements, changed = write_requirements(
                specs, name, requirements_dir, source_stem=tool_path.stem
            )
            if requirements:
                written[name] = (requirements, changed)
            state = (
                "(none)"
                if not specs
                else f"{specs} -> {requirements.name}"
                f"{' (rewritten)' if changed else ' (unchanged)'}"
            )
            print(f"{tool_path.name} [{name}]: dependencies {state}")

        if not declared:
            print(f"{tool_path.name}: no @tool found")

        # One `-k python` import ships the whole file, so the tools in it share a single venv and pip gets one -r. Several tools each declaring their own block means those blocks must agree; the union is what actually gets installed, so a conflict between them surfaces at deploy, not here.
        dependencies = _dedupe([spec for specs in declared.values() for spec in specs])

        # Relative to run_cwd when one is set, so the -r path resolves from the same directory the -f path does.
        def _arg(path):
            return path.name if run_cwd else str(path)

        if len(written) > 1:
            # The union is per-FILE rather than per-tool, so it is named for the authoring file to keep it distinct from the per-tool files.
            combined, _ = write_requirements(
                dependencies, f"{tool_path.stem}_all_tools", requirements_dir
            )
            command += ["-r", _arg(combined)]
            print(
                f"  {len(written)} tools in one file -> importing with the "
                f"union, {combined.name}"
            )
        elif written:
            only = next(iter(written.values()))[0]
            command += ["-r", _arg(only)]

        if extra_args:
            command += list(extra_args)

        if dry_run:
            where = f" (cwd: {run_cwd})" if run_cwd else ""
            print("  would run:", " ".join(command) + where)
            results.append(
                {
                    "path": tool_path,
                    "dependencies": dependencies,
                    "requirements": requirements,
                    "requirements_changed": changed,
                    "extracted": extracted,
                    "extracted_changed": extracted_changed,
                    "proc": None,
                }
            )
            continue

        proc = subprocess.run(command, capture_output=True, text=True, cwd=run_cwd)

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
            {
                "path": tool_path,
                "dependencies": dependencies,
                "requirements": requirements,
                "requirements_changed": changed,
                "extracted": extracted,
                "extracted_changed": extracted_changed,
                "proc": proc,
            }
        )

    return results
