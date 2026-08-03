# Parallel branch nodes — `parallel()` / `parallel_conditions()`

Concurrent routing. Both return a **subflow** you add nodes to; the parent resumes only
after every started branch reaches the subflow's `END`.

| | `parallel()` | `parallel_conditions()` |
| --- | --- | --- |
| Runs | Every branch, always | Every branch whose condition matches |
| Evaluator | `evaluator=None` | conditions via `condition()` |

## `parallel(evaluator=None, name=..., display_name=...)`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `evaluator` | `Conditions \| None` | no | `None` = unconditional; all branches run. |
| `name` | `str` | no | Generated if omitted. |
| `display_name` | `str` | no | UI name. |

Use for: running multiple teams at once, sending work to multiple services, processing data
through multiple pipelines.

```py
p = aflow.parallel(evaluator=None, name="parallel_development")
a = p.script(name="a", script="...")
b = p.script(name="b", script="...")
p.sequence(START, a, END)
p.sequence(START, b, END)
aflow.sequence(START, p, completion_node, END)
```

Each branch is wired `START → branch → END` **inside** the subflow.

## `parallel_conditions(name=..., display_name=...)`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Generated if left empty. |
| `display_name` | `str` | no | Defaults to the node name. |

Use for: multi-criteria processing, routing to multiple handlers by attribute, fan-out on
matching conditions.

### `condition(to_node, expression=None, default=False)`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `to_node` | `Node` | yes | Node to run when the condition matches. |
| `expression` | `str` | cond. | Required unless `default=True`. |
| `default` | `bool` | no | The else case. |

```py
p = aflow.parallel_conditions(name="task_processing")
high = p.script(name="high_priority_handler", script="...")
bill = p.script(name="billing_handler", script="...")
dflt = p.script(name="default_handler", script="...")

p.condition(expression="flow.input.priority == 'high'", to_node=high) \
 .condition(expression="flow.input.category == 'billing'", to_node=bill) \
 .condition(default=True, to_node=dflt)

p.sequence(high, END)
p.sequence(bill, END)
p.sequence(dflt, END)
aflow.sequence(START, p, END)
```

All matching conditions run concurrently — unlike `conditions()`, matching does not stop at
the first hit.

## Merging

Parallel subflows merge at their internal `END`. The parent continues only after every
branch completes.

```py
next_node = aflow.script(name="after_parallel", script="...")
aflow.edge(parallel_flow, next_node)     # runs after ALL branches finish
```

## Error handling per branch

Branches fail independently. Attach a handler per branch node.

```py
task = p.script(
    name="task1",
    script="...",
    error_handler=NodeErrorHandlerConfig(on_error="continue", max_retries=3),
)
```

## Constraint — no loop-back

Never edge a parallel branch back to an earlier node. This spawns unlimited parallel
threads and breaks at runtime.

```py
# WRONG
p.edge(node1, node2)
p.edge(node2, node1)   # unbounded thread creation
```

## Choosing

- Every branch must run → `parallel()`
- Branch execution depends on conditions → `parallel_conditions()`
- Only one path must run → `conditions()`, see [08](08-branch-node.md)
