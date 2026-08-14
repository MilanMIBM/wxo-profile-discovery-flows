# Collect every iteration's record out of a foreach loop.
#
# A PARALLEL foreach gives each iteration its own copy of flow state and merges
# the copies back by whole-object replacement, so anything a logic block writes
# to shared state is overwritten by whichever branch commits last. Measured on a
# 40-iteration run: a flow.private list kept 8 records (one per concurrency
# batch) and per-iteration system.context keys kept 1 (one per run), with every
# iteration completed and no errors. The records were produced and then lost in
# the merge.
#
# `parent.<loop_name>.output` is the surface that does expose all of them: every
# node execution from every iteration, flattened in completion order, each
# wrapped in its own single-element list --
#
#     [[node_a], [node_b], [node_c], [node_a], [node_b], [node_c], ...]
#
# so an N-node loop body yields N entries per iteration. Note this is different
# from `parent.<loop_name>.<node_name>.output.<field>`, which resolves to a
# single node's *current* value, i.e. the last branch to commit -- one record,
# not all of them.
#
# This builds a script node that walks that aggregate and pulls out one record
# per iteration:
#
#     from src.helpers.foreach_collector import foreach_collector
#
#     collect = foreach_collector(
#         loop_name="each_respondent",
#         record_key="enriched_profile",
#         name="collect_enriched_profiles",
#         output_field="enriched_profiles",
#         display_name="Collect enriched profiles",
#     )
#     node = collect(aflow, output_schema=CollectedOutput)
#     aflow.sequence(START, build, each, node, table, END)
#
# Records are identified by KEY, not position: an entry qualifies if it carries
# `record_key`. Nodes can be added to or reordered within the loop body without
# touching the collector.
#
# The node must sit OUTSIDE the loop. It reads by expression rather than through
# an edge, but it still has to run after the loop and before whatever consumes
# it, so keep it in the sequence.

from src.helpers.logic_block import LogicBlock

# Emitted verbatim into the script node. `{loop_name}` etc. are filled in by
# str.replace rather than .format(), since the body contains literal braces and
# str.format() is unavailable in the sandbox anyway.
_TEMPLATE = '''
collected = parent.__LOOP_NAME__.output

# Every node execution from every iteration, flattened, each in its own
# single-element list. Only __RECORD_KEY__-bearing entries are iteration records;
# the rest are the other nodes in the loop body.
records = []
stack = [collected]
while stack:
    entry = stack.pop(0)
    if isinstance(entry, list):
        for item in entry:
            stack.append(item)
        continue
    if not isinstance(entry, dict):
        continue
    value = entry.get("__RECORD_KEY__")
    if isinstance(value, dict):
        records.append(
            {
                "iteration_index": entry.get("__INDEX_KEY__"),
                "value": value,
            }
        )

# The loop is PARALLEL, so arrival order is completion order. Sort back to input
# order where the index is present; records without one keep their position, at
# the end.
indexed = []
unindexed = []
for record in records:
    if isinstance(record.get("iteration_index"), int):
        indexed.append(record)
    else:
        unindexed.append(record)
indexed.sort(key=lambda r: r["iteration_index"])

self.output.__OUTPUT_FIELD__ = [r["value"] for r in indexed + unindexed]
self.output.collected_num = len(records)
self.output.collected_indices = [r["iteration_index"] for r in indexed]
'''

# Used when no record_key is given: keep every node execution rather than the one
# node's record. Nothing identifies an iteration here, so there is no per-iteration
# grouping and no reordering -- the aggregate is flattened and returned as-is, in
# completion order. Useful for inspecting what a loop actually emitted.
_TEMPLATE_ALL = '''
collected = parent.__LOOP_NAME__.output

# Every node execution from every iteration, flattened out of the single-element
# lists the engine wraps each one in. No record_key was given, so nothing is
# filtered: entries from every node in the loop body are kept.
records = []
stack = [collected]
while stack:
    entry = stack.pop(0)
    if isinstance(entry, list):
        for item in entry:
            stack.append(item)
        continue
    if isinstance(entry, dict):
        records.append(entry)

# Completion order, not input order: without a record_key there is no reliable
# per-iteration anchor, and only some entries carry an index at all.
self.output.__OUTPUT_FIELD__ = records
self.output.collected_num = len(records)
self.output.collected_indices = [
    entry.get("__INDEX_KEY__")
    for entry in records
    if isinstance(entry.get("__INDEX_KEY__"), int)
]
'''


def foreach_collector(
    loop_name,
    record_key=None,
    name=None,
    output_field=None,
    index_key="iteration_index",
    display_name=None,
    description=None,
    **node_kwargs,
):
    """Build a script node that collects records out of a foreach loop.

    Args:
        loop_name: The foreach node's `name`, e.g. "each_respondent". Must match
            what was passed to `aflow.foreach(name=...)`.
        record_key: The output field the per-iteration record lives under, e.g.
            "enriched_profile" or "row". An entry in the aggregate counts as a
            record when this key holds a dict, so it must be unique to the node
            producing the record -- if two nodes in the loop body emit the same
            key, both are collected.

            OMIT IT to collect everything: every node execution from every
            iteration is kept, unfiltered, in completion order. There is no
            per-iteration record to anchor on in that mode, so nothing is
            reordered and the output holds one entry per node per iteration
            (an N-node loop over M items yields N*M entries) rather than one per
            iteration. Mostly useful for seeing what a loop actually emitted.
        name: Node name. Defaults to "collect_<output_field>".
        output_field: Field to write the list to. Defaults to `record_key` + "s",
            or "collected" when no record_key is given.
        index_key: The field carrying the iteration index, used to restore input
            order. The loop's record-producing node should set it from
            `parent._current_index`. Records without it still collect, they just
            stay in completion order.
        display_name / description / **node_kwargs: Forwarded to Flow.script().

    Returns:
        LogicBlock -- call it with a flow scope to attach it, exactly like a
        @logic_block-decorated function.

    The node writes three outputs: `<output_field>` (the records), and
    `collected_num` / `collected_indices` for verification. With a record_key, a
    gap in `collected_indices` names the iteration whose record did not make it
    out; without one, the indices are only whichever entries happened to carry
    the index field, so they are informational rather than a completeness check.
    """
    if not loop_name:
        raise ValueError("foreach_collector needs the foreach node's loop_name")

    collect_all = not record_key
    output_field = output_field or ("collected" if collect_all else f"{record_key}s")
    name = name or f"collect_{output_field}"

    template = _TEMPLATE_ALL if collect_all else _TEMPLATE
    script = (
        template.replace("__LOOP_NAME__", loop_name)
        .replace("__RECORD_KEY__", record_key or "")
        .replace("__INDEX_KEY__", index_key)
        .replace("__OUTPUT_FIELD__", output_field)
        .lstrip("\n")
    )

    if description is None and collect_all:
        description = (
            f"Collects every node execution from every iteration of the "
            f"`{loop_name}` foreach into `{output_field}`, unfiltered and in "
            f"completion order, reading the loop's aggregate output rather than "
            f"shared state, which does not survive a parallel loop's branch merge."
        )
    elif description is None:
        description = (
            f"Collects one `{record_key}` record per iteration of the "
            f"`{loop_name}` foreach into `{output_field}`, reading the loop's "
            f"aggregate output rather than shared state, which does not survive "
            f"a parallel loop's branch merge."
        )

    block = LogicBlock.__new__(LogicBlock)
    block._fn = None
    block._node_kwargs = {
        k: v
        for k, v in {
            "display_name": display_name or f"Collect {output_field}",
            "description": description,
            **node_kwargs,
        }.items()
        if v is not None
    }
    block.name = name
    block.script = script
    block.__doc__ = description
    block.__name__ = name
    return block


def collected_output_schema(output_field, model_name=None, item_description=None):
    """Build the pydantic output_schema matching a foreach_collector's outputs.

    Saves declaring the same three fields per flow. Pass the result as
    `output_schema=` when attaching the node:

        schema = collected_output_schema("enriched_profiles")
        node = collect(aflow, output_schema=schema)
    """
    from typing import Any, List

    from pydantic import BaseModel, Field, create_model

    return create_model(
        model_name or "CollectedOutput",
        __base__=BaseModel,
        **{
            output_field: (
                List[dict],
                Field(
                    default_factory=list,
                    description=item_description
                    or f"Records collected from the foreach, in `{output_field}`.",
                ),
            ),
            "collected_num": (
                int,
                Field(
                    default=0,
                    description="How many records were recovered from the loop.",
                ),
            ),
            "collected_indices": (
                List[int],
                Field(
                    default_factory=list,
                    description=(
                        "The foreach indices recovered, sorted -- a gap names an "
                        "iteration whose record did not make it out."
                    ),
                ),
            ),
        },
    )
