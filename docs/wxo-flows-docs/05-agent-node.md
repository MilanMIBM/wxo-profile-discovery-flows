# Agent node — `agent()`

Calls an imported agent to perform a task.

```py
node = aflow.agent(name=..., agent=..., display_name=..., title=..., message=...,
                   description=..., input_schema=..., output_schema=...,
                   guidelines=..., input_map=..., error_handler_config=...)
```

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Node name. |
| `agent` | `str` | yes | Name of the imported agent to call. |
| `display_name` | `str` | no | UI name. |
| `title` | `str` | no | Agent title. |
| `message` | `str` | no | The instruction sent to the agent. Defaults to `"Follow the agent instructions"`. |
| `description` | `str` | no | Node description. |
| `input_schema` | `type[BaseModel]` | no | Input schema. |
| `output_schema` | `type[BaseModel]` | no | Output schema. |
| `guidelines` | `str` | no | Agent guidelines. |
| `input_map` | `DataMap` | no | Structured input mapping. See [03](03-data-mapping.md). |
| `error_handler_config` | `NodeErrorHandlerConfig` | no | Retry/branch on failure. See [20](20-error-handling.md). |

## Minimum call form

```py
node = aflow.agent(name="ask", agent="ibm_agent")
```

## Writing `message`

The `message` is a natural-language instruction, not a template contract. Be precise about
the task and state the fallback, or the agent may not respond in the shape
`output_schema` expects. Refer to data the flow engine will supply.

```py
message="Give an answer about IBM based on the provided question. If you don't know the answer, just say 'I do not know'"
```

## Conversation memory

The flow-level `agent_conversation_memory_turns_limit` (on `@flow`) bounds the conversation
turns retained across agent nodes. See [01](01-flow-and-edges.md).
