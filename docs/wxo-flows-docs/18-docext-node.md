# Document extractor node - `docext()`

Public preview. Extracts named fields from a document.

```py
node, ExtractedValues = aflow.docext(name=..., fields=Fields(), llm=...)
```

**Returns a 2-tuple**: the node, and the generated output schema class for the extracted
values. Use the returned schema as the `input_schema` of downstream nodes.

## Prerequisites

```bash
orchestrate server start -e <.env file path> -d
```

Docker engine needs ≥ 20 GB RAM. Define `WO_INSTANCE`, `WO_API_KEY`, and
`AUTHORIZATION_URL` in your `.env`.

## Parameters

| Param                     | Type        | Req | Notes                                                                                             |
| ------------------------- | ----------- | --- | ------------------------------------------------------------------------------------------------- |
| `name`                    | `str`       | yes | Unique node identifier.                                                                           |
| `llm`                     | `str`       | yes | LLM for field extraction. Default `watsonx/mistralai/mistral-small-3-1-24b-instruct-2503`.        |
| `fields`                  | `object`    | yes | Instance of your fields model.                                                                    |
| `display_name`            | `str`       | no  | UI name.                                                                                          |
| `description`             | `str`       | no  | Node description.                                                                                 |
| `input_map`               | `DataMap`   | no  | Structured input mapping.                                                                         |
| `enable_hw`               | `bool`      | no  | `true` enables handwriting recognition.                                                           |
| `min_confidence`          | `float`     | no  | Minimum acceptable confidence for an extracted value.                                             |
| `review_fields`           | `List[str]` | no  | Fields requiring user review.                                                                     |
| `enable_review`           | `bool`      | no  | Human-in-the-loop toggle. Default `False`.                                                        |
| `field_extraction_method` | `str`       | no  | `classic` (default, Unstructured Document Extractor) or `layout` (Structured Document Extractor). |

Input type: `DocExtInput` (or `DocumentProcessingCommonInput`) from
`ibm_watsonx_orchestrate.flow_builder.types`.

## Defining fields

Each field is a `DocExtConfigField` on a `BaseModel`, following this shape:

```py
field: DocExtConfigField = Field(
    name="Field name",
    default=DocExtConfigField(name="Field name", field_name="field_name"),
)
```

### `DocExtConfigField`

| Param         | Type  | Notes                                          |
| ------------- | ----- | ---------------------------------------------- |
| `name`        | `str` | Human-readable field name.                     |
| `field_name`  | `str` | Machine name; the key in the extracted output. |
| `type`        | `str` | e.g. `string`, `date`.                         |
| `description` | `str` | Guides the LLM on what to extract.             |

```py
from ibm_watsonx_orchestrate.flow_builder.types import DocExtConfigField

class Fields(BaseModel):
    buyer: DocExtConfigField = Field(
        name="Buyer",
        default=DocExtConfigField(name="Buyer", field_name="buyer"),
    )
    agreement_date: DocExtConfigField = Field(
        name="Agreement date",
        default=DocExtConfigField(name="Agreement Date", field_name="agreement_date", type="date"),
    )
    contract_type: DocExtConfigField = Field(
        name="Contract type",
        default=DocExtConfigField(
            name="Contract Type", field_name="contract_type", type="string",
            description="The type of contract between the buyer and the seller."),
    )
```

## Call form

```py
from ibm_watsonx_orchestrate.flow_builder.types import DocumentProcessingCommonInput

@flow(name="custom_flow_docext_example", input_schema=DocumentProcessingCommonInput)
def build(aflow: Flow) -> Flow:
    doc_ext_node, _ExtractedValues = aflow.docext(
        name="contract_extractor",
        display_name="Extract fields from a contract",
        description="Extracts fields from an input contract file",
        llm="watsonx/mistralai/mistral-small-3-1-24b-instruct-2503",
        fields=Fields(),
    )
    aflow.sequence(START, doc_ext_node, END)
    return aflow
```

`fields=` takes an **instance** (`Fields()`), not the class.

## Human-in-the-loop

`min_confidence` and `review_fields` drive review together: when a field extracts below
`min_confidence` **and** its name is in `review_fields`, the agent opens a review window in
chat for confirmation.

This only works when the flow runs from a **chat session**.

## Extraction runtime

| `field_extraction_method` | Runtime                          |
| ------------------------- | -------------------------------- |
| `classic` (default)       | Unstructured Document Extractor. |
| `layout`                  | Structured Document Extractor.   |
