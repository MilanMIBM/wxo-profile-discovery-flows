import marimo

__generated_with = "0.23.16"
app = marimo.App(width="columns")

with app.setup:
    import marimo as mo
    import pandas as pd
    import subprocess
    import sqlalchemy
    import psycopg2
    import datetime
    import json
    import sys
    import os

    from pathlib import Path
    from typing import List, Dict, Any
    from pydantic import BaseModel, Field, create_model
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block
    from src.helpers.wxo_schema_cleaner import clean_schema
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
    # **Respondent Profile Enrichment -- Flow Assembly**

    Assembles the logic blocks authored in the `*_node.py` notebooks into the
    end-to-end flow, then compiles and imports it into watsonx Orchestrate.

    Every logic block is imported from the `*_node.py` notebook that owns it --
    marimo's `@app.function` / `@app.class_definition` cells are module-level, so
    they import like any other symbol. Each node notebook is where a block is
    *authored and locally tested*; this notebook only *wires and ships* them.
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


@app.cell
def _():
    rewrite_tables = os.getenv("REWRITE_TABLES", False)
    return (rewrite_tables,)


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
def _(postgresql_engine, rewrite_tables):
    from sqlalchemy import text, inspect
    from sqlalchemy.dialects.postgresql import JSONB

    TABLES_DIR = "src/data/tables"
    existing = set(inspect(postgresql_engine).get_table_names())

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

    for name in ["quiz_structure", "quiz_meta", "quiz_scoring", "quiz_details"]:
        if name in existing and rewrite_tables:
            print(f"{name}: dropping existing table")
            with postgresql_engine.connect() as connection:
                connection.execute(
                    text(f'DROP TABLE IF EXISTS "{name}" CASCADE')
                )
            existing.remove(name)

        # Always recreate the table, even if it already exists
        df = pd.read_csv(f"{TABLES_DIR}/{name}.csv")
        dtype = {}
        for col in JSON_COLUMNS.get(name, []):
            if col in df.columns:
                df[col] = df[col].map(_parse_json_cell)
                dtype[col] = JSONB()
        df.to_sql(
            name,
            postgresql_engine,
            index=False,
            if_exists="replace",
            dtype=dtype,
        )
        print(f"{name}: created, loaded {len(df)} rows")
    return


@app.cell
def _():
    retrieve_number = mo.ui.number(
        label="**Control number of records to retrieve:**",
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
        engine=postgresql_engine,
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
        engine=postgresql_engine,
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
        engine=postgresql_engine,
    )
    return (quiz_scoring,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Quiz ID's and unique emails**
    """)
    return


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_ids_unique = mo.sql(
        f"""
        SELECT DISTINCT "quiz_id" FROM "quiz_meta"
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_ids_unique,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    account_ids_unique = mo.sql(
        f"""
        SELECT DISTINCT "account_id" FROM "quiz_meta"
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (account_ids_unique,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    user_emails = mo.sql(
        f"""
        SELECT DISTINCT "email" FROM "quiz_scoring"
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (user_emails,)


@app.cell
def _(user_emails):
    user_emails_list = user_emails.email.to_list()
    select_user = mo.ui.dropdown(
        label="**Select user email:**",
        options=user_emails_list,
        value=user_emails_list[0],
    )
    # select_user
    return


@app.cell
def _(account_ids_unique):
    account_id_list = account_ids_unique.account_id.to_list()
    select_account = mo.ui.dropdown(
        label="**Select account to filter by:**",
        options=account_id_list,
        # value=account_id_list[0],
    )
    # select_account
    return (select_account,)


@app.cell
def _(quiz_ids_unique):
    quiz_id_list = quiz_ids_unique.quiz_id.to_list()
    select_quiz_id = mo.ui.dropdown(
        label="**Select Quiz ID:**", options=quiz_id_list, value=quiz_id_list[0]
    )
    # select_quiz_id
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
    # Every logic block is authored and locally tested in its own *_node.py notebook; imported here so there is exactly one definition of each and this notebook only wires them together.
    from wxo_base_profile_node import (
        build_respondent_profiles,
        BuildProfilesOutput,
    )
    from wxo_sustained_engagement_level_node import (
        sustained_engagement_level,
        SustainedEngagementOutput,
    )
    from wxo_long_term_fan_node import (
        likely_long_term_brand_fan,
        BrandFanOutput,
    )

    return (
        BrandFanOutput,
        SustainedEngagementOutput,
        build_respondent_profiles,
        likely_long_term_brand_fan,
        sustained_engagement_level,
    )


@app.class_definition
class RespondentProfileItem(BaseModel):
    """One respondent profile as iterated by the foreach.

    EVERY field the downstream nodes read must be declared here. `extra="allow"`
    is not enough: the engine validates each item against this schema and drops
    whatever it does not declare, so an undeclared field arrives empty at
    `parent._current_item` even though build_respondent_profiles emitted it.

    Both scorers walk `quizzes[].submissions[]`, so `quizzes` has to be declared
    -- without it every respondent scores off an empty list. The nested levels
    stay untyped (`List[dict]`) so the whole quiz/submission/answer structure
    rides through without being spelled out.
    """

    model_config = {"extra": "allow"}

    respondent_id: str = Field(
        default="",
        description="Id of the respondent.",
    )
    account_id: str = Field(
        default="",
        description="Id of the account that the respondent belongs to.",
    )
    context_record_id: str = Field(
        default="",
        description="Identifier supplied by the flow input, else the respondent id.",
    )
    identity: Any = Field(
        default=None,
        description="Display name, email and the anonymous / owner flags.",
    )
    quizzes: List = Field(
        default_factory=list,
        description="One entry per distinct quiz, each nesting its submissions and answers.",
    )
    quizzes_num: int = Field(
        default=0,
        description="How many distinct quizzes the respondent completed.",
    )
    analysis: Any = Field(
        default=None,
        description="Results of the scorer nodes",
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _():
    @logic_block(
        display_name="Stage profile inputs", output_schema=CurrentProfileOutput
    )
    def stage_profile_inputs(flow, self, parent, json):
        """Publishes this iteration's respondent profile as a node output so the scorers downstream have a named handle to map from.

        Reads:  parent._current_item -- the profile for this iteration
        Writes: self.output.profile"""
        current_profile = dict(parent._current_item) or {}

        self.output.profile = current_profile

    return (stage_profile_inputs,)


@app.class_definition
class CurrentProfileOutput(BaseModel):
    """Output for the stage_profile_inputs node."""

    profile: Any = Field(
        default_factory=None,
        description="Current profile in the flow",
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _():
    @logic_block(
        display_name="Merge profile signals",
        output_schema=MergeProfileOutput,
    )
    def merge_profile_signals(flow, self, parent, json):
        """Copies the current respondent profile and attaches an `analysis` block holding one entry per upstream scorer, keyed by the scorer's name and carrying that scorer's result.

        Reads:  parent._current_item -- the profile for this iteration
                self.input.<scorer>  -- that scorer's `result` dict
        Writes: self.output.enriched_profile -- profile + analysis
                self.output.preview_inputs   -- raw signal bag, for debugging

        Node-name agnostic: walks self.input rather than naming any scorer, and
        each input field is named after the node that feeds it, so the field
        name becomes the analysis key with no lookup table here. Adding a
        scorer needs a field on MergeProfileInputs and a map_input in the flow,
        nothing in this body."""

        enriched_profile = dict(
            parent.stage_profile_inputs.output.profile or {}
        )

        ### Ay additional scorer nodes added should be appended into scorers
        scorers = {
            "sustained_engagement_level": (
                parent.sustained_engagement_level.output.result or {}
            ),
            "likely_long_term_brand_fan": (
                parent.likely_long_term_brand_fan.output.result or {}
            ),
        }
        inputs = dict(scorers or {})
        ### ---------------------------------------------------------------

        analysis = {}
        for scorer_name, result in inputs.items():
            if result is None:
                continue
            if isinstance(result, dict) and isinstance(
                result.get("result"), dict
            ):
                result = result["result"]
            analysis[scorer_name] = result

        enriched_profile["analysis"] = analysis

        self.output.enriched_profile = enriched_profile
        self.output.preview_inputs = inputs

        # The foreach exposes no readable aggregate of its iterations, so each
        # iteration appends its own record to the flow-scoped list that
        # build_profile_table reads once the loop is done.
        collected = flow["private"].get("enriched_profiles") or []
        flow.private.enriched_profiles = collected + [enriched_profile]

    return (merge_profile_signals,)


@app.class_definition
class MergeProfileOutput(BaseModel):
    """merge_profile_signals' output -- same auto-typing problem as
    BuildProfilesOutput, and this one is the flow's final result, so a
    stringified `profile` here means every run returns unusable output."""

    model_config = {"extra": "allow"}

    enriched_profile: Any = Field(
        default_factory=None,
        description="The respondent profile plus every signal the scorers contributed.",
    )
    preview_inputs: Any = Field(
        default_factory=None,
        description="Preview inputs from the flow for debugging purposes",
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _():
    @logic_block(
        display_name="Build profile table",
        output_schema=ProfileTableOutputs,
    )
    def build_profile_table(flow, self, parent, json, each):
        """Turns the loop's enriched profile records into a table, decomposing `analysis` and `identity` one level into dot-notation columns.

        Runs ONCE, after the foreach -- it reads the whole accumulated list, not a
        single item, so it sits outside the loop where `parent._current_item` is
        meaningless.

        Reads:  parent.<for_each_flow_name>.<last_node_name>.output -- the for_each's aggregated per-iteration outputs
        Writes: self.output.rows      -- one row per respondent
                self.output.row_count -- how many rows were produced
                self.output.enriched_profiles -- the records as they arrived

        Nothing is dropped: every key on the record survives into the row. Only
        `analysis` and `identity` are decomposed, one level, into
        `analysis.<scorer>` / `identity.<field>` columns -- pandas would
        otherwise collapse each into a single object-dtype column. The
        decomposition is generic (it walks whatever keys are present rather than
        naming scorers) and stops at one level, so a scorer's own nested result
        stays whole in its cell."""
        inputs = (
            {"rows": parent.each_respondent.merge_profile_signals.output}
            if isinstance(
                parent.each_respondent.merge_profile_signals.output, list
            )
            else (
                parent.each_respondent.merge_profile_signals.output
                if isinstance(
                    parent.each_respondent.merge_profile_signals.output, dict
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
            collected = flow["private"].get("enriched_profiles")
            if isinstance(collected, list):
                rows_in = collected

        DECOMPOSE = ("analysis", "identity")

        rows_out = []
        for entry in rows_in:
            if not isinstance(entry, dict):
                continue

            row = {}
            for key, value in entry.items():
                # One level only: each child becomes `key.child`, and whatever
                # the child holds is left exactly as it is.
                if key in DECOMPOSE and isinstance(value, dict):
                    for sub_key, sub_value in value.items():
                        row[f"{key}.{sub_key}"] = sub_value
                else:
                    row[key] = value

            rows_out.append(row)

        self.output.rows = rows_out
        self.output.row_count = len(rows_out)
        self.output.enriched_profiles = rows_in
        self.output.preview_inputs = inputs

    return (build_profile_table,)


@app.class_definition
### build_profile_table - Output Schema
class ProfileTableOutputs(BaseModel):
    """Outputs of the build_profile_table script node.

    `rows` is typed as plain dicts rather than RespondentProfileItem: the rows
    carry the decomposed `analysis.<scorer>` / `identity.<field>` columns, which
    the item schema does not declare, and the engine drops whatever the declared
    schema does not name. `enriched_profiles` carries the same records with
    nothing decomposed.
    """

    rows: List[dict] = Field(
        default_factory=list,
        description="One flat row per respondent, ready to load straight into a dataframe.",
    )
    row_count: int = Field(
        default=0, description="How many respondent rows were produced."
    )
    enriched_profiles: List[dict] = Field(
        default_factory=list,
        description="The full nested profile documents, one per respondent, before flattening.",
    )
    preview_inputs: Any = Field(
        default=None,
        description="The inputs preview for debugging",
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
class ProfileFlowPrivate(BaseModel):
    """Internal accumulator for the for_each loop.

    The foreach node exposes no readable aggregate of its iterations: its
    `output_schema` is deprecated and populates nothing, and mapping the loop's
    output (whole or by leaf) into a downstream node yields empty. So each
    iteration appends its own record to this flow-scoped list instead, and
    build_profile_table reads the finished list after the loop.

    flow.private.* is flow-scoped rather than node-scoped, which is what lets a
    node inside the subflow write somewhere a node outside it can read.
    """

    model_config = {"extra": "allow"}

    base_profiles: Any = Field(
        default_factory=None,
        description="One record per completed iteration.",
    )
    enriched_profiles: List[dict] = Field(
        default_factory=list,
        description="The full nested profile documents, one per respondent, before flattening.",
    )


@app.class_definition
### Flow-level Output Schema
class ProfileFlowOutput(BaseModel):
    """Final output of the respondent_profile_enrichment flow.

    `rows` is a flat list of one dict per profile, every value a scalar, so
    `pd.DataFrame(result["rows"])` yields a table directly with no further
    unnesting. Typed as `dict` for the same reason as ProfileTableOutputs.rows:
    RespondentProfileItem describes the nested loop item, not this flat row, and
    the engine drops whatever the declared schema does not name.
    """

    rows: List[dict] = Field(
        default_factory=list,
        description="One flat row per profile, ready to load straight into a dataframe.",
    )
    row_count: int = Field(
        default=0, description="How many profile rows were produced."
    )
    enriched_profiles: List[dict] = Field(
        default_factory=list,
        description="The full nested profile documents, one per respondent, before flattening.",
    )


@app.cell
def _(
    BrandFanOutput,
    SustainedEngagementOutput,
    build_profile_table,
    build_respondent_profiles,
    display_name,
    flow_name,
    likely_long_term_brand_fan,
    merge_profile_signals,
    stage_profile_inputs,
    sustained_engagement_level,
):
    @flow(
        name=flow_name,
        display_name=display_name,
        output_schema=ProfileFlowOutput,
        private_schema=ProfileFlowPrivate,
        description=(
            """Builds one profile per quiz respondent from the raw quiz tables, then scores each respondent's sustained engagement level and long-term brand affinity concurrently, returning the profiles enriched with both signals."""
        ),
    )
    def build_respondent_profile_enrichment_flow(aflow: Flow) -> Flow:

        build_profiles = build_respondent_profiles(aflow)

        each: Flow = aflow.foreach(
            item_schema=RespondentProfileItem,
            name="each_respondent",
            display_name="Create Profile For Each Respondent",
            # ).policy(kind=ForeachPolicy.SEQUENTIAL)
        ).policy(kind=ForeachPolicy.PARALLEL)

        each.map_input(
            "items",
            f"parent.{build_profiles.spec.name}.output.base_profiles",
        )

        stage = stage_profile_inputs(each, output_schema=CurrentProfileOutput)

        engagement = sustained_engagement_level(
            each, output_schema=SustainedEngagementOutput
        )

        brand_fan = likely_long_term_brand_fan(
            each, output_schema=BrandFanOutput
        )

        merge = merge_profile_signals(
            each,
            output_schema=MergeProfileOutput,
        )

        each.sequence(
            START,
            stage,
            engagement,
            brand_fan,
            merge,
            END,
        )

        # Sits OUTSIDE the loop: it reads the whole accumulated list once, after
        # every iteration has appended to flow.private.enriched_profiles.
        table = build_profile_table(aflow, output_schema=ProfileTableOutputs)

        aflow.sequence(
            START,
            build_profiles,
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
        aflow.map_output(
            "enriched_profiles",
            f"flow.{table.spec.name}.output.enriched_profiles",
        )
        return aflow

    return (build_respondent_profile_enrichment_flow,)


@app.cell
def _():
    flow_name = "respondent_profile_enrichment"
    return (flow_name,)


@app.cell
def _(flow_name):
    from networkx import display

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
    return (run_flow_import,)


@app.cell
def _(build_respondent_profile_enrichment_flow):
    flow_import = build_respondent_profile_enrichment_flow()
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
        label="**Select flow to test:**",
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
def _():
    # This type of API call to wxo requires a user apikey rather than a service_id one.
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
