# watsonx Orchestrate Flow Builder — Reference Pack

Callable reference sheets for building agentic workflows programmatically with the
`ibm_watsonx_orchestrate.flow_builder` Python library.

Each sheet is self-contained: signature, parameters, return type, constraints, and the
minimum call form. Look up the node you need; do not read front-to-back.

## Sheets

| Sheet | Covers |
| --- | --- |
| [01-flow-and-edges.md](01-flow-and-edges.md) | `@flow` decorator, `Flow`, `edge()`, `sequence()`, `START`/`END`, compile/deploy |
| [02-expressions.md](02-expressions.md) | Expression grammar: `flow`, `parent`, `self`, loop cursors |
| [03-data-mapping.md](03-data-mapping.md) | `map_input()`, `map_output()`, `DataMap`, `Assignment`, auto-mapping + compression |
| [04-tool-node.md](04-tool-node.md) | `tool()` |
| [05-agent-node.md](05-agent-node.md) | `agent()` |
| [06-prompt-node.md](06-prompt-node.md) | `prompt()` — LLM generate/extract/classify |
| [07-script-node.md](07-script-node.md) | `script()` |
| [08-branch-node.md](08-branch-node.md) | `conditions()`, `condition()` — exclusive routing |
| [09-parallel-node.md](09-parallel-node.md) | `parallel()`, `parallel_conditions()` — concurrent routing |
| [10-foreach-node.md](10-foreach-node.md) | `foreach()`, `policy()` |
| [11-loop-node.md](11-loop-node.md) | `loop()` |
| [12-timer-node.md](12-timer-node.md) | `timer()` |
| [13-decisions-node.md](13-decisions-node.md) | `decisions()`, `DecisionsRule`, `DecisionsCondition`, `DecisionTableColumn` |
| [14-user-node-fields.md](14-user-node-fields.md) | `userflow()`, `field()`, `UserFieldKind` — multi-turn |
| [15-user-node-forms.md](15-user-node-forms.md) | `form()` and every form field constructor |
| [16-user-assignment.md](16-user-assignment.md) | `assign_to()`, `UserAssignmentPolicy`, `WXOUser` |
| [17-docproc-node.md](17-docproc-node.md) | `docproc()`, KVP schemas, output formats |
| [18-docext-node.md](18-docext-node.md) | `docext()`, `DocExtConfigField` |
| [19-docclassifier-node.md](19-docclassifier-node.md) | `docclassifier()`, `DocClassifierClass` |
| [20-error-handling.md](20-error-handling.md) | `NodeErrorHandlerConfig`, error edges |
| [21-callbacks.md](21-callbacks.md) | `add_callback()`, `FlowCallbackEventKind` |
| [22-masking.md](22-masking.md) | `mask_property()`, `MaskingPolicy`, `InputPolicy` |
| [23-multi-language.md](23-multi-language.md) | `target_locales()`, translation CSV round-trip |
| [24-cli-and-import.md](24-cli-and-import.md) | `orchestrate tools import`, testing, lifecycle |
| [25-node-selection-matrix.md](25-node-selection-matrix.md) | Which node/control structure to reach for |

## Model in one paragraph

A flow is a directed graph of **nodes** joined by **edges**. Exactly one `START`, at least
one `END`. A node factory method on the `Flow` object (`aflow.tool(...)`, `aflow.prompt(...)`)
both creates the node and registers it with the flow; you then wire it with `edge()` or
`sequence()`. Container nodes (`foreach`, `loop`, `parallel`, `userflow`) return a **subflow**
that is itself a `Flow` — you add nodes to the subflow and give the subflow its own
`START`/`END`, then wire the subflow into the parent as a single node. Flows run
asynchronously and return an instance ID.

## Import surface

```py
from ibm_watsonx_orchestrate.flow_builder.flows import (
    Flow, flow, START, END,
    Branch, UserNode, UserFlow, PromptNode, ScriptNode,
    DecisionsNode, DecisionsRule, DecisionsCondition,
)
from ibm_watsonx_orchestrate.flow_builder.types import (
    Assignment, UserFieldKind, UserFieldOption, UserAssignmentPolicy,
    ForeachPolicy, NodeErrorHandlerConfig, FlowCallback,
    DecisionTableColumn,
    DocProcInput, DocProcKVPSchema, DocProcKey, DocProcField, DocProcOutputFormat,
    TextExtractionResponse, TextExtractionObjectResponse,
    DocExtConfigField, DocExtInput, DocumentProcessingCommonInput,
    DocClassifierClass, DocumentClassificationResponse,
)
from ibm_watsonx_orchestrate.flow_builder.data_map import DataMap
from ibm_watsonx_orchestrate.flow_builder.masking_utils import MaskingPolicy, InputPolicy
from ibm_watsonx_orchestrate.flow_builder.flow_callback_types import FlowCallbackEventKind
from ibm_watsonx_orchestrate_core.types.tools.types import WXOUser
```

## Hard constraints

- Exactly one `START` per flow (and per subflow); at least one `END`.
- Nodes with multiple outgoing edges run **in parallel**, except branch nodes.
- Flow-as-callback-tool must contain no user activity nodes.
- Only `str` properties can be masked; flow **output** properties cannot be masked.
- `decision_table_columns` is required on `decisions()` for Builder UI integration.
- Do not loop a parallel branch back to an earlier node — unbounded thread creation.
- Human-in-the-loop review (`min_confidence`, `review_fields`, `enable_review`) only
  functions when the flow runs from a chat session.
