# Error handling — `NodeErrorHandlerConfig`

Per-node control over failure: retry, show a message, or redirect down an error edge.

```py
from ibm_watsonx_orchestrate.flow_builder.types import NodeErrorHandlerConfig

aflow.tool(
    "someTool",
    error_handler_config=NodeErrorHandlerConfig(
        on_error="branch",
        error_edge_id="some_error_edge",
    ),
)
```

Attach via `error_handler_config=` on `tool()`, `agent()`, `prompt()`, and the document
nodes; via `error_handler=` on `script()` within parallel subflows.

## Parameters

| Param | Type | Notes |
| --- | --- | --- |
| `error_message` | `str` | Describes the error. Logged for observability and debugging. **Not shown to the user** unless you surface it through a user flow or UI element. |
| `max_retries` | `int` | Retry attempts after a failure. `0` → apply `on_error` immediately. Omitted → platform default. |
| `retry_interval` | `int` | Delay between retries, in **milliseconds**. Only applies when `max_retries > 0`. |
| `on_error` | `str` | How the flow responds. See below. |
| `error_edge_id` | `str` | Edge to follow when `on_error="branch"`. Must match an `id` given to `aflow.edge(...)`. |

## `on_error` values

| Value | Behavior |
| --- | --- |
| `show_message` | Stops the flow after displaying an error message to the user. Use when no alternate path applies. |
| `branch` | Redirects execution along `error_edge_id`. Use for expected failures, recovery paths, or fallback logic — suits services with variable availability. |
| `continue` | Continues despite failure. Used for independent parallel branches. See [09](09-parallel-node.md). |

## Error edges

`error_edge_id` must name an edge you declared. If no matching edge exists, the flow fails
at validation or execution time.

```py
dog_fact_node = aflow.tool(
    "getDogFact",
    error_handler_config=NodeErrorHandlerConfig(
        error_message="Dog facts retrieval failed; redirecting to user message",
        max_retries=0,
        retry_interval=1000,
        on_error="branch",
        error_edge_id="dog_error_to_user_message",
    ),
)

# Happy path
aflow.sequence(START, dog_fact_node, END)

# Error path — the id matches error_edge_id
aflow.edge(dog_fact_node, user_flow, id="dog_error_to_user_message")
aflow.edge(user_flow, END)
```

A node carries both its normal outbound edge and its error edge; the engine picks at
runtime based on outcome.

## Dict form

`error_handler_config` also accepts a plain dict:

```py
error_handler_config={
    "error_message": "An error has occurred while invoking the LLM",
    "max_retries": 1,
    "retry_interval": 1000,
}
```

## Surfacing errors to users

`error_message` is log-only. To show something, branch to a user flow with a text output
field:

```py
user_flow = aflow.userflow()
err = user_flow.field(
    direction="output", name="error_display", display_name="Error Message",
    kind=UserFieldKind.Text,
    text="Sorry, we couldn't fetch dog facts at this time. Please try again later.",
)
user_flow.edge(START, err)
user_flow.edge(err, END)
```

## Retry semantics

- `max_retries=0` → no retries; `on_error` fires immediately.
- `max_retries` omitted → platform default retry behavior.
- `retry_interval` is ignored unless `max_retries > 0`.
