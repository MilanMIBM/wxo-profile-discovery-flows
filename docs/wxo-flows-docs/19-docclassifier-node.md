# Document classifier node — `docclassifier()`

Public preview. Classifies a document into one of a defined set of classes.

```py
node = aflow.docclassifier(name=..., classes=CustomClasses(), llm=...)
```

Returns a `DocClassifierNode`. Its output schema is `DocumentClassificationResponse`.

## Prerequisites

```bash
orchestrate server start -e <.env file path> -d
```

Docker engine needs ≥ 20 GB RAM. Define `WO_INSTANCE`, `WO_API_KEY`, and
`AUTHORIZATION_URL` in your `.env`.

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Unique node identifier. |
| `llm` | `str` | yes | LLM for classification. Default `watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8`. |
| `classes` | `object` | yes | Instance of your classes model. |
| `display_name` | `str` | no | UI name. |
| `description` | `str` | no | Node description. |
| `min_confidence` | `float` | no | Minimum confidence threshold. |
| `input_map` | `DataMap` | no | Structured input mapping. |
| `enable_review` | `bool` | no | Human-in-the-loop toggle. Default `False`. |

Input type: `DocumentProcessingCommonInput`.

## Defining classes

Each class is a `DocClassifierClass` field on a `BaseModel`.

### `DocClassifierClass`

| Param | Type | Notes |
| --- | --- | --- |
| `class_name` | `str` | The class label assigned to matching documents. |

```py
from ibm_watsonx_orchestrate.flow_builder.types import DocClassifierClass

class CustomClasses(BaseModel):
    invoice: DocClassifierClass = Field(default=DocClassifierClass(class_name="Invoice"))
    contract: DocClassifierClass = Field(default=DocClassifierClass(class_name="Contract"))
    tax_form: DocClassifierClass = Field(default=DocClassifierClass(class_name="TaxForm"))
    bill_of_lading: DocClassifierClass = Field(default=DocClassifierClass(class_name="BillOfLading"))
```

## Call form

```py
from ibm_watsonx_orchestrate.flow_builder.types import (
    DocumentProcessingCommonInput, DocumentClassificationResponse,
)

@flow(name="custom_flow_docclassifier_example", input_schema=DocumentProcessingCommonInput)
def build(aflow: Flow) -> Flow:
    node = aflow.docclassifier(
        name="document_classifier_node",
        description="Classifies documents into one custom class.",
        llm="watsonx/meta-llama/llama-4-maverick-17b-128e-instruct-fp8",
        classes=CustomClasses(),
    )
    aflow.sequence(START, node, END)
    return aflow
```

`classes=` takes an **instance** (`CustomClasses()`), not the class.

## Human-in-the-loop

`min_confidence` drives review: when a document classifies **below** the threshold, or as
`Other`, the agent opens a review window in chat for confirmation.

Only functions when the flow runs from a **chat session**.

## Downstream routing

Pair with a `conditions()` branch on the classification result to route per document type.
See [08-branch-node.md](08-branch-node.md).
