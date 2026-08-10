# Conditions branch node - `conditions()`

Exclusive routing. Evaluates conditions in declaration order and follows **only the first
match** - if/elif/else semantics.

```py
from ibm_watsonx_orchestrate.flow_builder.flows import Branch

branch: Branch = aflow.conditions()
```

Returns a `Branch`. Wire it as a node: give it an inbound edge; its outbound edges are
declared by the `to_node` of each condition.

## `condition(to_node, expression=None, default=False)`

Returns the `Branch`, so calls chain.

| Param        | Type   | Req   | Notes                                              |
| ------------ | ------ | ----- | -------------------------------------------------- |
| `to_node`    | `Node` | yes   | Node to run when this condition matches.           |
| `expression` | `str`  | cond. | Python expression. Required unless `default=True`. |
| `default`    | `bool` | no    | Marks the fallback path. Declare it last.          |

## Call form

```py
dog_node = aflow.tool("getDogFact")
cat_node = aflow.tool("getCatFact")

branch: Branch = aflow.conditions()
branch.condition(
    expression="flow.input.kind.strip().lower() == 'dog'", to_node=dog_node
).condition(
    expression="flow.input.kind.strip().lower() == 'cat'", to_node=cat_node
).condition(
    to_node=dog_node, default=True
)

aflow.edge(START, branch)
aflow.edge(dog_node, END)
aflow.edge(cat_node, END)
```

Note the shape: `edge(START, branch)` feeds the branch; each target's own path to `END` is
wired separately. The branch itself gets no outbound `edge()` calls.

## Rules

- Two or more exit paths supported.
- Evaluation is top-to-bottom; the first matching expression wins and no further conditions
  are evaluated.
- Only the matching path runs - a single path continues downstream.
- A branch node is the one exception to "multiple outgoing edges run in parallel".
- The `default=True` condition takes no `expression`. Provide one, or unmatched input has
  nowhere to go.

## Versus parallel

|            | `conditions()`                | `parallel_conditions()` |
| ---------- | ----------------------------- | ----------------------- |
| Processing | First matching condition only | All matching conditions |
| Semantics  | Sequential, if-else           | Concurrent              |
| Use case   | Exclusive paths               | Concurrent execution    |
| Merging    | Single path continues         | Waits for all paths     |

See [09-parallel-node.md](09-parallel-node.md).

## Expressions

Full grammar in [02-expressions.md](02-expressions.md). Conditions may read `flow.input.*`,
`flow.private.*`, and upstream node outputs.
