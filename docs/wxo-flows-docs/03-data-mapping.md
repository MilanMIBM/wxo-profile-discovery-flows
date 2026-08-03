# Data mapping

Two mechanisms: per-node `map_input()` / `map_output()` calls, and `DataMap` objects passed
as an `input_map=` parameter. Expressions follow [02-expressions.md](02-expressions.md).

## Automatic mapping

If you supply no mapping, the flow engine maps data at runtime using an LLM. Large payloads
are automatically summarized first; without summarization auto-mapping exceeds token limits
and behaves unpredictably.

Explicit mapping overrides auto-mapping. Where correctness matters — notably docproc
outputs — map every field explicitly so automap cannot substitute a wrong guess.

### `FlowContextWindow`

Tunes the compression that protects auto-mapping.

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `compression_threshold` | `int \| None` | `None` | Compress once the context reaches this token count. |
| `compression_instruction` | `str \| None` | `None` | Use-case-specific summarization instruction. |
| `max_tokens` | `int \| None` | `None` | Max tokens the model supports. |
| `allow_compress` | `bool \| None` | `True` | Whether compression is permitted. |

## `node.map_input(input_variable, expression, default_value=None)`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `input_variable` | `str` | yes | Field on the node's input schema. |
| `expression` | `str` | yes | Source expression. |
| `default_value` | `str` | no | Fallback when the expression yields nothing. |

```py
node.map_input(input_variable="first_name", expression="flow.input.first_name")
node.map_input(input_variable="last_name", expression="flow.input.last_name",
               default_value="default_last_name")
node.map_input(input_variable="description",
               expression="flow.Load_Data_Node.output.extracted_kvps.Description")
```

## `flow.map_output(output_variable, expression, default_value=None)`

Same shape, applied to the flow's output schema.

```py
aflow.map_output(
    output_variable="Type_Justification",
    expression='flow.Classifier_Node.output.justification_text if flow.Classifier_Node.output.justification_text else "N/A"',
)
```

## `DataMap` + `Assignment`

The object form. Build a `DataMap`, add `Assignment`s, pass it as `input_map=` (or as a
form field's `default=` / `choices=` / `min_date=` / etc.).

```py
from ibm_watsonx_orchestrate.flow_builder.data_map import DataMap
from ibm_watsonx_orchestrate.flow_builder.types import Assignment

dm = DataMap()
dm.add(Assignment(target_variable="self.input.value", value_expression="flow.input.salary"))
node = user_flow.field(direction="output", name="x", kind=UserFieldKind.Text, input_map=dm)
```

### `Assignment`

| Param | Type | Notes |
| --- | --- | --- |
| `target_variable` | `str` | Destination, typically `self.input.<slot>`. |
| `value_expression` | `str` | Expression string; literals must be literal *inside* the string. |

### Common `target_variable` slots

| Slot | Used by |
| --- | --- |
| `self.input.value` | Field value, file download, `field_output_field`. |
| `self.input.choices` | Choice/list fields. |
| `self.input.default` | Any field's default. |
| `self.input.min_date` / `self.input.max_date` | Date fields. |
| `self.input.min_num_files` / `self.input.max_num_files` | File upload. |

## `input_map` parameter

Every node factory accepts `input_map: DataMap`. It is the object-form equivalent of a
series of `map_input()` calls, and is the only way to set defaults/constraints on form
fields that take a `DataMap` rather than a scalar.

## Schema contract

| Param | Role |
| --- | --- |
| `input_schema` | Structure and types the node expects. The contract for required/optional inputs. |
| `map_input` | Binds incoming data to the node's parameters, optionally transforming or defaulting. |
| `output_schema` | Structure and types the node returns. |
| `map_output` | Builds the final output object per the output schema. |
