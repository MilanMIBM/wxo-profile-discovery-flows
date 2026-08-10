# User activity - `userflow()` and `field()`

User activity nodes are interactive steps. Two styles:

- **Multi-turn** - `field()`, one piece of data per conversational turn. This sheet.
- **Form** - `form()`, many pieces in a single turn. See [15](15-user-node-forms.md).

Both live inside a `userflow()` subflow.

## `userflow()`

```py
from ibm_watsonx_orchestrate.flow_builder.flows.flow import UserFlow

user_flow: UserFlow = aflow.userflow()
user_flow.spec.display_name = "Application"
```

Returns a `UserFlow` (a subflow). Build it with its own `START`/`END`, then wire it into
the parent as one node.

| Member                  | Notes                                                                  |
| ----------------------- | ---------------------------------------------------------------------- |
| `field(...)`            | Add a multi-turn field node.                                           |
| `form(...)`             | Add a form node. See [15](15-user-node-forms.md).                      |
| `script(...)`           | Add a script node. See [07](07-script-node.md).                        |
| `edge()` / `sequence()` | Wire internal nodes.                                                   |
| `assign_to(...)`        | Route the activity to specific users. See [16](16-user-assignment.md). |
| `spec.display_name`     | UI name of the user flow.                                              |

## `field()`

| Param          | Type              | Req | Notes                                                         |
| -------------- | ----------------- | --- | ------------------------------------------------------------- |
| `name`         | `str`             | yes | Unique node identifier.                                       |
| `kind`         | `UserFieldKind`   | yes | Field type.                                                   |
| `direction`    | `str`             | yes | `"input"` (collect) or `"output"` (display).                  |
| `display_name` | `str`             | no  | UI name - this is what expressions reference in bracket form. |
| `description`  | `str`             | no  | Node description.                                             |
| `text`         | `str`             | no  | Displayed text; interpolates expressions in braces.           |
| `default`      | `Any`             | no  | Default value.                                                |
| `option`       | `UserFieldOption` | no  | Predefined options with labels and values.                    |
| `is_list`      | `bool`            | no  | Field accepts multiple values.                                |
| `min`          | `Any`             | no  | Minimum value/constraint.                                     |
| `max`          | `Any`             | no  | Maximum value/constraint.                                     |
| `input_map`    | `DataMap`         | no  | Structured input mapping. See [03](03-data-mapping.md).       |
| `custom`       | `dict`            | no  | Additional metadata/configuration.                            |

## `UserFieldKind`

`Text`, `Date`, `DateTime`, `Time`, `Number`, `File`, `Boolean`, `Object`, `Choice`, `List`.

## Call forms by kind

```py
from ibm_watsonx_orchestrate.flow_builder.types import UserFieldKind, Assignment
from ibm_watsonx_orchestrate.flow_builder.data_map import DataMap

# Text input
user_flow.field(direction="input", name="last_name",
                display_name="Last name", kind=UserFieldKind.Text)

# Number input
user_flow.field(direction="input", name="age",
                display_name="Age", kind=UserFieldKind.Number)

# File upload
user_flow.field(direction="input", name="upload",
                display_name="File upload 1", kind=UserFieldKind.File)

# Text display with interpolation
user_flow.field(direction="output", name="display_first_name",
                display_name="Display first name", kind=UserFieldKind.Text,
                text="Display of first name is {flow.input.first_name}")
```

### File download - value via `DataMap`

```py
dm = DataMap()
dm.add(Assignment(target_variable="self.input.value",
                  value_expression='flow["userflow_1"]["File upload 1"].output.value'))
user_flow.field(direction="output", name="download", display_name="Download file",
                kind=UserFieldKind.File, input_map=dm)
```

### List output - array literal

```py
dm = DataMap()
dm.add(Assignment(target_variable="self.input.value",
                  value_expression='["Alice", "Bob", "Charlie"]'))
user_flow.field(direction="output", name="Friends", display_name="List of friends",
                kind=UserFieldKind.List, input_map=dm)
```

### Choice input - options via `self.input.choices`

```py
dm = DataMap()
dm.add(Assignment(target_variable="self.input.choices",
                  value_expression='["dog", "cat", "bird", "fish"]'))
user_flow.field(direction="input", name="pet_choice", display_name="Select Your Pet",
                kind=UserFieldKind.Choice, text="Choose your favorite pet:", input_map=dm)
```

## Wiring

```py
user_flow.edge(START, node1)
user_flow.edge(node1, node2)
user_flow.edge(node2, END)

aflow.sequence(START, user_flow, END)
```

## Reading a field's value

A field's captured value lives at `.output.value` on the field node, addressed through the
user flow by **display name**:

```py
'flow["userflow_1"]["File upload 1"].output.value'
'{flow.userflow_1["Last name"].output.value}'
```

## Constraints

- A flow used as a **callback tool** must contain no user activity nodes. See [21](21-callbacks.md).
- User activity nodes support multi-language configuration. See [23](23-multi-language.md).
- Auto-generated user flow names are `userflow_1`, `userflow_2`, …
