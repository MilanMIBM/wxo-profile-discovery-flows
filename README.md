# wxo-profile-discovery-flows

watsonx Orchestrate agentic flow tooling for generating profile data based on hypothesis-driven behavioral analysis.

Every notebook in this repo is a [marimo](https://marimo.io) notebook stored as a plain `.py` file — no `.ipynb`, no hidden state, no output diffs. That means they are importable Python modules as well as runnable notebooks, which is the core idea the whole project leans on: a logic block is authored and tested in one notebook, then imported by name into another that wires it into a flow.

## Setup

```bash
uv sync                              # or: pip install -r requirements.txt
cp config/.env.TEMPLATE config/.env  # then fill in your credentials
```

Requires Python 3.14+. `config/.env` holds the watsonx Orchestrate environment name and API key, plus MongoDB / PostgreSQL endpoints — it is gitignored, as is the `.pem` cert it points at.

Notebooks call [`ensure_wxo_env`](src/helpers/ensure_wxo_env.py) in their setup cell, which activates the right `orchestrate` environment if it isn't already active. You don't need to source anything by hand before starting a notebook.

## Running the notebooks

```bash
marimo edit wxo-flow-drafting/assemble_build_profiles_flow_v3.py   # author / build a flow
marimo edit wxo-deployed-flow-testing.py                           # test what's deployed
marimo run  wxo-deployed-flow-testing.py                           # read-only app view, no code
```

Run them from the repo root — paths like `config/.env` and `src/flow_specs/` are resolved relative to it.

`marimo edit` gives you the notebook; `marimo run` serves the same file as an app with the code hidden, which is the useful mode for the testing notebook when you just want the UI controls.

## `wxo-flow-drafting/` — building the flows

This is where the work happens. Two kinds of notebook live here:

**Node notebooks** (`wxo_*_node.py`) — one per logic block. Each authors a single node's Python logic and tests it locally against real data, without touching Orchestrate at all. Because marimo's `@app.function` and `@app.class_definition` cells are module-level, the functions they define import like any other symbol.

| Notebook | Node |
| --- | --- |
| [wxo_base_profile_node.py](wxo-flow-drafting/wxo_base_profile_node.py) | base respondent profile |
| [wxo_sustained_engagement_level_node.py](wxo-flow-drafting/wxo_sustained_engagement_level_node.py) | sustained engagement scoring |
| [wxo_long_term_fan_node.py](wxo-flow-drafting/wxo_long_term_fan_node.py) | long-term fan classification |
| [wxo_prize_details_node.py](wxo-flow-drafting/wxo_prize_details_node.py) | prize detail extraction |

**Assembly notebooks** (`assemble_*_flow*.py`) — import the blocks from the node notebooks, wire them into an end-to-end flow, compile it, and import it into Orchestrate. There are two flows: `assemble_build_profiles_flow*` (respondent profile enrichment) and `assemble_prize_detail_extraction_flow*`. These are versioned by filename suffix (`_v2`, `_v3`, …) rather than overwritten, so earlier assemblies stay runnable for comparison — work from the highest version unless you're specifically looking back.

The split is deliberate: node notebooks are where a block is *authored and tested*, assembly notebooks only *wire and ship*.

### Build and import

The assembly notebooks end with an `import_flow_to_wxo` cell behind a run button. It calls `flow.compile()` (not `compile_deploy()` — the ADK rejects flow-tool deploys against anything but a local server), writes the spec to `src/flow_specs/<flow_name>.json`, and shells out to `orchestrate tools import`, which takes a file path rather than an in-memory object.

**Tools are imported first, and overwritten every time.** A compiled flow spec references tool nodes *by name only* — unlike script nodes, which carry their bodies inline, a tool node's source never travels with the flow. A tool that isn't already registered in the environment leaves that node unresolved at runtime. Dependencies are separate again: pip runs server-side at deploy time from a requirements file attached to the *tool* import. Rather than hand-maintain those, each tool declares its own inline in a PEP 723-style block:

```python
# ///
# dependencies = [
#     "docling==2.55.1",
# ]
# ///
```

[`import_tools_to_wxo`](src/helpers/tool_import.py) parses those out, writes a temp requirements.txt per tool, and imports each with `-r`. Nothing permanent is written to the repo.

One gotcha worth knowing: pass the *built* flow to that function, not the builder. `@flow` compiles once at decoration time and caches the result, so calling the builder again replays the body against an already-compiled flow and raises `Flow has already been compiled.` Re-run the cell that defines the flow to get a fresh one.

### Collecting foreach results

A parallel foreach gives each iteration its own copy of flow state and merges by whole-object replacement, so anything a logic block writes to shared state gets clobbered by whichever branch commits last — measured on a 40-iteration run, a `flow.private` list kept 8 records and per-iteration context keys kept 1, with every iteration completing without error. [`foreach_collector`](src/helpers/foreach_collector.py) builds a script node that walks `parent.<loop_name>.output` (the one surface that exposes every iteration) and pulls out one record per iteration. Reach for it whenever a loop body produces something you need all of.

## `wxo-deployed-flow-testing.py` — testing what's deployed

A standalone marimo app for exercising flows that are already live in the environment, separate from the drafting loop. It lets you:

- list and pick a deployed flow from the active environment
- preview the PostgreSQL source tables, and pick an account / user / quiz ID to run against
- fire a test run and inspect the flow result
- push the enriched profiles into MongoDB, with control over what happens to documents that already exist, and retrieve them back to check

This is the notebook to reach for when a flow is deployed and you want to know whether it behaves — the assembly notebooks handle up to and including import, this one takes over after.

## What's where

| Path | Contents |
| --- | --- |
| [wxo-flow-drafting/](wxo-flow-drafting/) | node + assembly notebooks (the main working area) |
| [wxo-deployed-flow-testing.py](wxo-deployed-flow-testing.py) | deployed-flow test app |
| [src/helpers/](src/helpers/) | env activation, tool import, foreach collection, inference client, MongoDB document helpers, marimo UI helpers |
| [src/tools/](src/tools/) | standalone Orchestrate Python tools (`fetch_url_data`, `retrieve-database-tables`, `upload-enriched-profile`), each with its own requirements file |
| [src/flow_specs/](src/flow_specs/) | compiled flow JSON, written by the assembly notebooks |
| [src/data/](src/data/) | test tables (CSV), JSON schemas, and connection YAML + import scripts |
| [src/utils/](src/utils/) | shell helpers for wxo env setup / activation and tool import |
| [docs/wxo-flows-docs/](docs/wxo-flows-docs/) | reference notes on flow nodes, data mapping, expressions, CLI |
| [config/](config/) | `.env` (gitignored) and DB certs |

## Typical loop

1. Author or edit a logic block in its `wxo_*_node.py` notebook, testing it there against real rows.
2. Open the current assembly notebook, re-run the cell that imports the block and the cell that builds the flow.
3. Hit the import button — tools go up first, then the compiled flow spec.
4. Switch to `wxo-deployed-flow-testing.py` to run it end-to-end and check the output lands in MongoDB.
