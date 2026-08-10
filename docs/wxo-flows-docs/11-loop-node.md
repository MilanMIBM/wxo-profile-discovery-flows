# Loop node - `loop()`

A nested subflow that repeats **while** a condition holds - while-loop semantics. Returns a
`Flow`.

```py
while_loop: Flow = aflow.loop(evaluator=..., input_schema=..., output_schema=...)
```

## Parameters

| Param           | Type        | Req | Notes                                                           |
| --------------- | ----------- | --- | --------------------------------------------------------------- |
| `evaluator`     | `str`       | yes | Python expression. The subflow repeats while it evaluates true. |
| `input_schema`  | `BaseModel` | no  | Input schema of the nested subflow.                             |
| `output_schema` | `BaseModel` | no  | Output schema of the nested subflow.                            |

## Call form

```py
while_loop: Flow = aflow.loop(
    evaluator="not parent.get_request_status.input.attempt.atmp or parent.get_request_status.input.attempt.atmp < 5",
    input_schema=Attempt,
    output_schema=FlowOutput,
)

status_node = while_loop.tool(get_request_status)
timer_node = while_loop.timer(name="wait_1_sec", delay=1000)
while_loop.sequence(START, status_node, timer_node, END)

aflow.sequence(START, first_node, while_loop, END)
```

## Writing the evaluator

The evaluator runs in the **subflow's** context, so it reaches the enclosing flow through
`parent`. Reference a counter carried on a node's input, and guard the first pass where the
counter is unset:

```py
"not parent.get_request_status.input.attempt.atmp or parent.get_request_status.input.attempt.atmp < 5"
```

The `not <x>` clause admits the first iteration; the comparison bounds the rest. Without a
bound the loop does not terminate.

## Polling pattern

Pair a status tool with a `timer()` node inside the loop to back off between attempts.

```py
status = while_loop.tool(get_request_status)
wait = while_loop.timer(name="wait_1_sec", delay=1000,
                        description="Wait for 1 second before polling again")
while_loop.sequence(START, status, wait, END)
```

See [12-timer-node.md](12-timer-node.md).

## Versus foreach

|             | `loop()`                  | `foreach()`                |
| ----------- | ------------------------- | -------------------------- |
| Repeats     | While a condition is true | Once per item in a list    |
| Control     | `evaluator` expression    | `item_schema` + `policy()` |
| Concurrency | Sequential                | `SEQUENTIAL` or `PARALLEL` |
