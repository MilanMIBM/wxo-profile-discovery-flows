# Expression grammar

Expressions are Python expressions evaluated by the flow engine. Used in: branch/parallel
conditions, loop evaluators, data-map `value_expression` / `expression`, prompt
`system_prompt` and `user_prompt` interpolation, decisions variable paths, masking paths,
and user-field `text`.

## Root keywords

| Keyword  | Refers to                                                           |
| -------- | ------------------------------------------------------------------- |
| `flow`   | Top-level flow context.                                             |
| `parent` | The parent context - the enclosing flow for nodes inside a subflow. |
| `self`   | The current node.                                                   |

## Reference patterns

| Pattern                                          | Meaning                                                                       |
| ------------------------------------------------ | ----------------------------------------------------------------------------- |
| `flow.input.<name>`                              | Flow input field.                                                             |
| `flow.output.<name>`                             | Flow output field.                                                            |
| `flow.private.<name>`                            | Flow private-state field (needs `private_schema`).                            |
| `flow.<nodeName>.output.<name>`                  | Output of a named node in the flow.                                           |
| `flow.<nodeName>.input.<name>`                   | Input of a named node.                                                        |
| `flow["<nodeName>"]["<field>"].output.value`     | Bracket form - required when a name has spaces.                               |
| `parent.[input\|output].<name>`                  | Input/output of the enclosing flow, from inside a subflow.                    |
| `parent.[input\|output]["<name>"]`               | Bracket form of the above.                                                    |
| `parent.<nodeName>.[input\|output].<name>`       | Another node in the enclosing flow.                                           |
| `parent["<nodeName>"].[input\|output]["<name>"]` | Bracket form.                                                                 |
| `self["input"].<name>`                           | Input of the current node.                                                    |
| `self.input.<name>`                              | Dot form. Data-map targets use e.g. `self.input.value`, `self.input.choices`. |

## Loop cursors

| Pattern                 | Meaning                                              |
| ----------------------- | ---------------------------------------------------- |
| `parent._current_index` | Current index in a `foreach`. `null` outside a loop. |
| `parent._current_item`  | Current item in a `foreach`. `null` outside a loop.  |

## Operators and forms

Standard Python expression syntax is available.

```py
"flow.input.priority == 'high'"
"flow.input.priority == 'high' and flow.input.value > 1000"
"flow.input.category == 'billing' or flow.input.category == 'finance'"
"flow.private.needs_approval is True"
"flow.input.amount > 5000"
"'urgent' in flow.input.tags"
"flow.input.kind.strip().lower() == 'dog'"
"not parent.get_status.input.attempt.atmp or parent.get_status.input.attempt.atmp < 5"
"flow.Classifier.output.justification if flow.Classifier.output.justification else \"N/A\""
```

String methods (`.strip()`, `.lower()`), conditional expressions, membership tests, and
boolean composition all evaluate.

## Literal values in data maps

`value_expression` takes an expression string, so literals must be written as literals
**within** that string:

```py
Assignment(target_variable="self.input.choices", value_expression='["dog", "cat", "bird"]')
Assignment(target_variable="self.input.min_date", value_expression='"2026-01-05"')
Assignment(target_variable="self.input.min_num_files", value_expression="1")
```

## Interpolation in text

User-field `text` and prompt bodies interpolate with braces:

```py
text="Display of first name is {flow.input.first_name}"
text="Welcome {flow.userflow_1[\"Last name\"].output.value}"
user_prompt=["Write a 2 sentence summary of: {text}"]
```

## Naming note

Auto-generated subflow names follow `userflow_1`, `userflow_2`, … Reference them by that
name, or set `spec.display_name` and reference fields by display name in bracket form.
