# Node selection matrix

## By intent

| I need to…                                | Use                        | Sheet                          |
| ----------------------------------------- | -------------------------- | ------------------------------ |
| Call an imported tool                     | `tool()`                   | [04](04-tool-node.md)          |
| Delegate an open-ended task to an agent   | `agent()`                  | [05](05-agent-node.md)         |
| Extract / classify / generate with an LLM | `prompt()`                 | [06](06-prompt-node.md)        |
| Transform data or set state inline        | `script()`                 | [07](07-script-node.md)        |
| Take exactly one of N paths               | `conditions()`             | [08](08-branch-node.md)        |
| Run every path                            | `parallel(evaluator=None)` | [09](09-parallel-node.md)      |
| Run every *matching* path                 | `parallel_conditions()`    | [09](09-parallel-node.md)      |
| Repeat per item in a list                 | `foreach()`                | [10](10-foreach-node.md)       |
| Repeat while a condition holds            | `loop()`                   | [11](11-loop-node.md)          |
| Wait / back off                           | `timer()`                  | [12](12-timer-node.md)         |
| Apply a rule table                        | `decisions()`              | [13](13-decisions-node.md)     |
| Ask the user for one thing at a time      | `userflow()` + `field()`   | [14](14-user-node-fields.md)   |
| Ask the user for many things at once      | `userflow()` + `form()`    | [15](15-user-node-forms.md)    |
| Send an activity to a specific person     | `assign_to()`              | [16](16-user-assignment.md)    |
| Get text/KVPs out of a document           | `docproc()`                | [17](17-docproc-node.md)       |
| Get named fields out of a document        | `docext()`                 | [18](18-docext-node.md)        |
| Identify a document's type                | `docclassifier()`          | [19](19-docclassifier-node.md) |
| React to a node failure                   | `NodeErrorHandlerConfig`   | [20](20-error-handling.md)     |
| React to flow lifecycle events            | `add_callback()`           | [21](21-callbacks.md)          |
| Hide sensitive strings                    | `mask_property()`          | [22](22-masking.md)            |
| Serve users in several languages          | `target_locales()`         | [23](23-multi-language.md)     |

## Routing: three ways to fork

|             | `conditions()`        | `parallel_conditions()` | `parallel()`         |
| ----------- | --------------------- | ----------------------- | -------------------- |
| Paths taken | First match only      | All matches             | All, unconditionally |
| Evaluation  | Sequential, if-else   | Concurrent              | None                 |
| Downstream  | Single path continues | Waits for all           | Waits for all        |
| Returns     | `Branch`              | `Flow` (subflow)        | `Flow` (subflow)     |

## Iteration: two ways to repeat

|                 | `foreach()`                               | `loop()`                  |
| --------------- | ----------------------------------------- | ------------------------- |
| Driven by       | A list (`item_schema`)                    | A condition (`evaluator`) |
| Terminates when | List exhausted                            | Evaluator false           |
| Concurrency     | `SEQUENTIAL` \| `PARALLEL`                | Sequential                |
| Cursors         | `parent._current_item` / `_current_index` | -                         |

## Logic: `decisions()` vs `conditions()` vs `script()`

|                   | `decisions()`                                                                    | `conditions()`        | `script()`                    |
| ----------------- | -------------------------------------------------------------------------------- | --------------------- | ----------------------------- |
| Shape             | Rule table → values                                                              | Condition → next node | Arbitrary Python              |
| Result            | Sets output variables                                                            | Routes execution      | Sets variables                |
| Reach for it when | Many rules over the same variables; business-owned; generated from a spreadsheet | Control flow forks    | Logic is procedural and small |

## Structural rules

- Exactly one `START` per flow and per subflow; at least one `END`.
- One outgoing edge → sequential. Multiple → parallel. Branch nodes are the exception.
- Subflows (`foreach`, `loop`, `parallel*`, `userflow`) are built internally with their own
  `START`/`END`, then wired into the parent as a single node.
- Parallel/foreach subflows merge at their internal `END`; the parent waits.
- Never edge a parallel branch back to an earlier node - unbounded threads.

## Return-shape gotchas

| Call                                                                 | Returns                                                     |
| -------------------------------------------------------------------- | ----------------------------------------------------------- |
| `aflow.docext(...)`                                                  | **2-tuple**: `(node, ExtractedValuesSchema)`                |
| `aflow.conditions()`                                                 | `Branch` - wired via `condition(to_node=...)`, not `edge()` |
| `aflow.foreach(...)` / `loop(...)` / `parallel*(...)` / `userflow()` | A `Flow`/`UserFlow` subflow, not a plain node               |
| `aflow.add_callback(...)`                                            | `Self` - chainable                                          |
| `edge()` / `sequence()` / `condition()` / `map_input()`              | Chainable                                                   |
| `foreach().policy(...)`                                              | Chains off `foreach()`                                      |

## Constructor-instance gotchas

`fields=Fields()` and `classes=CustomClasses()` take **instances**, not classes.

## Where chat is required

Human-in-the-loop review (`min_confidence`, `review_fields`, `enable_review` on `docext` /
`docclassifier`) only functions when the flow runs from a chat session.

## Where user activities are forbidden

A flow used as a **callback tool** must contain no user activity nodes. See
[21](21-callbacks.md).
