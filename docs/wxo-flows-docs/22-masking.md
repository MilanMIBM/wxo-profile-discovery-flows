# Masking - `mask_property()`

Obscures sensitive strings in logs, UI, and outputs while keeping the value usable inside
the workflow.

```py
from ibm_watsonx_orchestrate.flow_builder.masking_utils import MaskingPolicy, InputPolicy

aflow.mask_property(property_path, masking_policy, regex_config=None, input_policy=None)
```

## Restrictions

- Only **STRING** properties can be masked. Arrays, objects, numbers, and booleans cannot.
- Flow **output** properties cannot be masked. Only flow input, flow private, and node
  output properties.

## Parameters

| Param            | Type            | Req   | Notes                              |
| ---------------- | --------------- | ----- | ---------------------------------- |
| `property_path`  | `str`           | yes   | Dot-notation path to the property. |
| `masking_policy` | `MaskingPolicy` | yes   | Strategy.                          |
| `regex_config`   | `dict`          | cond. | Required for `MASK_VIA_REGEX`.     |
| `input_policy`   | `InputPolicy`   | no    | Input-time behavior.               |

## `property_path` forms

| Path                                          | Targets                  |
| --------------------------------------------- | ------------------------ |
| `flow.input.<property>`                       | Flow input schema.       |
| `flow.private.<property>`                     | Flow private schema.     |
| `flow.<node_name>.output.<property>`          | Node output schema.      |
| `flow.<nested_flow>.<node>.output.<property>` | Nested flow node output. |
| `flow.input.user.email`                       | Nested property.         |

## `MaskingPolicy`

| Value            | Effect                                   | Example                                |
| ---------------- | ---------------------------------------- | -------------------------------------- |
| `MASK_ALL`       | Masks the entire value.                  | `123-45-6789` → `***********`          |
| `MASK_LAST4`     | Masks all but the last 4.                | `123-45-6789` → `*******6789`          |
| `MASK_FIRST4`    | Masks all but the first 4.               | `AUTH-TOKEN-12345` → `AUTH***********` |
| `MASK_VIA_REGEX` | Custom pattern. Requires `regex_config`. | see below                              |

## `regex_config`

| Key               | Type  | Req | Notes                                                                   |
| ----------------- | ----- | --- | ----------------------------------------------------------------------- |
| `text-pattern`    | `str` | yes | Regex matching the text to mask.                                        |
| `masking-pattern` | `str` | yes | Replacement. `$1`, `$2`, … refer to capture groups from `text-pattern`. |

```py
aflow.mask_property(
    "flow.input.credit_card",
    MaskingPolicy.MASK_VIA_REGEX,
    regex_config={
        "text-pattern": r"^(\d{4})-(\d{4})-(\d{4})-(\d{4})$",
        "masking-pattern": "XXXX-XXXX-XXXX-$4",
    },
)
# 1234-5678-9012-3456 -> XXXX-XXXX-XXXX-3456
```

## `InputPolicy`

| Value               | Effect                                |
| ------------------- | ------------------------------------- |
| `MASK_WHILE_TYPING` | Masks in real time as the user types. |

Omitted → the value is masked only on output, not during input.

## Call forms

```py
aflow.mask_property("flow.input.ssn", MaskingPolicy.MASK_ALL)
aflow.mask_property("flow.private.account.number", MaskingPolicy.MASK_LAST4)
aflow.mask_property("flow.get_token.output.token", MaskingPolicy.MASK_FIRST4)
aflow.mask_property("flow.input.pin", MaskingPolicy.MASK_ALL,
                    input_policy=InputPolicy.MASK_WHILE_TYPING)
```

Masking applies across node types - input schema fields, private variables (including
nested objects), script node outputs, user flow fields, tool inputs/outputs, OpenAPI tool
responses, and foreach loop data.

## Working around the output restriction

Since flow output cannot be masked directly, mask at the **source** - the node output or
private variable feeding it.
