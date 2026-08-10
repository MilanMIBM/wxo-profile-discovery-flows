# Decisions node - `decisions()`

Public preview. Executes a decision table: an ordered set of rules. Rules are evaluated
top-to-bottom; the **first** rule whose conditions all pass supplies the result.

```py
from ibm_watsonx_orchestrate.flow_builder.flows import (
    DecisionsNode, DecisionsRule, DecisionsCondition,
)
from ibm_watsonx_orchestrate.flow_builder.types import DecisionTableColumn

node = aflow.decisions(name=..., rules=..., decision_table_columns=...,
                       default_actions=..., display_name=..., description=..., locale=...)
```

## `decisions()` parameters

| Param                    | Type                        | Req | Notes                                                          |
| ------------------------ | --------------------------- | --- | -------------------------------------------------------------- |
| `name`                   | `str`                       | yes | Node name.                                                     |
| `rules`                  | `list[DecisionsRule]`       | yes | Ordered rules.                                                 |
| `decision_table_columns` | `list[DecisionTableColumn]` | yes | **Required** for Builder UI integration.                       |
| `default_actions`        | `dict[str, Any]`            | no  | Result when no rule matches.                                   |
| `display_name`           | `str`                       | no  | UI name.                                                       |
| `description`            | `str`                       | no  | Node description.                                              |
| `locale`                 | `str`                       | no  | e.g. `en-US`, `fr-FR`, `es-MX`. Affects **date parsing only**. |

## `DecisionsRule`

A rule = conditions + actions. Both methods chain.

```py
rule = DecisionsRule()
rule.condition("flow.input.grade", DecisionsCondition().equal("A")) \
    .condition("flow.input.loan_amount", DecisionsCondition().less_than(100000))
rule.action("flow.output.insurance_required", True) \
    .action("flow.output.insurance_rate", 0.001)
```

### `condition(variable, DecisionsCondition)`

`variable` is a fully-qualified path:

| Path                      | Refers to                           |
| ------------------------- | ----------------------------------- |
| `flow.input.<name>`       | Flow input.                         |
| `flow.private.<name>`     | Flow private variable.              |
| upstream node output path | Output emitted by an upstream node. |

### `action(variable, value)`

`variable` is `flow.output.<name>`, or any other flow variable such as
`flow.private.<name>`. `value` is a literal.

## `DecisionsCondition` methods

| Method                                              | Applies to           |
| --------------------------------------------------- | -------------------- |
| `.equal(v)`                                         | number, date, string |
| `.not_equal(v)`                                     | number, date, string |
| `.greater_than(v)`                                  | number, date         |
| `.greater_than_or_equal(v)`                         | number, date         |
| `.less_than(v)`                                     | number, date         |
| `.less_than_or_equal(v)`                            | number, date         |
| `.in_range(min, max, min_inclusive, max_inclusive)` | number, date         |
| `.contains(v)`                                      | string               |
| `.does_not_contain(v)`                              | string               |
| `.starts_with(v)`                                   | string               |
| `.ends_with(v)`                                     | string               |

```py
# 0 inclusive to 50 exclusive
rule.condition("flow.input.revenue_quote_ratio",
               DecisionsCondition().in_range(0, 50, True, False))
```

### Underlying operators

`==`, `!=`, `>`, `>=`, `<`, `<=`, `contains`, `doesNotContain`, `startsWith`, `endsWith`.

Range notation: `"min:max"` bounded by `( )` exclusive or `[ ]` inclusive, mixable -
`[0:50)`.

## Supported condition types

| Type       | Notes                                                                                                                                                                            |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `number`   | Integer or float.                                                                                                                                                                |
| `string`   | Text.                                                                                                                                                                            |
| `boolean`  | `true` / `false`.                                                                                                                                                                |
| `date`     | Locale-sensitive. Accepts `3/14/2020`, `March 25, 2025`, `2020-10-20`. Default format `YYYY-MM-DD`. Full list: [any-date-parser](https://www.npmjs.com/package/any-date-parser). |
| `time`     | Time of day, e.g. `14:30:00`.                                                                                                                                                    |
| `datetime` | e.g. `2025-07-31T14:30:00`.                                                                                                                                                      |

## Supported action types

| Type      | Notes                                |
| --------- | ------------------------------------ |
| `number`  | Integer or float.                    |
| `string`  | Text.                                |
| `boolean` | True/False.                          |
| `date`    | Auto-formatted as "Month Day, Year". |

## `DecisionTableColumn`

Maps technical variable names to display names in the Builder UI. Cover both condition and
action variables.

| Param          | Type  | Notes                 |
| -------------- | ----- | --------------------- |
| `variable`     | `str` | Fully-qualified path. |
| `display_name` | `str` | UI label.             |

```py
decision_table_columns=[
    DecisionTableColumn(variable="flow.input.grade", display_name="Credit Grade"),
    DecisionTableColumn(variable="flow.output.insurance_rate", display_name="Insurance Rate"),
]
```

## `default_actions`

A dict of variable path → value, applied when no rule matches.

```py
default_actions={
    "flow.output.assessment_error": "Not assessed. Incorrect data submitted."
}
```

## Assembly

```py
rules = []
r1 = DecisionsRule()
r1.condition("flow.input.grade", DecisionsCondition().equal("A"))
r1.action("flow.output.insurance_required", False)
rules.append(r1)
# ... build the rest programmatically, e.g. from a CSV or spreadsheet

node = aflow.decisions(
    name="assess_insurance_rate",
    rules=rules,
    default_actions={...},
    decision_table_columns=[...],
)
aflow.sequence(START, node, END)
```

Rules are ordinary Python objects - generate them in a loop from external data rather than
writing each by hand.
