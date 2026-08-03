# User activity — `form()` and form fields

Collects several pieces of data in one conversational turn. Created on a `userflow()`
subflow; see [14](14-user-node-fields.md).

```py
user_flow = aflow.userflow()
form = user_flow.form(name="ApplicationForm", display_name="Application",
                      instructions=..., submit_button_label=..., cancel_button_label=...)
```

### `form()` parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal form name. |
| `display_name` | `str` | no | Name shown on the form. |
| `instructions` | `str` | no | Instructions text. |
| `submit_button_label` | `str` | no | Defaults to `Submit`. |
| `cancel_button_label` | `str` | no | `None` hides the button. |

### Wiring form buttons

An edge leaving a form node carries `button_label` to bind a specific button to that
transition.

```py
user_flow.edge(START, feedback_form)
user_flow.edge(feedback_form, confirmation_node, button_label="Submit")
user_flow.edge(confirmation_node, END)
```

### `DataMap` parameters

Many field parameters take a `DataMap` rather than a scalar — `default`, `choices`,
`min_date`, `minimum`, `min_num_files`, `value`. Build one per parameter:

```py
dm = DataMap()
dm.add(Assignment(target_variable="self.input.default", value_expression="flow.input.salary"))
form.number_input_field(name="salary", label="Desired salary", default=dm)
```

Target slots: `self.input.default`, `self.input.choices`, `self.input.value`,
`self.input.min_date`, `self.input.max_date`, `self.input.min_num_files`,
`self.input.max_num_files`. See [03](03-data-mapping.md).

---

## Input fields

### `text_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `single_line` | `bool` | no | Default `True`. `False` → multi-line text area. |
| `placeholder_text` | `str` | no | Placeholder. |
| `help_text` | `str` | no | Help text. |
| `default` | `Any` | no | Default value, as `DataMap`. |
| `regex` | `str` | no | Validation pattern. |
| `regex_error_message` | `str` | no | Defaults to "Input does not match the required pattern". |

### `number_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `is_integer` | `bool` | no | Default `True`. `False` → decimals. |
| `help_text` | `str` | no | Help text. |
| `default` | `Any` | no | As `DataMap`. |
| `minimum` | `Any` | no | As `DataMap`. |
| `maximum` | `Any` | no | As `DataMap`. |

### `boolean_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `single_checkbox` | `bool` | no | Default `True`. `False` → radio buttons. |
| `default` | `Any` | no | As `input_map`. |
| `true_label` | `str` | no | Defaults to `True`. |
| `false_label` | `str` | no | Defaults to `False`. |

### `date_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `default` | `Any` | no | As `DataMap`. |
| `min_date` | `Any` | no | Minimum of allowed range. |
| `max_date` | `Any` | no | Maximum of allowed range. |
| `multiple_dates` | `bool` | no | Default `False`. |

### `date_range_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `start_date_label` | `str` | no | Label for start date. |
| `end_date_label` | `str` | no | Label for end date. |
| `default_start` | `Any` | no | As `DataMap`. |
| `default_end` | `Any` | no | As `DataMap`. |
| `min_date` | `Any` | no | `DataMap` mapping to `self.input.min_date`. |
| `max_date` | `Any` | no | `DataMap` mapping to `self.input.max_date`. |

### `datetime_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `default` | `Any` | no | Through a `DataMap`. |
| `min_time` | `Any` | no | Minimum datetime/time. |
| `max_time` | `Any` | no | Maximum datetime/time. |
| `inputType` | `UserFieldKind` | no | `DateTime` or `Time`. Defaults to `DateTime`. |

### `datetime_range_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `start_date_label` | `str` | no | Label for start value. |
| `end_date_label` | `str` | no | Label for end value. |
| `default_start` | `Any` | no | Through a `DataMap`. |
| `default_end` | `Any` | no | Through a `DataMap`. |
| `min_time` | `Any` | no | Minimum of range. |
| `max_time` | `Any` | no | Maximum of range. |

### `single_choice_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `choices` | `Any` | no | Available choices, as `DataMap`. |
| `show_as_dropdown` | `bool` | no | Default `True`. `False` → radio buttons. |
| `dropdown_item_column` | `str` | no | Column used for dropdown display text. |
| `placeholder_text` | `str` | no | Dropdown placeholder. |
| `default` | `Any` | no | Default selection, as `DataMap`. |
| `columns` | `dict[str, str]` | no | Source property → display label, for complex choice objects. |

### `multi_choice_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `choices` | `Any` | no | Available choices, as `DataMap`. |
| `show_as_dropdown` | `bool` | no | Default `True`. `False` → checkboxes. |
| `dropdown_item_column` | `str` | no | Column for dropdown display text. |
| `placeholder_text` | `str` | no | Dropdown placeholder. |
| `default` | `Any` | no | Default selections, as `DataMap`. |
| `columns` | `dict[str, str]` | no | Source property → display label. |
| `minItems` | `Any` | no | Minimum selections. |
| `maxItems` | `Any` | no | Maximum selections. |

### `file_upload_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `instructions` | `str` | no | Upload instructions. |
| `required` | `bool` | no | Default `False`. |
| `allow_multiple_files` | `bool` | no | Default `False`. |
| `file_max_size` | `int` | no | Max size in MB. Default `10`. |
| `supported_file_types` | `List[str]` | no | Extensions, e.g. `pdf`, `docx`. |
| `min_num_files` | `Any` | no | Only when `allow_multiple_files=True`. |
| `max_num_files` | `Any` | no | Only when `allow_multiple_files=True`. |

### `list_input_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `isRowAddable` | `bool` | no | User can add rows. |
| `isRowDeletable` | `bool` | no | User can delete rows. |
| `default` | `Any` | no | Items to display, in a `DataMap`. |
| `columns` | `dict[str, str]` | no | Source property → column label. Only listed columns appear. |

### `user_input_field()`

Selects people from the tenant.

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `required` | `bool` | no | Default `False`. |
| `multiple_users` | `bool` | no | Default `False`. |
| `min_num_users` | `Any` | no | Only when `multiple_users=True`. Integer or `DataMap`. |
| `max_num_users` | `Any` | no | Only when `multiple_users=True`. Integer or `DataMap`. |

---

## Output fields

### `message_output_field()`

Static text.

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `message` | `str` | no | Text to display. |

### `field_output_field()`

Dynamic value.

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `value` | `Any` | no | Value to display, as `DataMap`. |

### `list_output_field()`

Tabular data.

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `choices` | `Any` | no | Items to display, as `DataMap`. |
| `columns` | `dict[str, str]` | no | Source property → column label. Only listed columns appear. |

### `file_download_field()`

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Internal field name. |
| `label` | `str` | no | Display label. |
| `value` | `Any` | no | File to download, as `DataMap`. |

---

### Call forms

```py
# Choices sourced from flow input
dm = DataMap()
dm.add(Assignment(target_variable="self.input.choices", value_expression="flow.input.salutations"))
form.single_choice_input_field(name="salutation", label="Salutation", required=True,
                               choices=dm, show_as_dropdown=True,
                               placeholder_text="Please enter your title")

# Regex-validated text
form.text_input_field(name="lastName", label="Last name", required=True,
                      regex=r"^[a-zA-Z0-9\s]+$",
                      regex_error_message="No special characters allowed")

# Bounded file upload
dm_min = DataMap(); dm_min.add(Assignment(target_variable="self.input.min_num_files", value_expression="1"))
dm_max = DataMap(); dm_max.add(Assignment(target_variable="self.input.max_num_files", value_expression="2"))
form.file_upload_field(name="credentials", label="Upload credentials",
                       allow_multiple_files=True, file_max_size=256,
                       min_num_files=dm_min, max_num_files=dm_max)

# Date with literal bounds — note literals are quoted inside the expression
dm_min_date = DataMap()
dm_min_date.add(Assignment(target_variable="self.input.min_date", value_expression='"2026-01-05"'))
form.date_input_field(name="endDate", label="End Date", required=True, min_date=dm_min_date)

# Table of objects, selected columns only
dm_friends = DataMap()
dm_friends.add(Assignment(target_variable="self.input.choices",
                          value_expression="flow.input.friends.listOfNames"))
form.list_output_field(name="friends", label="Friends", choices=dm_friends,
                       columns={"first_name": "First", "last_name": "Last"})
```
