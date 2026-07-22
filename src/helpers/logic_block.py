# Author script nodes as real functions instead of strings.
#
# A script node's body is a Python *source string* the flow engine execs in a
# restricted sandbox with `flow`, `self`, `parent` and `json` pre-injected.
# Written as a string it gets no highlighting, no linting, and -- inside marimo
# -- the formatter re-indents string contents to match the cell body, flattening
# nested blocks into invalid Python.
#
# @logic_block lifts the body back out as source via inspect + dedent. Because
# the body is dedented as a unit, marimo can re-indent the cell however it likes
# and the extracted script stays valid.
#
# Define once, in its own cell, with the same node metadata aflow.script() takes:
#
#     @logic_block(
#         display_name="Build respondent profiles",
#         description="Collapses the flat quiz tables into one profile each.",
#         output_schema=BuildProfilesOutput,
#     )
#     def build_respondent_profiles(flow, self, json):
#         node_out = flow.get("retrieve_tables") or {}
#         ...
#         self.output.profiles = records
#
# Then attach it to any flow, sub-flow, foreach or parallel scope by calling it:
#
#     build = build_respondent_profiles(aflow)
#     stage = stage_current_profile(each_profile)
#     aflow.sequence(START, retrieve, build, ...)
#
# The sandbox names are declared as parameters purely so linters resolve them;
# the engine injects them, so the function is never really called that way.

import ast
import inspect
import textwrap

# Names the flow engine injects into every script node's namespace.
SANDBOX_NAMES = ("flow", "self", "parent", "json")

# Node metadata forwarded verbatim to Flow.script().
_NODE_FIELDS = (
    "display_name",
    "description",
    "input_schema",
    "output_schema",
    "position",
    "dimensions",
)


class LogicBlock:
    """A script node defined as a function.

    Call it with a flow scope to attach it as a node:

        node = my_block(aflow)          # -> ScriptNode
        node = my_block(each_profile)   # foreach/parallel scopes work too
        node = my_block(aflow, name="override_name")

    Attributes:
        name:     node name (the function's name unless overridden)
        script:   the body as dedented source
        config:   kwargs for Flow.script(), including the script itself
    """

    def __init__(self, fn, name=None, **node_kwargs):
        unknown = set(node_kwargs) - set(_NODE_FIELDS)
        if unknown:
            raise TypeError(
                f"@logic_block got unexpected node field(s): {', '.join(sorted(unknown))}. "
                f"Valid fields: {', '.join(_NODE_FIELDS)}"
            )
        self._fn = fn
        self._node_kwargs = {k: v for k, v in node_kwargs.items() if v is not None}
        self.name = name or fn.__name__
        self.script = _extract_body(fn)
        # A docstring documents the block; reuse it as the node description when
        # none was given explicitly.
        if "description" not in self._node_kwargs and fn.__doc__:
            self._node_kwargs["description"] = inspect.cleandoc(fn.__doc__)
        self.__doc__ = fn.__doc__
        self.__name__ = self.name

    @property
    def config(self):
        """Everything Flow.script() needs, as kwargs."""
        return {"name": self.name, "script": self.script, **self._node_kwargs}

    def __call__(self, scope, **overrides):
        """Attach this block to `scope` (a Flow, Foreach, Parallel, ...)."""
        if not hasattr(scope, "script"):
            raise TypeError(
                f"{self.name}() expects a flow scope with a .script() method, "
                f"got {type(scope).__name__}. To run the body directly for a test, "
                f"use {self.name}.run(flow=..., self=...)."
            )
        return scope.script(**{**self.config, **overrides})

    def run(block, /, **sandbox):
        """Invoke the underlying function directly, for unit tests.

        The first parameter is positional-only and named `block`, not `self`, so
        `self=` stays free for the sandbox name the engine injects:

            my_block.run(flow=..., self=..., json=json)
        """
        if block._fn is None:
            raise TypeError(
                f"logic block {block.name!r} was loaded from a file and has no "
                "Python function to run; only its script source is available."
            )
        return block._fn(**sandbox)

    def __str__(self):
        return self.script

    def __repr__(self):
        lines = self.script.count("\n")
        return f"<LogicBlock {self.name!r}: {lines} lines>"


def _extract_body(fn) -> str:
    """Return fn's body as standalone source, minus the def line and docstring."""
    try:
        src = textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError) as exc:
        raise RuntimeError(
            f"cannot read source for logic block {fn.__name__!r}. @logic_block needs "
            "the defining source on disk -- it works in marimo notebooks and modules, "
            "but not in a bare REPL or exec'd string."
        ) from exc

    # Parse to find where the body starts, so decorators, multi-line signatures
    # and a leading docstring are all dropped reliably.
    fn_node = ast.parse(src).body[0]
    if not isinstance(fn_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise TypeError(f"@logic_block expects a function, got {type(fn_node).__name__}")

    body = fn_node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # the docstring documents the block, not the node
    if not body:
        raise ValueError(f"logic block {fn.__name__!r} has an empty body")

    lines = src.splitlines()
    # ast line numbers are 1-based; decorators sit above the def, so the first
    # body statement's lineno is the correct cut point.
    start = body[0].lineno - 1
    end = max(stmt.end_lineno for stmt in body)
    return textwrap.dedent("\n".join(lines[start:end])).rstrip() + "\n"


def logic_block(fn=None, *, name=None, **node_kwargs):
    """Turn a function into a callable script node. Bare or with node metadata."""
    if fn is None:
        return lambda f: LogicBlock(f, name=name, **node_kwargs)
    return LogicBlock(fn, name=name, **node_kwargs)


def from_file(path, name=None, **node_kwargs):
    """Wrap an existing logic-block .py file as a LogicBlock.

    Lets file-based blocks (src/helpers/logic-blocks/*.py) be attached with the
    same call syntax as decorated ones, so both styles can coexist.
    """
    from pathlib import Path

    path = Path(path)
    block = LogicBlock.__new__(LogicBlock)
    block._fn = None
    block._node_kwargs = {k: v for k, v in node_kwargs.items() if v is not None}
    block.name = name or path.stem
    block.script = path.read_text()
    block.__doc__ = None
    block.__name__ = block.name
    return block
