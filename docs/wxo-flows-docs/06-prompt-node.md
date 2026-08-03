# Generative prompt node — `prompt()`

Public preview. Makes an LLM call to extract, classify, or generate. Returns a `PromptNode`.

```py
node = aflow.prompt(name=..., display_name=..., system_prompt=..., user_prompt=...,
                    prompt_examples=..., llm=..., llm_parameters=..., description=...,
                    input_schema=..., output_schema=..., input_map=...,
                    error_handler_config=...)
```

## Parameters

| Param | Type | Req | Notes |
| --- | --- | --- | --- |
| `name` | `str` | yes | Unique node identifier. |
| `display_name` | `str` | no | UI name. |
| `system_prompt` | `str \| list[str]` | no | Instructions governing LLM behavior. Supports expressions. |
| `user_prompt` | `str \| list[str]` | no | The request/task. Supports expressions. |
| `prompt_examples` | `list[PromptExample]` | no | Few-shot examples. |
| `llm` | `str` | no | Model id for generation. |
| `llm_parameters` | `PromptLLMParameters` \| `dict` | no | Decoding parameters. |
| `description` | `str` | no | Node description. |
| `input_schema` | `type[BaseModel]` | no | Input schema. |
| `output_schema` | `type[BaseModel]` | no | Output schema — the LLM is steered to fill it. |
| `input_map` | `DataMap` | no | Structured input mapping. See [03](03-data-mapping.md). |
| `error_handler_config` | `NodeErrorHandlerConfig` | no | See [20](20-error-handling.md). |

A `list[str]` for `system_prompt`/`user_prompt` is joined into one prompt — use it to keep
long instructions readable.

## `llm_parameters`

| Key | Type | Effect |
| --- | --- | --- |
| `temperature` | `float` | Randomness. Higher = more diverse. |
| `min_new_tokens` | `int` | Minimum tokens to generate. |
| `max_new_tokens` | `int` | Maximum tokens to generate. |
| `top_k` | `int` | Restrict selection to the k most likely tokens. |
| `top_p` | `float` | Nucleus sampling over cumulative probability p. |
| `stop_sequences` | `list[str]` | Sequences that halt generation. |

```py
llm_parameters={
    "temperature": 0,
    "min_new_tokens": 5,
    "max_new_tokens": 400,
    "top_k": 1,
    "stop_sequences": ["Human:", "AI:"],
}
```

## `prompt_examples` — `PromptExample`

| Field | Type | Notes |
| --- | --- | --- |
| `input` | `str` | Example input prompt. |
| `expected_output` | `str` | Expected output for that input. |
| `enabled` | `bool` | Toggle the example on/off. |

## Expression interpolation

Both prompt bodies interpolate flow expressions with braces:

```py
system_prompt=["You are a customer support processing assistant."]
user_prompt=["Here is the {message}"]
user_prompt=["Write a 2 sentence summary of: {text}"]
```

## Structured extraction pattern

Set `output_schema` to the target model; the node fills it from the prompt.

```py
node = aflow.prompt(
    name="extract_support_info",
    system_prompt=[
        "You are a customer support processing assistant, your job take the supplied support request received from email,",
        "and extract the information in the output as specified in the schema.",
    ],
    user_prompt=["Here is the {message}"],
    llm="meta-llama/llama-3-3-70b-instruct",
    llm_parameters={"temperature": 0, "max_new_tokens": 400, "top_k": 1},
    input_schema=Message,
    output_schema=SupportInformation,
)
```

## Retry

```py
error_handler_config={
    "error_message": "An error has occurred while invoking the LLM",
    "max_retries": 1,
    "retry_interval": 1000,
}
```
