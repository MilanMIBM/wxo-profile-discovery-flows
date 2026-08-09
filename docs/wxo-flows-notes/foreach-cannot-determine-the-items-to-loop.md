# `Cannot determine the items to loop` — foreach item-schema duplication

**Applies to:** `ibm-watsonx-orchestrate` ADK **2.14.0**. Verified 2026-08-08 by compiling probe flows and
inspecting the dumped specs (see [§7 Reproduction](#7-reproduction)).

**TL;DR** — A foreach fails at runtime with `Cannot determine the items to loop` even though `items` is
populated, because the compiled spec registered the item model **twice** under two names:

```text
node.item_schema           -> #/schemas/RespondentProfileItem
node.input_schema.items[]  -> #/schemas/RespondentProfileItem_1     <- different schema
```

The split is triggered by **any top-level field on the item model whose JSON Schema is `type: object`, or an
array of objects** — `dict`, `Dict[str, str]`, a nested `BaseModel`, `List[dict]`, `List[Model]`. Type those
fields `Any` (or leave the container untyped, `List`) and the split disappears.

---

## 1. Symptom

The flow dies at the foreach node. The error prints three things, and they look fine at a glance — `items` is
present and full of correctly-built records:

```text
Cannot determine the items to loop.
input       = {"items":[{"respondent_id":"1ead5aa0-…","identity":{…},"quizzes":[…]}, …]}
inputSchema = {"type":"object","title":"each_respondent_input","required":["items"],
               "properties":{"items":{"type":"array","items":{"title":"RespondentProfileItem_1", …
itemSchema  = {"type":"object","title":"RespondentProfileItem", …
```

**The tell is the `_1`.** `inputSchema`'s array element is `RespondentProfileItem_1`; `itemSchema` is
`RespondentProfileItem`. The engine locates the loop source by matching the input property whose array element
schema *is* the node's `item_schema`. Two names, no match, no loop — regardless of how good the payload is.

The two schemas dump to **byte-identical content**, which is why this reads as impossible until you look at
the names.

## 2. Root cause

Two mechanics in `flow_builder/flows/flow.py` combine:

**a. `Flow.foreach()` embeds the item schema in an auto-built input schema** (flow.py:1552-1587). With no
`input_schema` argument it constructs:

```py
input_schema_obj = JsonSchemaObject(
    type="object",
    properties={"items": JsonSchemaObject(type="array", items=foreach_item_schema)},
    required=["items"])

new_foreach_item_schema = self._add_schema(foreach_item_schema)   # registered separately
```

`_add_schema` **deep-copies** what it registers, so the copy embedded inside `input_schema_obj` stays raw
while the registered one gets normalized.

**b. `Flow._add_schema()` normalizes on registration, then dedupes by comparing raw against normalized**
(flow.py:210-334). Normalization rewrites every property that is `type: object` — and every array whose
`items` are objects — into a `$ref` into the flow's schema registry, promotes inline `$defs`, and strips them:

```jsonc
// before                                    // after registration
"identity": {"type": "object", …}            "identity": {"$ref": "#/schemas/Identity"}
```

When the *second* copy (the raw one, still carrying the inline object) is registered at compile time under the
same title, the deep compare at flow.py:226-249 sees inline-object vs `$ref`, decides they are different
schemas, and renames:

```py
# else we need a new name, and create a new schema
title = title + "_" + str(self._next_sequence_id())        # flow.py:252
```

…and only *then* normalizes the newcomer — which makes it identical to the original, under a different name.

**So the rename happens if and only if normalization changes the item schema**, i.e. if and only if the model
has a field that gets rewritten into a `$ref`. Models made of scalars and scalar arrays compare equal, dedupe
cleanly, and share one registry entry.

### Why the obvious fixes don't work

| Attempt | Result |
| --- | --- |
| Pass an explicit `input_schema` with `items: List[ItemModel]` | **Still splits.** The `$defs` copy is promoted through the same deep compare and still gets `_1`. Verified. |
| Make `items` required (`Field(...)` instead of a default) | Irrelevant. `items` is already required in the auto-built schema; the payload already arrives. |
| Add `each.map_input("items", "flow.<node>.output.<field>")` | Irrelevant. Mapping delivers the data — the error is about *schema identity*, not delivery. |
| `model_config = {"extra": "allow"}` | Irrelevant here (it matters for field retention, not for this). |

## 3. What triggers it

Tested by compiling one probe flow per field type on ADK 2.14.0 and comparing
`item_schema` against the loop input's element `$ref`:

| Top-level field type on the item model | Foreach resolves? |
| --- | --- |
| `str`, `int`, `float`, `bool` | OK |
| `List[str]` (array of scalars) | OK |
| `List` (untyped) | OK |
| `List[Any]` | OK |
| `Any` | OK |
| `Optional[dict]` | OK — *incidental*, see note |
| `dict` | **BREAKS** |
| `Dict[str, str]` | **BREAKS** |
| nested `BaseModel` | **BREAKS** |
| `List[dict]` | **BREAKS** |
| `List[SomeModel]` | **BREAKS** |
| `Optional[SomeModel]` | **BREAKS** |

Only **top-level** fields of the item model matter. Nested structure *inside* an untyped container is
invisible to the normalizer, so `quizzes: List` carrying deep nested dicts at runtime is fine.

> **Note on `Optional[dict]`** — it survives because pydantic emits `anyOf: [{type: object}, {type: null}]`,
> which has no top-level `type: object` for the normalizer to catch. That is an accident of the shape, not a
> supported guarantee. Prefer `Any`.

### Seen in this repo

Three foreach flows, identical wiring, and the item model alone decides the outcome:

| Flow | Item model | Object-typed top-level fields | Compiled refs |
| --- | --- | --- | --- |
| `assemble_prize_detail_extraction_flow.py` | `PrizeItem` — `Optional[str]` + `List[str]` only | none | `PrizeItem` / `PrizeItem` — works |
| `assemble_build_profiles_flow.py` | `RespondentProfileItem` — `RespondentIdentity`, `List[RespondentQuiz]` | two | `RespondentProfileItem` / `RespondentProfileItem_1` — **fails** |
| `alt_assemble_build_profiles_flow.py` | `RespondentProfileItem` — `identity: dict` → `identity: Any` | one → none | was `…Item` / `…Item_1`, now `…Item` / `…Item` — **fixed** |

The single `identity: dict` field was the entire difference in the third flow. Note the second one is still
broken: the fully-typed nested-model version of the same model is the *most* affected shape, not the safest.

## 4. How to avoid it

**Rule: a foreach `item_schema` must be a flat model.** Scalars, scalar arrays, untyped containers, `Any`.
Nothing at the top level that compiles to `type: object`.

```py
# BREAKS — dict / nested model / typed object array at the top level
class RespondentProfileItem(BaseModel):
    respondent_id: str = Field(default="", description="Id of the respondent.")
    identity: dict = Field(default_factory=dict, description="Display name, email, flags.")
    submissions: List[Submission] = Field(default_factory=list, description="Attempts.")

# WORKS — same data, shapes the normalizer leaves alone
class RespondentProfileItem(BaseModel):
    model_config = {"extra": "allow"}
    respondent_id: str = Field(default="", description="Id of the respondent.")
    identity: Any = Field(
        default=None,
        description="Identity block: display_name, email, anonymous, is_owner, placeholder_email.")
    submissions: List = Field(
        default_factory=list,
        description="One entry per attempt: submission_id, submitted_at, correct, incorrect, time_seconds.")
```

Practical consequences of typing a field `Any` / untyped `List`:

- **Data still arrives intact.** The value rides through the engine's item validation untouched — this is the
  same mechanism `quizzes: List` already relies on.
- **You lose per-field validation** on that branch. Nothing checks that `identity` is a dict.
- **The LLM auto-mapper loses the structure**, so put the shape in the `description` (as above). Auto-mapping
  matches on names and descriptions, and that is now the only place the shape is written down.
- **Fields still have to be declared.** `extra="allow"` alone does not retain them — the engine validates each
  item against `item_schema` and drops what is not declared. Declaring the field as `Any` keeps it; deleting
  the field loses it.

If you genuinely need a typed nested model for a step, keep `item_schema` flat and reconstruct/validate inside
the loop body — a script node reading `parent._current_item` can do the typing where it has no effect on the
foreach's schema identity.

> **Scope of verification.** Everything above is confirmed at the *spec* level: the duplicate registration, its
> trigger, and its disappearance after the fix are all readable in the compiled JSON. The claim that the engine
> matches the loop source by schema identity is read off the error payload (`items` populated, both schemas
> printed, names differing) rather than from engine source. A green run is the final confirmation.

## 5. Catch it before import

The defect is fully visible in the compiled spec, so check the dump rather than waiting for a run. Drop this
next to your specs and run it after `compile()` / `dump_spec()`:

```py
# check_foreach_specs.py — usage: python check_foreach_specs.py src/flow_specs/*.json
import json, sys

def check(spec_path):
    spec = json.load(open(spec_path))
    schemas, ok = spec.get("schemas", {}), True

    def ref_name(obj):
        return obj["$ref"].rsplit("/", 1)[-1] if isinstance(obj, dict) and "$ref" in obj else None

    def walk(node_map, path=""):
        nonlocal ok
        for name, node in (node_map or {}).items():
            s = node.get("spec", {})
            if s.get("kind") == "foreach":
                item = ref_name(s.get("item_schema"))
                inp = schemas.get(ref_name(s.get("input_schema")), s.get("input_schema") or {})
                loop = ref_name((inp.get("properties", {}).get("items") or {}).get("items"))
                if item != loop:
                    ok = False
                print(f"{'OK  ' if item == loop else 'FAIL'} {path}{name}: item_schema={item} loop items={loop}")
            walk(node.get("nodes"), f"{path}{name}/")

    walk(spec.get("nodes"))
    return ok

sys.exit(0 if all([check(p) for p in sys.argv[1:]]) else 1)
```

Against this repo's specs (`python check_foreach_specs.py src/flow_specs/*.json`):

```text
OK   for_each_prize:  item_schema=PrizeItem              loop items=PrizeItem
FAIL each_respondent: item_schema=RespondentProfileItem  loop items=RespondentProfileItem_1
OK   each_respondent: item_schema=RespondentProfileItem  loop items=RespondentProfileItem
```

It exits non-zero on any FAIL, so it drops straight into a pre-import check.

Quick manual version — if `grep -o '"RespondentProfileItem[^"]*"' spec.json | sort -u` returns more than one
name, you have the bug.

## 6. The general hazard: title collisions in the schema registry

The foreach failure is one symptom of a broader rule worth knowing:

> **The flow spec has one flat, global schema registry keyed by title. Two schemas that want the same title
> and are not byte-identical (pre-normalization) get suffixed `_1`, `_2`, `_4`, … silently.**

The suffix number comes from the flow's sequence counter, so it is not stable across edits.

Two things feed titles into that registry, and the second one surprises people:

1. **Model class names** — `RespondentProfileItem`, `BuildProfilesOutput`, …
2. **Field names of object-typed fields.** A field `identity: dict` registers a schema titled **`Identity`**;
   `result: dict` registers **`Result`**; `preview_inputs: dict` registers **`Preview Inputs`**. These are
   *global*, so the same generic field name on two different models — with different descriptions — collides.

This repo's own specs show both feeds. `respondent_profile_enrichment_flow.json` registers `Identity`,
`Profile`, `Result`, `Engagement`, `Brand Fan` — all from field names — plus
`Preview Inputs` / `Preview Inputs_1` / `Preview Inputs_2`, three copies because three output models each
declare `preview_inputs` with a different description. `respondent_profile_enrichment.json`, whose item model
is built from nested `BaseModel`s, shows the cascade: `QuizPrize_2`, `QuizPrize_3`, `QuizPrize_5`,
`QuizPrize_6`, `RespondentIdentity_3`, `RespondentIdentity_4`, `RespondentQuiz_2` … one duplicate chain per
place the nested tree is re-embedded.

Most collisions are harmless: a node's schema is self-contained, so an extra `_2` copy costs nothing but
noise. **They only bite where the engine compares schema identity rather than schema content** — foreach
`item_schema` being the known case.

Habits that keep the registry clean:

- Give every model a distinct, specific class name across the whole flow (`MergeProfileOutput`, not `Output`).
- Give object-typed fields specific names (`respondent_identity`, not `identity`; `engagement_result`, not
  `result`) — and keep the description identical everywhere a field name repeats, so copies dedupe instead of
  multiplying.
- Prefer one shared model reused by reference over several structurally-similar models.
- Skim the `schemas` keys of the compiled spec for `_N` suffixes; each one is a collision you didn't intend
  (`bo_N` is not a collision — it is the ADK's placeholder name for an untitled schema):

  ```sh
  python -c "import json,sys,re; print([k for k in json.load(open(sys.argv[1]))['schemas'] \
      if re.search(r'_\d+$', k) and not k.startswith('bo_')])" spec.json
  ```

## 7. Reproduction

Compile one foreach per candidate field type and compare the two refs. This is the script the table in §3 came
from:

```py
import json, tempfile
from typing import List, Any, Dict, Optional
from pydantic import BaseModel, Field
from ibm_watsonx_orchestrate.flow_builder.flows import END, START, Flow, flow
from ibm_watsonx_orchestrate.flow_builder.types import ForeachPolicy

class Nested(BaseModel):
    a: str = Field(default="", description="a")

class Item(BaseModel):                       # swap the probe field's type to test
    model_config = {"extra": "allow"}
    keeper: str = Field(default="", description="k")
    probe: dict = Field(default_factory=dict, description="probe")

class Out(BaseModel):
    x: dict = Field(default_factory=dict, description="out")

@flow(name="probe", display_name="probe", output_schema=Out)
def f(aflow: Flow) -> Flow:
    each = aflow.foreach(item_schema=Item, name="each", display_name="each") \
                .policy(kind=ForeachPolicy.SEQUENTIAL)
    aflow.sequence(START, each, END)
    return aflow

p = tempfile.mktemp(suffix=".json")
f().compile().dump_spec(p)
spec = json.load(open(p))
node = spec["nodes"]["each"]["spec"]
ins  = spec["schemas"][node["input_schema"]["$ref"].rsplit("/", 1)[-1]]
print("item_schema:", node["item_schema"])
print("loop items :", ins["properties"]["items"]["items"])
```

`probe: dict` prints `Item` vs `Item_1`; `probe: Any` prints `Item` vs `Item`.

> `@flow` caches its Flow at decoration time — calling the builder twice raises
> *"Flow has already been compiled."* Re-run the defining cell for a fresh one.

## See also

- [`docs/wxo-flows-docs/10-foreach-node.md`](../wxo-flows-docs/10-foreach-node.md) — foreach parameters,
  policies, `parent._current_item`.
- [`docs/wxo-flows-docs/03-data-mapping.md`](../wxo-flows-docs/03-data-mapping.md) — how descriptions drive
  auto-mapping, which is what you lean on after typing a field `Any`.
- `flow_builder/flows/flow.py` in the installed ADK — `foreach()` at :1552, `_add_schema()` at :210.
