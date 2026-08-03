# Flow callbacks — `add_callback()`

Invokes a tool when specified events occur during a flow run. Creates a `FlowCallback`,
appends it to the flow spec, and returns `Self` — so calls chain.

```py
from ibm_watsonx_orchestrate.flow_builder.flow_callback_types import FlowCallbackEventKind

aflow.add_callback(
    tool="flow_callback_handler",
    events=[
        FlowCallbackEventKind.ON_FLOW_START,
        FlowCallbackEventKind.ON_FLOW_END,
        FlowCallbackEventKind.ON_FLOW_ERROR,
    ],
)
```

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `tool` | `str` | yes | Tool identifier. Four accepted formats, below. |
| `events` | `List[FlowCallbackEventKind]` | yes | Events that trigger the callback. |
| `batch_interval` | `int` | no | Batching interval in **milliseconds**. Server default when omitted. |

## `tool` identifier formats

| Format | Example |
| --- | --- |
| `tool_name` | `"flow_callback_handler"` |
| `tool_name:tool_uuid` | `"error_handler:abc-123-def-456"` |
| `toolkit:tool_name` | `"monitoring_toolkit:task_event_handler"` |
| `toolkit:tool_name:tool_uuid` | `"audit_toolkit:audit_logger:xyz-789"` |

## `FlowCallbackEventKind`

| Event | Fires when | Batched? |
| --- | --- | --- |
| `ON_FLOW_START` | Flow starts. | Yes |
| `ON_FLOW_END` | Flow completes. | Yes |
| `ON_FLOW_ERROR` | Flow errors. | Yes |
| `ON_TASK_MESSAGE` | Task emits a message. | **No** — invoked immediately. |
| `ON_TASK_WAIT` | Task waits for user input. | **No** — invoked immediately. |
| `ON_TASK_ERROR` | Task errors. | — |

`batch_interval` applies only to the three `ON_FLOW_*` events. It is ignored for
`ON_TASK_MESSAGE` and `ON_TASK_WAIT`.

## Execution model

The flow runtime executes callbacks **fire-and-forget**, for performance. Do not rely on a
callback's completion or return value to gate flow logic.

## Supported callback tool kinds

OpenAPI, Python, Flow, MCP.

**Prefer OpenAPI tools.** They give a clean, stateless callback interface with no user
interaction to manage and no correlation-ID propagation.

## Constraint — Flow tools as callbacks

A Flow used as a callback tool **must not contain user activity nodes**.

Why: the runtime would have to submit user-activity events into the caller's chat thread,
which requires propagating correlation IDs through the callback event chain. That is not
supported.

Workaround: design flows intended as callbacks without user interaction.

## Registering multiple callbacks

Call `add_callback()` once per handler, or append `FlowCallback` objects directly.

```py
aflow.add_callback(
    tool="monitoring_toolkit:task_event_handler",
    events=[
        FlowCallbackEventKind.ON_TASK_WAIT,
        FlowCallbackEventKind.ON_TASK_ERROR,
        FlowCallbackEventKind.ON_TASK_MESSAGE,
    ],
    batch_interval=30000,
)

# Direct append
from ibm_watsonx_orchestrate.flow_builder.types import FlowCallback

aflow.callbacks.append(FlowCallback(
    tool="audit_toolkit:audit_logger:xyz-789-ghi-012",
    events=[FlowCallbackEventKind.ON_FLOW_START, FlowCallbackEventKind.ON_FLOW_END],
    batch_interval=60000,
))
```

## Local run handlers

Distinct from registered callbacks: `invoke()` takes per-run Python handlers for local
testing. See [01](01-flow-and-edges.md).

```py
run = await definition.invoke(
    payload, on_flow_end_handler=on_end, on_flow_error_handler=on_error, debug=True
)
```
