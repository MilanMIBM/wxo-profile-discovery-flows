# Flow, decorator, and edges

## `@flow` decorator

Marks a builder function as a flow definition. The decorated function must take a single
`Flow` parameter and return that `Flow`.

```py
from ibm_watsonx_orchestrate.flow_builder.flows import Flow, flow, START, END

@flow(name="...", input_schema=In, output_schema=Out)
def build(aflow: Flow) -> Flow:
    ...
    return aflow
```

### Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal flow/tool name. |
| `display_name` | `str` | no | UI name. |
| `description` | `str` | no | Drives agent tool-selection; write it for the LLM. |
| `input_schema` | `type[BaseModel]` | no | Populates `flow.input.*`. |
| `output_schema` | `type[BaseModel]` | no | Populates `flow.output.*`. May be `str` or `None`. |
| `private_schema` | `type[BaseModel]` | no | Populates `flow.private.*` — internal state, not exposed. |
| `initiators` | — | no | Who may start the flow. |
| `schedulable` | `bool` | no | `True` enables schedule creation from Chat UI. |
| `llm_model` | `str` | no | Model backing auto-mapping / flow-level LLM work. |
| `agent_conversation_memory_turns_limit` | `int` | no | Conversation memory turns for agent nodes. |

## `Flow` object

The `aflow` parameter. Two roles: **node factory** and **graph builder**.

### Node factories (each returns a node registered on the flow)

| Method | Sheet |
| --- | --- |
| `tool()` | [04](04-tool-node.md) |
| `agent()` | [05](05-agent-node.md) |
| `prompt()` | [06](06-prompt-node.md) |
| `script()` | [07](07-script-node.md) |
| `timer()` | [12](12-timer-node.md) |
| `decisions()` | [13](13-decisions-node.md) |
| `docproc()` / `docext()` / `docclassifier()` | [17](17-docproc-node.md) / [18](18-docext-node.md) / [19](19-docclassifier-node.md) |

### Subflow factories (each returns a `Flow` you build into, then wire as one node)

| Method | Returns | Sheet |
| --- | --- | --- |
| `conditions()` | `Branch` | [08](08-branch-node.md) |
| `parallel()` / `parallel_conditions()` | `Flow` | [09](09-parallel-node.md) |
| `foreach(item_schema=...)` | `Flow` | [10](10-foreach-node.md) |
| `loop(evaluator=...)` | `Flow` | [11](11-loop-node.md) |
| `userflow()` | `UserFlow` | [14](14-user-node-fields.md) |

### Flow-level configuration

| Method | Sheet |
| --- | --- |
| `add_callback(tool, events, batch_interval=None)` | [21](21-callbacks.md) |
| `mask_property(path, policy, regex_config=None, input_policy=None)` | [22](22-masking.md) |
| `target_locales([...])` | [23](23-multi-language.md) |
| `map_output(output_variable, expression, default_value=None)` | [03](03-data-mapping.md) |

## Constants

| Constant | Meaning |
| --- | --- |
| `START` | Entry point. Exactly one per flow and per subflow. |
| `END` | Exit point. At least one per flow; may be several. |

Import from `ibm_watsonx_orchestrate.flow_builder.flows` or
`ibm_watsonx_orchestrate.flow_builder.flows.constants`.

## `edge(from_node, to_node, **kwargs)`

Connects two nodes. Returns the `Flow`, so calls chain.

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `from_node` | `Node` \| `START` | yes | Source. |
| `to_node` | `Node` \| `END` | yes | Target. |
| `id` | `str` | no | Names the edge. Required as the target of `error_edge_id`. See [20](20-error-handling.md). |
| `button_label` | `str` | no | Only for edges leaving a form node — binds a form button to this transition. See [15](15-user-node-forms.md). |

```py
aflow.edge(START, a).edge(a, b).edge(b, END)
aflow.edge(node, user_flow, id="tool_error_path")
user_flow.edge(form_node, next_node, button_label="Submit")
```

## `sequence(*nodes)`

Chains nodes with edges in order. Equivalent to consecutive `edge()` calls.

```py
aflow.sequence(START, a, b, END)          # == edge(START,a).edge(a,b).edge(b,END)
```

## Edge semantics

- A node with **one** outgoing edge → the successor runs next, sequentially.
- A node with **multiple** outgoing edges → all successors run **in parallel**.
- Exception: branch nodes (`conditions()`), which take only the first matching path.
- Container subflows merge at their internal `END`; the parent resumes only after every
  internal path reaches `END`.

## Async execution

Flows run asynchronously. Invoking a flow tool returns an **instance ID**; progress is
polled with the *Get agentic workflow status* tool using that ID.

## Compile / deploy / invoke (local scripting)

```py
definition = await build_my_flow().compile_deploy()
definition.dump_spec(f"{folder}/my_flow_spec.json")

run = await definition.invoke(
    {"field": "value"},
    on_flow_end_handler=handler,
    on_flow_error_handler=handler,
    debug=True,
)
```

| Member | Notes |
| --- | --- |
| `compile_deploy()` | Awaitable; returns the flow definition. |
| `dump_spec(path)` | Writes the JSON flow spec. |
| `invoke(payload, on_flow_end_handler=, on_flow_error_handler=, debug=)` | Awaitable run. |
| `definition.flow.spec.display_name` | Flow display name off the spec. |

See [24](24-cli-and-import.md) for importing into an environment.
