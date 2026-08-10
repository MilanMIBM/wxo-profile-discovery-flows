# Document processing node - `docproc()`

Public preview. Extracts text (and optionally semantic key-value pairs) from a document.

```py
from ibm_watsonx_orchestrate.flow_builder.types import DocProcInput, DocProcOutputFormat

node = aflow.docproc(name=..., task="text_extraction", ...)
```

## Prerequisites

```bash
orchestrate server start -e <.env file path> -d
```

Docker engine needs **≥ 20 GB RAM** for document processing.

## Parameters

| Param                   | Type                     | Req | Notes                                                                                                                 |
| ----------------------- | ------------------------ | --- | --------------------------------------------------------------------------------------------------------------------- |
| `name`                  | `str`                    | yes | Unique node identifier.                                                                                               |
| `task`                  | `str`                    | yes | `text_extraction` - extracts plain text.                                                                              |
| `display_name`          | `str`                    | no  | UI name.                                                                                                              |
| `description`           | `str`                    | no  | Node description.                                                                                                     |
| `output_format`         | `DocProcOutputFormat`    | no  | See below. Default `docref`.                                                                                          |
| `input_map`             | `DataMap`                | no  | Structured input mapping.                                                                                             |
| `document_structure`    | `bool`                   | no  | `true` adds document-assembly fields to the output.                                                                   |
| `kvp_schemas`           | `list[DocProcKVPSchema]` | no  | Schemas for key-value pair extraction.                                                                                |
| `enable_hw`             | `bool`                   | no  | `true` enables handwriting recognition.                                                                               |
| `kvp_model_name`        | `str`                    | no  | LLM for KVP extraction. Defaults to the WDU model, currently `watsonx/mistralai/mistral-small-3-1-24b-instruct-2503`. |
| `kvp_force_schema_name` | `str`                    | no  | Forces a schema by `document_type`. If unset/None, the engine matches the document against supplied schemas.          |
| `kvp_enable_text_hints` | `bool`                   | no  | Text hints to assist KVP extraction.                                                                                  |

Input type: `DocProcInput` from `ibm_watsonx_orchestrate.flow_builder.types`.

## `DocProcOutputFormat`

| Value                                  | Response type                  | Use when                                                                                   |
| -------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------ |
| `DocProcOutputFormat.docref` (default) | `TextExtractionResponse`       | Large or structurally complex documents. Returns a **URL reference** to the stored result. |
| `DocProcOutputFormat.object`           | `TextExtractionObjectResponse` | Small documents, or when output must feed a downstream node. Returns **inline JSON**.      |

With `object`, map all top-level fields of `TextExtractionObjectResponse` into downstream
inputs or the flow output.

## Minimum call form

```py
@flow(name="text_extraction_flow_example", input_schema=DocProcInput)
def build(aflow: Flow) -> Flow:
    node = aflow.docproc(name="text_extraction", task="text_extraction")
    aflow.sequence(START, node, END)
    return aflow
```

Output is a URL to a file holding the extracted text; with KVP configured, the file also
holds the extracted pairs.

## `kvp_model_name` compatibility

Must accept image input and respond in JSON, and must be registered in your environment.
Known-compatible:

- `watsonx/mistralai/mistral-small-3-1-24b-instruct-2503`
- `watsonx/mistralai/mistral-medium-2505`
- `watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8`

## KVP schemas

Definable in **two places**, with a precedence rule.

| Where                      | Behavior                                  |
| -------------------------- | ----------------------------------------- |
| Node spec (`kvp_schemas=`) | Used when the runtime input defines none. |
| Runtime input payload      | **Overrides** the node spec.              |

Default is `null` in both. An **empty array** `[]` falls back to the built-in predefined
schemas.

### `DocProcKVPSchema`

| Field                            | Type                      | Notes                                            |
| -------------------------------- | ------------------------- | ------------------------------------------------ |
| `document_type`                  | `str`                     | Schema name; matched by `kvp_force_schema_name`. |
| `document_description`           | `str`                     | What the document is.                            |
| `additional_prompt_instructions` | `str`                     | Extra extraction guidance.                       |
| `fields`                         | `dict[str, DocProcField]` | Fields to extract.                               |

### `DocProcField`

| Field         | Type  | Notes                                   |
| ------------- | ----- | --------------------------------------- |
| `description` | `str` | What the field is and where it appears. |
| `example`     | `str` | Example value.                          |
| `default`     | `str` | Value when absent.                      |

```py
from ibm_watsonx_orchestrate.flow_builder.types import DocProcKVPSchema, DocProcField

INVOICE_KVP_SCHEMA = DocProcKVPSchema(
    document_type="MyInvoice",
    document_description="A simple invoice document",
    fields={
        "invoice_number": DocProcField(
            description="The unique identifier for the invoice.",
            default="", example="INV-0001"),
        "total_amount": DocProcField(
            description="The total amount due on the invoice.",
            default="", example="1000.00"),
    },
)

node = aflow.docproc(
    name="text_extraction_node",
    task="text_extraction",
    output_format=DocProcOutputFormat.object,
    kvp_schemas=[INVOICE_KVP_SCHEMA],
    kvp_force_schema_name="MyInvoice",
    kvp_enable_text_hints=True,
)
```

Dict-literal form is also accepted for `kvp_schemas`.

## Explicit mapping

Map every KVP input explicitly so auto-mapping cannot override runtime values with a wrong
guess:

```py
node.map_input(input_variable="document_ref", expression="flow.input.document_ref")
node.map_input(input_variable="kvp_schemas", expression="flow.input.kvp_schemas")
node.map_input(input_variable="kvp_model_name", expression="flow.input.kvp_model_name")
node.map_input(input_variable="kvp_force_schema_name", expression="flow.input.kvp_force_schema_name")
node.map_input(input_variable="kvp_enable_text_hints", expression="flow.input.kvp_enable_text_hints")
```

## Runtime payload

```py
run = await definition.invoke({
    "document_ref": doc_ref,
    "language": "en",
    "kvp_schemas": [schema_json],
})
```

All `kvp_*` parameters are runtime-overridable, so one flow definition serves multiple
schema configurations without code changes.

## Extending the response type

```py
class TestFlowResultType(TextExtractionObjectResponse):
    summary_text: str = Field(description="Summary computed downstream", default="")
```
