from ibm_watsonx_orchestrate.flow_builder.utils import dereference_refs


def clean_schema(model, response=False):
    """Pydantic -> the flat schema dialect the flow runtime validates against.

    The deployed inspector rejects `title`, `anyOf` and `additionalProperties`,
    and requires an explicit `type` everywhere, `properties` on every object
    and `items` on every array. Pydantic emits all three rejected keywords for
    Optional[...], dict and extra="allow", so strip them here rather than
    contorting the models.

    Returns a ToolRequestBody (or ToolResponseBody when `response`), NOT a
    plain dict: _get_json_schema_obj branches on the argument's type, and only
    the BaseModel-subclass and ToolRequestBody/ToolResponseBody branches accept
    a schema. A dict falls through to `TypeAdapter(type_def).json_schema()`,
    which treats it as a *type* and dies with `Unknown schema type: "object"`.
    """

    def flatten(node):
        if not isinstance(node, dict):
            return node
        n = dict(node)
        for key in ("title", "additionalProperties"):
            n.pop(key, None)
        # `"default": null` is what Optional fields emit; it carries no type info.
        if n.get("default", "_missing") is None:
            n.pop("default")
        # anyOf:[X, null] is Optional[X] -- collapse to X.
        if "anyOf" in n:
            options = [o for o in n.pop("anyOf") if o.get("type") != "null"]
            if options:
                for key, val in flatten(options[0]).items():
                    n.setdefault(key, val)
        if "properties" in n:
            n["properties"] = {k: flatten(v) for k, v in n["properties"].items()}
            n.setdefault("type", "object")
        if isinstance(n.get("items"), dict):
            n["items"] = flatten(n["items"])
            n.setdefault("type", "array")
        # List[dict] / dict produce a typeless object; give it empty properties.
        if n.get("type") == "object" and "properties" not in n:
            n["properties"] = {}
        return n

    # Imported inside the function: `flow_builder.types` imports
    # `flow_builder.flows`, which imports `types` straight back, so importing
    # types at module scope from a fresh interpreter raises ImportError on
    # FlowContext. By call time the package is fully initialised.
    from ibm_watsonx_orchestrate.flow_builder.types import (
        ToolRequestBody,
        ToolResponseBody,
    )

    schema = flatten(dereference_refs(model.model_json_schema()))

    # ToolRequestBody/ToolResponseBody declare only type/properties/required;
    # the model-level `description` Pydantic adds from the class docstring is
    # not among them, so drop every key they cannot carry.
    schema = {
        key: val
        for key, val in schema.items()
        if key in ("type", "properties", "required")
    }
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("required", [])

    body = ToolResponseBody if response else ToolRequestBody
    return body(**schema)
