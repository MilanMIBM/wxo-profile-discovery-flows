import marimo

__generated_with = "0.23.16"
app = marimo.App(width="columns")

with app.setup:
    import marimo as mo
    import pandas as pd
    import subprocess
    import sqlalchemy
    import psycopg2
    import json
    import sys
    import os

    from pathlib import Path
    from typing import List, Dict, Optional
    from pydantic import BaseModel, Field
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block
    from ibm_watsonx_orchestrate.flow_builder.flows import (
        END,
        START,
        Flow,
        flow,
    )
    from ibm_watsonx_orchestrate.flow_builder.types import ForeachPolicy
    from src.helpers.ensure_wxo_env import ensure_wxo_env

    wxo_env_status = ensure_wxo_env(env_file="config/.env", reactivate=True)
    print(wxo_env_status)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # **Prize Detail Extraction -- Flow Assembly**

    Takes the same table bundle as the respondent-profile flow, but follows the
    prize branch instead: collect every distinct prize from `quiz_meta`, then run
    one linear pass per prize --

    - **fetch_url_data** on the prize url (when one is present) -> **extract_prize_details**
      reduces the fetched page to specification text with an LLM;
    - **metadata_tag_generation** derives enriched tags from the baseline prize
      information, so it does not depend on the page fetch having found anything.

    A prize with no url still gets tags -- it just carries no scraped
    description. The prizes themselves are still iterated in parallel; it is only
    the per-prize work that is sequential.

    Every tool, prompt node and logic block is imported from the `*_node.py`
    notebook that owns it -- marimo's `@app.function` / `@app.class_definition`
    cells are module-level, so they import like any other symbol. This notebook
    only *wires and ships* them.
    """)
    return


@app.cell
def _():
    load_dotenv("config/.env", override=True)
    return


@app.cell
def _():
    pg_endpoint = os.path.expandvars(os.getenv("POSTGRESQL_ENDPOINT", ""))
    return (pg_endpoint,)


@app.cell
def _():
    mongodb_endpoint = os.path.expandvars(os.getenv("MONGODB_ENDPOINT", ""))
    return (mongodb_endpoint,)


@app.cell
def _(pg_endpoint):
    postgresql_engine = sqlalchemy.create_engine(
        pg_endpoint, connect_args={"sslmode": "require"}
    )
    print(postgresql_engine)
    return (postgresql_engine,)


@app.cell
def _(mongodb_endpoint):
    mongodb = MongoClient(mongodb_endpoint)
    print(mongodb)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Test Data Import**
    """)
    return


@app.function(hide_code=True)
def value_select_mapping(df, key_col, value_col):
    """Build a {key_col value: value_col value} dict from a dataframe.

    Args:
        df: A pandas or polars dataframe.
        key_col: Name of the column whose values become dict keys.
        value_col: Name of the column whose values become dict values.

    Returns:
        dict mapping each row's key_col value to its value_col value.
    """
    if hasattr(df, "to_dicts"):
        rows = df.to_dicts()
    else:
        rows = df.to_dict(orient="records")
    return {row[key_col]: row[value_col] for row in rows}


@app.cell(hide_code=True)
def _(postgresql_engine):
    from sqlalchemy import text, inspect
    from sqlalchemy.dialects.postgresql import JSONB

    # Drop existing tables before reloading them from CSV. Compare the string, since
    # bool("False") is True.
    rewrite_tables = os.getenv("REWRITE_TABLES", "false").lower() == "true"
    print(f"Rewrite tables: **{rewrite_tables}**")

    TABLES_DIR = Path("src/data/tables")
    existing = set(inspect(postgresql_engine).get_table_names())

    # One table per CSV in TABLES_DIR, named after the file stem -- drop a new CSV
    # in the directory and it gets loaded without touching this cell.
    table_csvs = sorted(TABLES_DIR.glob("*.csv"))
    print(f"Found {len(table_csvs)} CSV(s) in {TABLES_DIR}")

    # Columns stored in the CSV as JSON-array strings ('["a","b"]') that should land in Postgres as native jsonb (real lists) rather than plain text.
    JSON_COLUMNS = {
        "quiz_meta": ["brand_tags", "prize_type"],
    }

    def _parse_json_cell(val):
        # Blank/NaN -> NULL; otherwise decode the JSON array. Leave already-parsed values (list/dict) untouched so re-runs are idempotent.
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        if isinstance(val, (list, dict)):
            return val
        s = str(val).strip()
        return json.loads(s) if s else None

    for csv_path in table_csvs:
        name = csv_path.stem

        # Missing tables are always created; existing ones are only rebuilt when rewrite_tables is set, so a partial set fills in the gaps.
        if name in existing and not rewrite_tables:
            print(f"{name}: already exists, skipping (rewrite_tables is False)")
            continue

        if name in existing:
            print(f"{name}: dropping existing table")

            with postgresql_engine.begin() as connection:
                connection.execute(
                    text(f'DROP TABLE IF EXISTS "{name}" CASCADE')
                )
            existing.remove(name)

        df = pd.read_csv(csv_path)
        dtype = {}
        for col in JSON_COLUMNS.get(name, []):
            if col in df.columns:
                df[col] = df[col].map(_parse_json_cell)
                dtype[col] = JSONB()
        df.to_sql(
            name,
            postgresql_engine,
            index=False,
            if_exists="fail",
            dtype=dtype,
        )
        print(f"{name}: created, loaded {len(df)} rows")
    return


@app.cell
def _():
    retrieve_number = mo.ui.number(
        label="**Control number of records to retrieve :**",
        start=0,
        stop=1000,
        step=1,
        value=3,
    )
    # retrieve_number
    return (retrieve_number,)


@app.cell
def _(retrieve_number, select_account):
    filter_stack = mo.hstack(
        [select_account, retrieve_number], justify="space-around"
    )
    # filter_stack
    return (filter_stack,)


@app.cell(hide_code=True)
def _(postgresql_engine, retrieve_number, select_account):
    if select_account.value:
        quiz_meta = mo.sql(
            f"""
            SELECT * FROM "quiz_meta"
            WHERE "account_id" = '{select_account.value}'
            LIMIT {retrieve_number.value}
            """,
            engine=postgresql_engine,
            output=False,
        )
    else:
        quiz_meta = mo.sql(
            f"""
            SELECT * FROM "quiz_meta"
            LIMIT {retrieve_number.value}
            """,
            engine=postgresql_engine,
            output=False,
        )
    return (quiz_meta,)


@app.cell(hide_code=True)
def _(postgresql_engine, quiz_meta):
    quiz_structure = mo.sql(
        f"""
        SELECT * FROM "quiz_structure"
        WHERE "quiz_id" IN ({",".join(map(repr, quiz_meta["quiz_id"].to_list())) or "NULL"})
        LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine
    )
    return (quiz_structure,)


@app.cell(hide_code=True)
def _(postgresql_engine, quiz_meta):
    quiz_details = mo.sql(
        f"""
        SELECT * FROM "quiz_details" 
        WHERE "quiz_id" IN ({",".join(map(repr, quiz_meta["quiz_id"].to_list())) or "NULL"})
        LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine
    )
    return (quiz_details,)


@app.cell(hide_code=True)
def _(postgresql_engine, quiz_meta):
    quiz_scoring = mo.sql(
        f"""
        SELECT * FROM "quiz_scoring"
        WHERE "quiz_id" IN ({",".join(map(repr, quiz_meta["quiz_id"].to_list())) or "NULL"})
        LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine
    )
    return (quiz_scoring,)


@app.cell
def _(postgresql_engine):
    account_ids_unique = mo.sql(
        f"""
        SELECT DISTINCT "account_id" FROM "quiz_meta"
        """,
        output=False,
        engine=postgresql_engine
    )
    return (account_ids_unique,)


@app.cell
def _(account_ids_unique):
    account_id_list = account_ids_unique.account_id.to_list()
    select_account = mo.ui.dropdown(
        label="**Select account to filter by :**",
        options=account_id_list,
        # value=account_id_list[0],
    )
    # select_account
    return (select_account,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Prize urls present in the catalogue**
    """)
    return


@app.cell(hide_code=True)
def _(postgresql_engine):
    prize_urls = mo.sql(
        f"""
        SELECT DISTINCT "prize.prize_name", "prize.prize_url" FROM "quiz_meta" WHERE "prize.prize_url" IS NOT NULL
        """,
        output=False,
        engine=postgresql_engine
    )
    return (prize_urls,)


@app.cell
def _(prize_urls):
    prize_urls_list = prize_urls["prize.prize_url"].to_list()
    prize_names_list = prize_urls["prize.prize_name"].to_list()
    _prize_url_mapping = dict(zip(prize_names_list, prize_urls_list))

    select_prize_url = mo.ui.dropdown(
        label="**Select prize URL :**",
        options=_prize_url_mapping,
        value=prize_names_list[0],
        full_width=True,
    )
    # select_prize_url
    return


@app.function(hide_code=True)
def as_table_entry(name, df):
    """Shape a dataframe like one `retrieve_database_tables` result entry."""
    # mo.sql returns pandas here (.to_dict(orient="records")), but returns polars, (.to_dicts()) when marimo's dataframe backend is switched, so accept both.
    rows = (
        df.to_dicts()
        if hasattr(df, "to_dicts")
        else df.to_dict(orient="records")
    )
    return {
        "table": name,
        "rows": [jsonable_row(r) for r in rows],
    }


@app.function(hide_code=True)
def jsonable_row(row):
    """Convert a dataframe row mapping to a plain JSON-serialisable dict.

    Same coercion as `retrieve_database_tables._jsonable_row`, inlined here so
    the notebook has no dependency on the tool module: Decimal -> float, dates ->
    ISO strings, bytes -> decoded/hex, UUID and anything else unknown -> str.
    Adds pandas' missing values (NaN/NaT/pd.NA) -> None, since those stand in for
    the SQL NULLs and aren't valid JSON.
    """
    import datetime
    import decimal

    def coerce(val):
        if val is None or isinstance(val, (bool, int, str)):
            return val
        if isinstance(val, float):
            # NaN != NaN; NaN and inf are both unrepresentable in JSON.
            return (
                None
                if val != val or val in (float("inf"), float("-inf"))
                else val
            )
        if isinstance(val, decimal.Decimal):
            return float(val)
        if isinstance(
            val, (datetime.datetime, datetime.date, datetime.time)
        ):
            return val.isoformat()
        if isinstance(val, (bytes, bytearray, memoryview)):
            b = bytes(val)
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return b.hex()
        if isinstance(val, dict):
            return {k: coerce(v) for k, v in val.items()}
        if isinstance(val, (list, tuple, set)):
            return [coerce(v) for v in val]
        # pandas NaT and pd.NA are neither None nor float NaN.
        if val is not val or str(val) in ("NaT", "<NA>"):
            return None
        return str(val)

    return {key: coerce(value) for key, value in row.items()}


@app.cell
def _(quiz_details, quiz_meta, quiz_scoring, quiz_structure):
    db_records = [
        as_table_entry("quiz_meta", quiz_meta),
        as_table_entry("quiz_structure", quiz_structure),
        as_table_entry("details", quiz_details),
        as_table_entry("scoring", quiz_scoring),
    ]
    return (db_records,)


@app.cell
def _(db_records):
    # Same input shape as the respondent-profile flow and the *_node.py notebooks: the retrieved_tables bundle as a bare list of table entries.
    test_flow = {"retrieved_tables": db_records}
    return (test_flow,)


@app.cell
def _():
    run_tests = mo.ui.run_button(label="Run Node Tests")
    return


@app.cell(column=1, hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.cell
def _():
    # The tool, prompt nodes and their schemas are authored and locally tested in
    # wxo_prize_details_node.py; imported here so there is exactly one definition
    # of each and this notebook only wires them together.
    from wxo_prize_details_node import (
        build_prompt_extract_prize_details,
        build_prompt_metadata_tag_generation,
        fetch_url_data,
    )

    return (
        build_prompt_extract_prize_details,
        build_prompt_metadata_tag_generation,
        fetch_url_data,
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.class_definition
# FOR EACH - subflow - Input Schema
class PrizeItem(BaseModel):
    """One prize as iterated by the foreach.

    EVERY field the downstream nodes read must be declared here. `extra="allow"`
    is not enough: the engine validates each item against this schema and drops
    whatever it does not declare, so an undeclared field arrives empty at
    `parent._current_item` even though collect_prize_catalogue emitted it.
    """

    model_config = {"extra": "allow"}

    quiz_id: Optional[str] = Field(
        default=None, description="Id of the quiz the prize belongs to."
    )
    title: Optional[str] = Field(
        default=None, description="Title of the quiz the prize belongs to."
    )
    brand_name: Optional[str] = Field(
        default=None, description="Brand that provides the prize."
    )
    brand_tags: List[str] = Field(
        default_factory=list, description="Brand descriptor tags."
    )
    language: Optional[str] = Field(
        default=None, description="Language of the quiz."
    )
    prize_name: Optional[str] = Field(
        default=None, description="Name of the prize."
    )
    prize_url: Optional[str] = Field(
        default=None,
        description="Prize page url, or empty when the catalogue has none.",
    )
    prize_value: Optional[str] = Field(
        default=None,
        description="Numeric price of the prize, excluding currency.",
    )
    prize_currency: Optional[str] = Field(
        default=None,
        description="ISO 4217 currency code for the price, e.g. 'NOK', 'GBP'.",
    )
    prize_description: Optional[str] = Field(
        default=None,
        description="Free-text prize description as supplied by the catalogue.",
    )
    prize_type: List[str] = Field(
        default_factory=list,
        description="Prize category tags, e.g. 'product' or 'experience'.",
    )
    has_prize_url: Optional[bool] = Field(
        default=None,
        description="Whether the prize carries a fetchable url.",
    )


@app.cell
def _():
    @logic_block(
        display_name="Collect prize catalogue",
        output_schema=PrizeCatalogueOutput,
    )
    def collect_prize_catalogue(flow, self, parent, json):
        """Collapses the quiz_meta table into one record per distinct prize, nesting the flat prize.* columns and flagging which prizes carry a fetchable url.

        Runs in the flow engine's restricted sandbox, NOT as a normal module:
        `flow`, `self` and `parent` are injected, `json` is pre-bound (no
        imports), and there is no return value -- output happens by assignment.

        Reads:  the table bundle (quiz_meta) from the flow input -- bare, or
                nested under "retrieved_tables" / an "output" wrapper
        Writes: self.output.prizes              -- prize records to iterate
                self.output.prizes_num          -- how many were collected
                self.output.prizes_with_url_num -- how many carry a prize url

        The counters live on the node's public output only: flow.private.*
        requires a private_schema on the @flow decorator, and an undeclared
        private write fails inside the first node and kills the whole run."""

        # First node in the flow, so the tables come from the flow's own input. The bundle is normally a bare list of {"table":..., "rows":[...]}, but a caller passing a retrieval node's context through verbatim wraps it.
        flow_input = flow["input"] or {}
        tables = flow_input.get("retrieved_tables") or flow_input
        if isinstance(tables, dict):
            for key in ("output", "result", "value", "tables"):
                if isinstance(tables.get(key), list):
                    tables = tables[key]
                    break
        if not isinstance(tables, list):
            tables = []

        # Tags are stored as JSON-array strings ('["a","b"]') but may also arrive as a real list, empty, or "[]".
        def parse_tags(value):
            if value is None:
                return []
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                s = value.strip()
                if s in ("", "[]"):
                    return []
                try:
                    parsed = json.loads(s)
                except ValueError:
                    return []
                return parsed if isinstance(parsed, list) else []
            return []

        # Missing values arrive as None or as the string "nan" once the CSV has been round-tripped; treat both as absent. "" rather than None so the downstream url test never trips over a null.
        def text(value):
            if value is None:
                return ""
            s = str(value).strip()
            return "" if s.lower() in ("nan", "none", "null") else s

        by_table = {t.get("table"): (t.get("rows") or []) for t in tables}
        quiz_meta = by_table.get("quiz_meta") or []

        records = []
        seen = {}
        with_url = 0
        for m in quiz_meta:
            qid = m.get("quiz_id")
            if qid is None or qid in seen:
                continue
            seen[qid] = True

            url = text(m.get("prize.prize_url"))
            if url:
                with_url += 1

            records.append(
                {
                    "quiz_id": qid,
                    "title": text(m.get("title")),
                    "brand_name": text(m.get("brand_name")),
                    "brand_tags": parse_tags(m.get("brand_tags")),
                    "language": text(m.get("language")),
                    "prize_name": text(m.get("prize.prize_name")),
                    "prize_url": url,
                    "prize_value": text(m.get("prize.prize_value")),
                    "prize_currency": text(m.get("prize.prize_currency")),
                    "prize_description": text(m.get("prize.prize_description")),
                    "prize_type": parse_tags(m.get("prize_type")),
                    "has_prize_url": bool(url),
                }
            )

        self.output.prizes = records
        self.output.prizes_num = len(records)
        self.output.prizes_with_url_num = with_url

        flow.private.enriched_prizes = []

    return (collect_prize_catalogue,)


@app.class_definition
### collect_prize_catalogue - Output Schema
class PrizeCatalogueOutput(BaseModel):
    """Outputs of the collect_prize_catalogue script node."""

    prizes: List[dict] = Field(
        default_factory=list,
        description="One record per distinct prize found in quiz_meta.",
    )
    prizes_num: Optional[int] = Field(
        default=None, description="How many prizes were collected."
    )
    prizes_with_url_num: Optional[int] = Field(
        default=None, description="How many of them carry a prize url."
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.function
@logic_block(
    display_name="Stage prize inputs",
)
def stage_prize_inputs(flow, self, parent, json):
    """Turns the current prize record into the url list the fetch tool consumes and the baseline prize fields the tag-generation prompt consumes.

    Runs in the flow engine's restricted sandbox, NOT as a normal module:
    `flow`, `self` and `parent` are injected, `json` is pre-bound (no imports),
    and there is no return value -- output happens by assignment.

    Reads:  parent._current_item -- the prize record for this iteration
    Writes: self.output.urls -- [] when no url, so fetch_url_data is a no-op
            self.output.<PrizeInfo fields> -- brand/prize/value/currency + knobs

    fetch_url_data takes a LIST of urls and returns one entry per url, so an
    empty list is the natural "nothing to fetch" signal -- no branch needed."""
    prize = dict(parent._current_item or {})

    url = prize.get("prize_url") or ""
    self.output.urls = [url] if url else []
    self.output.has_prize_url = bool(url)

    self.output.brand_name = prize.get("brand_name") or ""
    self.output.prize_name = prize.get("prize_name") or ""
    self.output.prize_description = prize.get("prize_description") or ""
    self.output.prize_value = prize.get("prize_value") or "0"
    self.output.prize_currency = prize.get("prize_currency") or ""
    self.output.language = prize.get("language") or ""

    self.output.tag_type = (
        flow["input"].get("tag_type") or "type, purpose, audience"
    )
    self.output.number_of_tags = int(
        flow["input"].get("number_of_tags") or 8
    )
    self.output.preview_inputs = prize


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.function
@logic_block(
    display_name="Select fetched page",
)
def select_fetched_page(flow, self, parent, json):
    """Reduces the fetch tool's list of documents to the single page string the extraction prompt expects, blanking failures and empty fetches.

    Runs in the flow engine's restricted sandbox, NOT as a normal module:
    `flow`, `self` and `parent` are injected, `json` is pre-bound (no imports),
    and there is no return value -- output happens by assignment.

    Reads:  self.input.documents -- fetch_url_data's strings, one per url
    Writes: self.output.page_content -- the first usable document, else ""

    fetch_url_data never raises on a bad url; it returns an "ERROR: ..." string
    in that slot. Those become "" so the extraction prompt sees no content
    rather than being asked to summarise an error message."""
    inputs = parent.fetch_url_data.output.documents or {}

    if isinstance(inputs, dict):
        documents = inputs.get("documents") or []
    elif isinstance(inputs, list):
        documents = inputs
    else:
        documents = []

    page = ""
    for entry in documents:
        if not isinstance(entry, str):
            continue
        if entry.startswith("ERROR:"):
            continue
        page = entry
        break

    self.output.page_content = page
    self.output.fetched = bool(page)
    self.output.preview_inputs = inputs


@app.cell
def _():
    @logic_block(
        display_name="Assemble prize record",
        output_schema=EnrichedPrizeOutput,
    )
    def assemble_prize_record(flow, self, parent, json):
        """Layers the extracted specification text and the generated metadata tags onto the prize record this iteration started from.

        Reads:  parent._current_item -- the prize record for this iteration
                self.input.*         -- whatever the enrichment nodes produced
        Writes: self.output.prize / .prize_description / .metadata_tags
                / .result_json

        Node-name agnostic: reads self.input rather than any named node, so
        upstream nodes can be renamed or added to without touching this body --
        only the data maps wiring them into this node's input change.

        self.input is filled by EXPLICIT maps in the flow builder:
          generated_description <- extract_prize_details
          tags                  <- prize_metadata_tag_generation (whole object)
        The record's own catalogue blurb is a different thing entirely: it
        comes from parent._current_item, never from these inputs."""
        prize = dict(parent._current_item or {})

        prize_description = prize.get("prize_description") or ""
        generated_description = (
            parent.extract_prize_details.output.generated_description or ""
        )

        tags_obj = parent.prize_metadata_tag_generation.output.tags or {}
        tags = (
            tags_obj.get("metadata_tags")
            if isinstance(tags_obj, dict)
            else None
        )
        tags = [tag for tag in tags if tag] if isinstance(tags, list) else []

        self.output.quiz_id = prize.get("quiz_id")
        self.output.prize_name = prize.get("prize_name")
        self.output.prize_description = prize_description
        self.output.generated_description = generated_description
        self.output.metadata_tags = tags
        self.output.prize = prize

        self.output.row = {
            "quiz_id": prize.get("quiz_id"),
            "prize_name": prize.get("prize_name"),
            "prize_description": prize_description,
            "generated_description": generated_description,
            "metadata_tags": tags,
            "prize": prize,
        }
        collected = flow["private"].get("enriched_prizes") or []
        flow.private.enriched_prizes = collected + [self.output.row]

    return (assemble_prize_record,)


@app.class_definition
### assemble_prize_record - Output Schema
class EnrichedPrizeOutput(BaseModel):
    """Outputs of the assemble_prize_record script node."""

    quiz_id: Optional[str] = Field(
        default=None, description="Id of the quiz the prize belongs to."
    )
    prize_name: Optional[str] = Field(
        default=None, description="Name of the prize."
    )
    prize_description: Optional[str] = Field(
        default=None,
        description="Original object prize description, if present.",
    )
    generated_description: Optional[str] = Field(
        default=None,
        description="Specification text extracted from the prize page, when one was fetched.",
    )
    metadata_tags: List[str] = Field(
        default_factory=list,
        description="Enriched descriptor tags generated from the prize information.",
    )
    prize: Optional[dict] = Field(
        default=None, description="The whole enriched prize record."
    )
    row: Optional[dict] = Field(
        default=None,
        description="This iteration's record as appended to flow.private.enriched_prizes.",
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _(PrizeTableOutputs):
    @logic_block(
        display_name="Build prize table",
        output_schema=PrizeTableOutputs,
    )
    def build_prize_table(flow, self, parent, json, each):
        """Flattens the loop's enriched prize records into one flat dict per prize so the result loads straight into a dataframe.

        Runs ONCE, after the foreach -- it reads the whole accumulated list, not a
        single item, so it sits outside the loop where `parent._current_item` is
        meaningless.

        Reads:  parent.<for_each_flow_name>.<last_node_name>.output -- the for_each's aggregated per-iteration outputs
        Writes: self.output.rows      -- flat dicts, one per prize
                self.output.row_count -- how many rows were produced

        The loop hands back each iteration's assemble_prize_record output, which
        nests the catalogue fields under `prize`. Pandas would turn that nested
        dict into a single object-dtype column, so those fields are lifted to the
        top level here and the row is left entirely flat."""
        inputs = (
            {"rows": parent.for_each_prize.assemble_prize_record.output}
            if isinstance(
                parent.for_each_prize.assemble_prize_record.output, list
            )
            else (
                parent.for_each_prize.assemble_prize_record.output
                if isinstance(
                    parent.for_each_prize.assemble_prize_record.output, dict
                )
                else {}
            )
        )
        rows_in = inputs.get("rows")

        # Tolerate the bare list and the {rows: [...]} / {items: [...]} wrappers.
        if isinstance(rows_in, dict):
            for key in ("rows", "items", "output", "result"):
                if isinstance(rows_in.get(key), list):
                    rows_in = rows_in[key]
                    break
        if not isinstance(rows_in, list):
            rows_in = []

        # The mapped input is the fallback, not the primary source: the foreach exposes no readable aggregate, so the records actually arrive via the flow-scoped list each iteration appended to.
        if not rows_in:
            collected = flow["private"].get("enriched_prizes")
            if isinstance(collected, list):
                rows_in = collected

        def text(value):
            return "" if value is None else str(value)

        def tags(value):
            return [t for t in value if t] if isinstance(value, list) else []

        rows_out = []
        for entry in rows_in:
            if not isinstance(entry, dict):
                continue

            # Each entry is an assemble_prize_record output; the catalogue fields live one level down under `prize`.
            prize = entry.get("prize")
            if not isinstance(prize, dict):
                prize = {}

            rows_out.append(
                {
                    "quiz_id": text(
                        entry.get("quiz_id") or prize.get("quiz_id")
                    ),
                    "title": text(prize.get("title")),
                    "brand_name": text(prize.get("brand_name")),
                    "language": text(prize.get("language")),
                    "prize_name": text(
                        entry.get("prize_name") or prize.get("prize_name")
                    ),
                    "prize_url": text(prize.get("prize_url")),
                    "prize_value": text(prize.get("prize_value")),
                    "prize_currency": text(prize.get("prize_currency")),
                    "prize_description": text(entry.get("prize_description")),
                    "generated_description": text(
                        entry.get("generated_description")
                    ),
                    "metadata_tags": tags(entry.get("metadata_tags")),
                    "brand_tags": tags(prize.get("brand_tags")),
                    "prize_type": tags(prize.get("prize_type")),
                    "has_prize_url": bool(prize.get("has_prize_url")),
                }
            )

        self.output.rows = rows_out
        self.output.row_count = len(rows_out)
        self.output.preview_inputs = inputs

    return (build_prize_table,)


@app.cell
def _():
    class PrizeTableOutputs(BaseModel):
        """Final output of the prize_detail_extraction flow.

        `rows` is a flat list of one dict per prize, every value a scalar or a list
        of strings, so `pd.DataFrame(result["rows"])` yields a table directly with
        no further unnesting.
        """

        rows: List[EnrichedPrizeTableRow] = Field(
            default_factory=list,
            description="One flat row per prize, ready to load straight into a dataframe.",
        )
        row_count: Optional[int] = Field(
            default=None, description="How many prize rows were produced."
        )
        preview_inputs: Optional[dict] = Field(
            default=None,
            description="The inputs preview for debugging",
        )

    return (PrizeTableOutputs,)


@app.class_definition
### One dataframe row
class EnrichedPrizeTableRow(BaseModel):
    """A single prize as one flat, dataframe-ready row.

    Deliberately FLAT: no nested objects, because a nested dict lands in pandas
    as an object-dtype cell rather than a column. `metadata_tags` stays a list
    of strings (one cell holding a list is normal and still filterable) and the
    whole record is additionally carried as `result_json` for anything that
    needs the unflattened form.
    """

    quiz_id: Optional[str] = Field(
        default=None, description="Id of the quiz the prize belongs to."
    )
    title: Optional[str] = Field(
        default=None, description="Title of the quiz the prize belongs to."
    )
    brand_name: Optional[str] = Field(
        default=None, description="Brand that provides the prize."
    )
    language: Optional[str] = Field(
        default=None, description="Language of the quiz."
    )
    prize_name: Optional[str] = Field(
        default=None, description="Name of the prize."
    )
    prize_url: Optional[str] = Field(
        default=None,
        description="Prize page url, empty when the catalogue has none.",
    )
    prize_value: Optional[str] = Field(
        default=None,
        description="Numeric price of the prize, excluding currency.",
    )
    prize_currency: Optional[str] = Field(
        default=None, description="ISO 4217 currency code for the price."
    )
    prize_description: Optional[str] = Field(
        default=None,
        description="Catalogue's own prize description, if present.",
    )
    generated_description: Optional[str] = Field(
        default=None,
        description="Specification text extracted from the prize page, when one was fetched.",
    )
    metadata_tags: List[str] = Field(
        default_factory=list,
        description="Enriched descriptor tags generated from the prize information.",
    )
    brand_tags: List[str] = Field(
        default_factory=list,
        description="Brand descriptor tags from the catalogue.",
    )
    prize_type: List[str] = Field(
        default_factory=list, description="Prize category tags."
    )
    has_prize_url: Optional[bool] = Field(
        default=None,
        description="Whether the prize carried a fetchable url.",
    )


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    # **Build Flow into wxo Environment**
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    /// admonition | Flow Build
    """)
    return


@app.class_definition
### Flow-level private state
class PrizeFlowPrivate(BaseModel):
    """Internal accumulator for the for_each_prize loop.

    The foreach node exposes no readable aggregate of its iterations: its
    `output_schema` is deprecated and populates nothing, and mapping the loop's
    output (whole or by leaf) into a downstream node yields empty. So each
    iteration appends its own record to this flow-scoped list instead, and
    build_prize_table reads the finished list after the loop.

    flow.private.* is flow-scoped rather than node-scoped, which is what lets a
    node inside the subflow write somewhere a node outside it can read.
    """

    enriched_prizes: List[dict] = Field(
        default_factory=list,
        description="One enriched prize record per completed iteration.",
    )


@app.class_definition
### Flow-level Output Schema
class PrizeFlowOutput(BaseModel):
    """Final output of the prize_detail_extraction flow.

    `rows` is a flat list of one dict per prize, every value a scalar or a list
    of strings, so `pd.DataFrame(result["rows"])` yields a table directly with
    no further unnesting.
    """

    rows: List[EnrichedPrizeTableRow] = Field(
        default_factory=list,
        description="One flat row per prize, ready to load straight into a dataframe.",
    )
    row_count: int = Field(
        default=0, description="How many prize rows were produced."
    )


@app.cell
def _(
    assemble_prize_record,
    build_prize_table,
    build_prompt_extract_prize_details,
    build_prompt_metadata_tag_generation,
    collect_prize_catalogue,
    display_name,
    fetch_url_data,
    flow_name,
):
    @flow(
        name=flow_name,
        display_name=display_name,
        output_schema=PrizeFlowOutput,
        private_schema=PrizeFlowPrivate,
        description=(
            """Collects every distinct prize from the raw quiz tables, then per prize fetches its page and reduces it to specification text with an LLM and generates enriched metadata tags from the baseline prize information, returning a flat table of one enriched row per prize."""
        ),
    )
    def build_prize_detail_extraction_flow(aflow: Flow) -> Flow:

        collect = collect_prize_catalogue(aflow)

        each: Flow = aflow.foreach(
            item_schema=PrizeItem,
            name="for_each_prize",
            display_name="For each prize",
            # ).policy(kind=ForeachPolicy.SEQUENTIAL)
        ).policy(kind=ForeachPolicy.PARALLEL)

        each.map_input("items", f"flow.{collect.spec.name}.output.prizes")

        ### --- Nodes inside the for_each loop --- Start
        stage = stage_prize_inputs(each)

        fetch = each.tool(fetch_url_data)

        fetch.map_input(
            "urls",
            f"parent.{stage.spec.name}.output.urls",
        )

        select = select_fetched_page(each)

        extract = build_prompt_extract_prize_details(each)
        extract.map_input(
            "page_content",
            f"parent.{select.spec.name}.output.page_content",
        )
        extract.map_input(
            "output_language",
            f"parent.{stage.spec.name}.output.language",
        )

        tag_generation = build_prompt_metadata_tag_generation(each)
        tag_generation.map_input(
            "generated_description",
            f"parent.{extract.spec.name}.output.generated_description",
        )
        tag_generation.map_input(
            "output_language",
            f"parent.{stage.spec.name}.output.language",
        )

        assemble = assemble_prize_record(each)
        ### --- Nodes inside the for_each loop --- End

        each.sequence(
            START,
            stage,
            fetch,
            select,
            extract,
            tag_generation,
            assemble,
            END,
        )

        table = build_prize_table(aflow)

        aflow.sequence(
            START,
            collect,
            each,
            table,
            END,
        )

        # The flow returns the flat table: `pd.DataFrame(result["rows"])`.
        aflow.map_output(
            "rows",
            f"flow.{table.spec.name}.output.rows",
        )
        aflow.map_output(
            "row_count",
            f"flow.{table.spec.name}.output.row_count",
        )
        return aflow

    return (build_prize_detail_extraction_flow,)


@app.cell
def _():
    flow_name = "prize_detail_extraction"
    return (flow_name,)


@app.cell
def _(flow_name):
    display_name = flow_name.replace("_", " ").title()
    print(display_name)
    return (display_name,)


@app.cell
def _(flow_name):
    FLOW_SPEC_PATH = f"src/flow_specs/{flow_name}.json"
    return (FLOW_SPEC_PATH,)


@app.cell(hide_code=True)
def _(FLOW_SPEC_PATH):
    def import_flow_to_wxo(aflow, path=FLOW_SPEC_PATH, dry_run=False):
        """Compile the notebook's flow and import it into the active wxo environment.

        Takes the built Flow, not the builder: @flow creates its Flow once at
        decoration time and caches it, so calling the builder a second time
        replays the body against an already-compiled flow and raises
        "Flow has already been compiled." Re-run the cell that defines the flow
        to get a fresh one.

        Uses compile() rather than compile_deploy(): the deploy half pushes the
        model straight at the active environment, and the ADK rejects flow tools
        on anything but a local server. Compiling only produces the spec, which
        is written to disk because `orchestrate tools import` takes a file path
        rather than an in-memory object.
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        definition = aflow.compile()
        definition.dump_spec(path)
        print(f"wrote {path}")

        if dry_run:
            return None

        proc = subprocess.run(
            ["orchestrate", "tools", "import", "-k", "flow", "-f", path],
            capture_output=True,
            text=True,
        )
        print(proc.stdout or "")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        return proc

    return (import_flow_to_wxo,)


@app.cell
def _():
    run_flow_import = mo.ui.run_button(label="**Import flow into wxo**")
    # run_flow_import
    return (run_flow_import,)


@app.cell
def _(build_prize_detail_extraction_flow):
    flow_import = build_prize_detail_extraction_flow()
    return (flow_import,)


@app.cell
def _(flow_import, import_flow_to_wxo, run_flow_import):
    flow_import_result = (
        import_flow_to_wxo(flow_import) if run_flow_import.value else None
    )
    return (flow_import_result,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    /// admonition | Import & Test Deployed Flow
    """)
    return


@app.cell
def _():
    from src.helpers.inference_helper_functions_v3 import InferenceClient

    # Custom helper wrapper for calling wxo and other ibm inference apis
    return (InferenceClient,)


@app.cell
def _(InferenceClient):
    flows_client = InferenceClient(
        provider="wxo",
        api_key=os.getenv("IBMCLOUD_APIKEY", ""),
        url=os.getenv("WXO_ENDPOINT", ""),
        timeout=360,
    )
    flows_client
    return (flows_client,)


@app.cell
def _(flows_client, run_flow_import):
    _refresh_flows = run_flow_import.value or True
    flows_list = flows_client.get_wxo_tools(tool_types=["wxflows", "flow"])
    flow_selection = value_select_mapping(
        pd.DataFrame(flows_list), key_col="name", value_col="id"
    )
    return (flow_selection,)


@app.cell
def _(flow_name, flow_selection):
    flow_selection_dropdown = mo.ui.dropdown(
        label="**Select flow to test :**",
        options=flow_selection,
        value=(
            flow_name
            if flow_name in flow_selection
            else (
                next(iter(flow_selection)) if len(flow_selection) > 0 else None
            )
        ),
    )
    return (flow_selection_dropdown,)


@app.cell
def _(flow_run_test, flow_selection_dropdown):
    test_stack = mo.hstack(
        [flow_selection_dropdown, flow_run_test], justify="space-around"
    )
    return (test_stack,)


@app.cell
def _():
    flow_run_test = mo.ui.run_button(label="**Test Run Deployed Flow**")
    # flow_run_test
    return (flow_run_test,)


@app.cell
def _():
    # This type of API call to wxo requires a user apikey rather than a service_id one.
    return


@app.cell
def _(run_flow_import):
    run_flow_import
    return


@app.cell
def _(flow_import_result):
    flow_import_result
    return


@app.cell
def _(filter_stack):
    filter_stack
    return


@app.cell
def _(test_stack):
    test_stack
    return


@app.cell
def _(flow_run_test, flow_selection_dropdown, flows_client, test_flow):
    if flow_run_test.value and flow_selection_dropdown.value:
        flow_result = flows_client.run_wxo_flow(
            flow_id=flow_selection_dropdown.value,
            flow_input=test_flow,
        )
    else:
        flow_result = {}
    return (flow_result,)


@app.cell
def _(flow_result):
    flow_result
    return


@app.cell
def _(flow_result):
    flow_result_table = (
        pd.DataFrame(flow_result.get("rows"))
        if flow_result is not None
        else pd.DataFrame({})
    )
    flow_result_table
    return


if __name__ == "__main__":
    app.run()
