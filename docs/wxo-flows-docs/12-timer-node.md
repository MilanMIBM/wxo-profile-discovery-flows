# Timer node — `timer()`

Introduces a delay between actions.

```py
node = aflow.timer(name=..., delay=..., display_name=..., description=..., input_map=...)
```

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Unique node identifier. |
| `delay` | `int` | yes | Delay in **milliseconds**. |
| `display_name` | `str` | no | UI name. |
| `description` | `str` | no | Node description. |
| `input_map` | `DataMap` | no | Structured input mapping. See [03](03-data-mapping.md). |

## Minimum call form

```py
node = aflow.timer(name="wait_1_sec", delay=1000)
```

## In a polling loop

The common use: back off between status checks inside a `loop()` subflow.

```py
timer_node = while_loop.timer(
    name="wait_1_sec",
    delay=1000,
    description="Wait for 1 second before polling again",
)
while_loop.sequence(START, get_request_status_node, timer_node, END)
```

Available on `Flow` and on any subflow. See [11-loop-node.md](11-loop-node.md).
