# Script node — `script()` (a.k.a. logic block)

Runs inline Python in a **restricted** environment, then continues to the next downstream
node. Called a *script node* in the ADK, a *logic block* in the Builder UI — same node.

Execution is fast, predictable, and free of side effects.

```py
node = aflow.script(name=..., script=..., display_name=..., description=...,
                    error_handler=...)
```

### Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Node name. |
| `script` | `str` | yes | Python source, as a string. |
| `display_name` | `str` | no | UI name. |
| `description` | `str` | no | Node description. |
| `error_handler` | `NodeErrorHandlerConfig` | no | See [20](20-error-handling.md). |

Available on `Flow` and on every subflow (`parallel`, `foreach`, `loop`, `userflow`).

### Use it for

Initializing variables · transforming data · applying business logic · message formatting ·
file processing.

### Do NOT use it for

| Excluded | Use instead |
| --- | --- |
| Importing external Python libraries | a tool |
| Arbitrary or long-running logic | a tool |
| Calling external services or APIs | a tool |
| Reusable functions / shared libraries | a tool |
| Replacing a Python tool or microservice | a tool |

Logic blocks run **inline** in the workflow. Unrestricted Python would slow the workflow,
introduce security risks, and make workflows harder to debug and scale. If you need
external libraries, API calls, reusable logic, or long-running computation, use a tool.

---

## Runtime environment

### Available standard libraries

The list is **fixed and cannot be extended**. Some members within these modules may still
be unavailable.

`array` · `calendar` · `collections` · `datetime` · `enum` · `json` · `math` · `random` ·
`re` · `string` · `time` · `yaml` · `zoneinfo`

No `import` statement — these are pre-bound.

### Excluded functions and their replacements

| Not supported | Use instead |
| --- | --- |
| `eval(my_str)` | `(my_str == "True")` |
| `type()` | `safe_type()` |
| `import`, `class` | — (not available) |
| `str.format()`, `xxx.format()`, `xxx.format_map()` | f-strings |
| `string.Formatter.format()` | `string.safe_format()` |
| `yaml` — anything but the safe API | `safe_load()`, `safe_load_all()`, `safe_dump()`, `safe_dump_all()` |

f-strings work and are the idiomatic replacement for `.format()`:

```py
formatted_address = f"{addr['street']}, {addr['city']}, {addr['state']}"
```

---

## Reading and writing context

`flow`, `self`, and `parent` are **Python dictionaries**. Two equivalent access forms:

| Form | Notes |
| --- | --- |
| `flow["input"]["name"]` | Bracket — required when a key contains spaces or commas. |
| `flow.input.name` | Dot. |

Node and field names in the UI routinely contain spaces, so bracket form is unavoidable
when reaching into user activities:

```py
birthday_str = flow["User activity 1"]["Ask for date of birth"].output.value
```

### Shape of the dictionaries

```py
# flow — inputs and outputs of the outermost flow
flow = {
  "input": {
    "first_name": "John",
    "address": {"street": "123 ABC Street", "city": "NY", "state": "NY", "country": "USA"},
    "customer_status": "Bronze",
  },
  "output": {"age": <number>, "address": <str>},
}

# self — inputs and outputs of the current node
self = {
  "input": {"customer_status": "Bronze", "price": 1000},
  "output": {"discount_rate": <number>},
}
```

A script sets values by assignment; there is no return value.

```py
self.output.age = age
self["output"]["discount_rate"] = discount_rate
flow["input"]["address"]["state"] = address["state"]
```

### Initialize containers before writing into them

Assigning to `self["input"]["customer"]["discount_rate"]` throws if `"customer"` does not
exist yet. Initialize each containing object first. This is the most common script-node
exception.

Reading is safer with `.get()`:

```py
status = flow["input"].get("customer_status")
price = flow["input"].get("price", 0)
```

---

## Data types

| Flow type | Python | JSON |
| --- | --- | --- |
| Boolean | `bool` | Boolean |
| Date | `str` | String |
| Time | `str` | String |
| Date & time | `str` | String |
| Decimal | `float` | Number |
| File | `WxoFile` | String |
| Integer | `int` | Integer |
| Object | `dict` | Object |
| String | `str` | String |
| User | `str` | String |

Dates are **strings in ISO 8601** (`"%Y-%m-%d"`), both in Python and JSON. Object types
must follow the JSON Schema standard, with `"format": "date"` on date strings.

### Conversions

| From → To | Idiom |
| --- | --- |
| str → int | `int(my_str)` |
| str → float | `float(my_str)` |
| str → bool | `(my_str == "True")` — **not** `eval()` |
| str → date | `datetime.datetime.strptime(s, "%Y-%m-%d").date()` |
| int/float → str | `str(my_int)` |
| int → bool | `bool(my_int)` — `0` → `False`, `1` → `True` |
| float → int | `int(x)` truncates · `math.ceil(x)` · `math.floor(x)` |
| int/float → date | `datetime.date.fromordinal(int(x))` |
| date → str | `my_date.isoformat()` · `my_date.strftime("%a %d %B %Y")` |
| date → int/float | `my_date.toordinal()` |
| bool → str/int/float | `str(b)` · `int(b)` · `float(b)` |

Date arithmetic goes through `timedelta`:

```py
today = datetime.date.today()
three_days_ago = today - datetime.timedelta(days=3)
self.output.three_days_ago = three_days_ago.isoformat()
```

---

## `system` API

### `system.file` — file processing

Two interchangeable styles: module functions, or methods on the `WxoFile` object.

| Function | Method | Returns |
| --- | --- | --- |
| `system.file.get_name(f)` | `f.get_name()` | File name |
| `system.file.get_type(f)` | `f.get_type()` | File type |
| `system.file.get_size(f)` | `f.get_size()` | File size |
| `system.file.get_content(f)` | `f.get_content()` | Content as **bytes** |

#### Accessing files by source

| Source | Expression |
| --- | --- |
| Flow input | `flow.input.externalFile` |
| Form, single upload | `flow["User activity 1"]["Form 1"].output["single file upload"]` |
| Form, multiple uploads | `flow["User activity 1"]["Form 1"].output["Multi file upload"]` |
| Non-form file field | `flow["User activity 1"]["File upload 1"].output.value` |

**Single uploads are accessed directly, without an index. Multiple uploads require
indexing** — `[0]`, `[1]` — to reference each file.

```py
# Single
f = flow.input.externalFile
self.output.file_name = f.get_name()

# Multiple
files = flow["User activity 1"]["Form 1"].output["Multi file upload"]
self.output.file_count = len(files)
self.output.first_file_name = system.file.get_name(files[0])
```

### `system.user` — user lookup

Search methods each return a **list** of matching users; index it.

| Method | Finds by |
| --- | --- |
| `system.user.search_by_name(name)` | Name |
| `system.user.search_by_email(email)` | Email |
| `system.user.search_by_id(id)` | ID |

Attribute access, again in two interchangeable styles:

| Function | Method | Returns |
| --- | --- | --- |
| `system.user.get_name(u)` | `u.get_name()` | Name |
| `system.user.get_email(u)` | `u.get_email()` | Email |
| `system.user.get_id(u)` | `u.get_id()` | ID |

```py
user = system.user.search_by_email("user1@ibm.com")[0]
self.output.user_name = user.get_name()
self.output.user_email = user.get_email()
```

Feeding a `WXOUser` into user assignment: see [16](16-user-assignment.md).

### `system.context` — workflow-scoped variables

Shared data points that **persist for the entire workflow run**. Set one early (in a logic
block) and it stays available throughout.

| Method | Params | Notes |
| --- | --- | --- |
| `system.context.get_variable(variable_name)` | variable key | Retrieves by name. |
| `system.context.set_variable(variable_name, variable_value)` | key, value | Stores a value. |

```py
system.context.set_variable('order_stage', "validated")
stage = system.context.get_variable("order_stage")
```

#### Predefined context variables

Always available — no `set_variable` needed. Read with `get_variable` anywhere in the flow.

| Variable |
| --- |
| `wxo_email_id` |
| `wxo_tenant_id` |
| `wxo_user_name` |

---

## Call forms

```py
# Initialize private state
init = aflow.script(name="init_state", script="""
flow.private.design_needed = flow.input.design_needed
flow.private.phases_completed = []
""")

# Format a message
fmt = aflow.script(name="format_address", script="""
addr = flow["input"]["address"]
self["output"]["address"] = f"{addr['street']}, {addr['city']}, {addr['state']}, {addr['country']}"
""")

# Business rule
rule = aflow.script(name="check_payment", script="""
product = flow.input.product
age = flow.input.age
if product == "Alcohol" and age < 18:
    self.output.accept_payment = False
elif product == "Fireworks" and age < 18:
    self.output.accept_payment = False
else:
    self.output.accept_payment = True
""")

# Derive from a user activity value
age_node = aflow.script(name="calc_age", script="""
today = datetime.date.today()
birthday_str = flow["User activity 1"]["Ask for date of birth"].output.value
birthday = datetime.datetime.strptime(birthday_str, "%Y-%m-%d").date()
self.output.age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
""")
```

### Aggregation after parallel

A script placed after a parallel subflow runs only once every branch has reached the
subflow's `END`.

```py
aggregate = aflow.script(name="aggregate_results", script="""
flow.output.combined_results = [...]
""")
aflow.sequence(START, parallel_flow, aggregate, END)
```
