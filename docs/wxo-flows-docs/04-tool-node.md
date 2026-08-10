# Tool node - `tool()`

Calls an imported tool and returns its result.

```py
node = aflow.tool(tool, name=..., display_name=..., description=...,
                  input_schema=..., output_schema=..., input_map=...,
                  error_handler_config=...)
```

Returns a tool node registered on `aflow`.

## Parameters

| Param                  | Type                     | Req | Notes                                                             |
| ---------------------- | ------------------------ | --- | ----------------------------------------------------------------- |
| `tool`                 | `Any \| str`             | yes | Tool name (`"myTool"`) or a Python function reference (`myTool`). |
| `name`                 | `str`                    | no  | Node name.                                                        |
| `display_name`         | `str`                    | no  | UI name.                                                          |
| `description`          | `str`                    | no  | Node description.                                                 |
| `input_schema`         | `type[BaseModel]`        | no  | Input schema.                                                     |
| `output_schema`        | `type[BaseModel]`        | no  | Output schema.                                                    |
| `input_map`            | `DataMap`                | no  | Structured input mapping. See [03](03-data-mapping.md).           |
| `error_handler_config` | `NodeErrorHandlerConfig` | no  | Retry/branch on failure. See [20](20-error-handling.md).          |

## Passing the tool

- **By reference** - only functions decorated with `@tool` qualify.
- **By name** - a string, for tools already imported into the environment (OpenAPI tools,
  tools you did not author, etc.).

```py
from ibm_watsonx_orchestrate.agent_builder.tools import tool, ToolPermission

node_a = aflow.tool(send_emails)      # @tool-decorated function
node_b = aflow.tool("getDogFact")     # imported tool, by name
```

## Minimum call form

```py
node = aflow.tool(my_tool)
aflow.sequence(START, node, END)
```

## Supported tool kinds

Tool nodes resolve four kinds: **OpenAPI**, **Python**, **Flow**, **MCP**.

## Connections

Flows do not carry connections. A tool node's connection is configured on the downstream
component tool itself.

## As a flow callback

When a tool is used as a flow callback (see [21](21-callbacks.md)):

- Prefer **OpenAPI** tools - stateless, no correlation-ID propagation.
- A **Flow** used as a callback tool must contain **no user activity nodes**. The runtime
  would have to submit user-activity events into the caller's chat thread, which requires
  correlation-ID propagation through the callback chain and is not supported.

## Error handling

```py
aflow.tool(
    "someTool",
    error_handler_config=NodeErrorHandlerConfig(
        on_error="branch",
        error_edge_id="some_error_edge",
    ),
)
aflow.edge(node, recovery_node, id="some_error_edge")
```
