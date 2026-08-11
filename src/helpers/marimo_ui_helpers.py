import marimo as mo

_UNSET = object()


def accordion_preview(
    value=_UNSET,
    name=None,
    lazy=False,
    nest_accordion=None,
    nested_value=None,
    nested_name=None,
    gap=1,
):
    """Wrap `value` in a collapsed `mo.accordion` labelled with its variable name.

    Args:
        value: Anything marimo can render (dataframe, dict, UI element, ...). May
            be omitted when `nested_value` is given, in which case the nested
            accordions are stacked on their own as the entry's body.
        name: Override for the label. When None, the caller's variable name that
            points at `value` is looked up and used instead.
        lazy: Passed through to `mo.accordion` to defer rendering until opened.
        nest_accordion: When True, `nested_value` is rendered as its own accordion
            and stacked underneath `value`, inside the outer accordion's entry.
            Defaults to None, meaning "True whenever `nested_value` is given";
            pass False to suppress nesting even with a `nested_value`.
        nested_value: The value shown in the nested accordion. A list or tuple
            yields one nested accordion per item, all stacked with `mo.vstack`.
        nested_name: Override for the nested accordion's label; a list or tuple to
            label each nested value in turn (use None for entries that should keep
            their looked-up variable name). When None, the caller's variable name
            that points at each nested value is used instead.
        gap: Passed through to `mo.vstack` when stacking the nested accordions.

    Returns:
        A `mo.accordion` whose single key is `**<name>**` and whose value is
        `value`, or a `mo.vstack` of `value` (when given) and the nested
        accordions when `nest_accordion` is True.
    """
    import inspect as _inspect

    if nest_accordion is None:
        nest_accordion = nested_value is not None

    if value is _UNSET and not nest_accordion:
        raise TypeError("accordion_preview() needs `value`, `nested_value`, or both")

    _scope = {}
    if name is None or (nest_accordion and nested_name is None):
        _frame = _inspect.currentframe().f_back
        try:
            _scope = {**_frame.f_globals, **_frame.f_locals}
        finally:
            # Break the frame reference cycle so the caller frame can be freed.
            del _frame

    def _auto_name(target):
        _names = [
            _key
            for _key, _val in _scope.items()
            if _val is target and not _key.startswith("_")
        ]
        return _names[0] if _names else None

    def _label(target, override, fallback=None):
        if override:
            return override
        return f"**{_auto_name(target) or fallback or type(target).__name__}**"

    if nest_accordion:
        nested_values = (
            list(nested_value)
            if isinstance(nested_value, (list, tuple))
            else [nested_value]
        )
        nested_names = (
            list(nested_name)
            if isinstance(nested_name, (list, tuple))
            else [nested_name] * len(nested_values)
        )
        nested_names += [None] * (len(nested_values) - len(nested_names))

        nested_accordions = [
            mo.accordion({_label(_val, _name): _val}, lazy=lazy)
            for _val, _name in zip(nested_values, nested_names)
        ]
        stack = nested_accordions if value is _UNSET else [value] + nested_accordions
        body = mo.vstack(stack, gap=gap)
    else:
        body = value

    if value is _UNSET:
        # Nothing to name the panel after, so fall back to the nested container's
        # variable name (or a generic label when it was built inline).
        label = _label(nested_value, name, fallback="Preview")
    else:
        label = _label(value, name)

    return mo.accordion({label: body}, lazy=lazy)
