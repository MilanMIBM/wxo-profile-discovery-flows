# Foreach node - `foreach()`

A nested subflow repeated once per item in a list. Returns a `Flow`.

```py
foreach_flow: Flow = aflow.foreach(item_schema=ItemModel)
```

## Parameters

| Param           | Type        | Req | Notes                               |
| --------------- | ----------- | --- | ----------------------------------- |
| `item_schema`   | `BaseModel` | yes | Schema of each item iterated over.  |
| `input_schema`  | `BaseModel` | no  | Input schema of the nested subflow. |
| `output_schema` | `BaseModel` | no  | **Deprecated.**                     |

## Call form

Build the subflow with its own `START`/`END`, then wire the subflow into the parent as one
node.

```py
list_node = aflow.tool(get_emails_from_customer)

foreach_flow: Flow = aflow.foreach(item_schema=CustomerRecord)
send_node = foreach_flow.tool(send_invitation_email)
foreach_flow.sequence(START, send_node, END)

aflow.edge(START, list_node)
aflow.edge(list_node, foreach_flow)
aflow.edge(foreach_flow, END)
```

More than one node may live in the foreach subflow.

## `policy(kind)`

Sets the processing method. Chains off `foreach()`.

| Param  | Type            | Req | Notes                                                   |
| ------ | --------------- | --- | ------------------------------------------------------- |
| `kind` | `ForeachPolicy` | yes | `ForeachPolicy.SEQUENTIAL` or `ForeachPolicy.PARALLEL`. |

```py
from ibm_watsonx_orchestrate.flow_builder.types import ForeachPolicy

foreach_flow: Flow = aflow.foreach(item_schema=CustomerRecord) \
    .policy(kind=ForeachPolicy.SEQUENTIAL)
```

| Policy       | Behavior                                                     | When                                    |
| ------------ | ------------------------------------------------------------ | --------------------------------------- |
| `SEQUENTIAL` | One item at a time; next starts after the previous finishes. | Order of processing affects the result. |
| `PARALLEL`   | Multiple items at once. Usually faster.                      | Items are independent.                  |

## Loop cursors

Inside the subflow, reference the iteration position with:

| Expression              | Value                                 |
| ----------------------- | ------------------------------------- |
| `parent._current_item`  | Current item. `null` outside a loop.  |
| `parent._current_index` | Current index. `null` outside a loop. |

See [02-expressions.md](02-expressions.md).
