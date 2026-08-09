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
    from typing import List, Optional
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


@app.cell
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
                connection.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
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
        value=50,
    )
    retrieve_number
    return (retrieve_number,)


@app.cell(hide_code=True)
def _(postgresql_engine, retrieve_number):
    quiz_meta = mo.sql(
        f"""
        SELECT * FROM "quiz_meta" LIMIT {retrieve_number.value}
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_meta,)


@app.cell(hide_code=True)
def _(postgresql_engine, quiz_meta):
    quiz_structure = mo.sql(
        f"""
        SELECT * FROM "quiz_structure"
        WHERE "quizId" IN ({",".join(map(repr, quiz_meta["quizId"].to_list())) or "NULL"})
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
        WHERE "quizId" IN ({",".join(map(repr, quiz_meta["quizId"].to_list())) or "NULL"})
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
        WHERE "quizId" IN ({",".join(map(repr, quiz_meta["quizId"].to_list())) or "NULL"})
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
        SELECT DISTINCT "quizId" FROM "quiz_structure"
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_ids_unique,)


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
def _(quiz_ids_unique):
    quiz_id_list = quiz_ids_unique.quizId.to_list()
    select_quiz_id = mo.ui.dropdown(
        label="**Select Quiz ID:**", options=quiz_id_list, value=quiz_id_list[0]
    )
    # select_quiz_id
    return


@app.function
def as_table_entry(name, df):
    """Shape a dataframe like one `retrieve_database_tables` result entry."""
    # mo.sql returns pandas here (.to_dict(orient="records")), but returns polars, (.to_dicts()) when marimo's dataframe backend is switched, so accept both.
    rows = df.to_dicts() if hasattr(df, "to_dicts") else df.to_dict(orient="records")
    return {
        "table": name,
        "rows": [jsonable_row(r) for r in rows],
    }


@app.function
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
            return None if val != val or val in (float("inf"), float("-inf")) else val
        if isinstance(val, decimal.Decimal):
            return float(val)
        if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
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
    test_flow = {"output": db_records}
    return (test_flow,)


@app.cell
def _():
    run_tests = mo.ui.run_button(label="Run Node Tests")
    return


@app.cell(column=1, hide_code=True)
def _():
    mo.md(r"""
    ### Class definitions
    """)
    return


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

    respondent_id: Optional[str] = Field(
        default=None, description="Id of the respondent."
    )
    context_record_id: Optional[str] = Field(
        default=None,
        description="Identifier supplied by the flow input, else the respondent id.",
    )
    identity: Optional[dict] = Field(
        default=None,
        description="Display name, email and the anonymous / owner flags.",
    )
    quizzes: List[dict] = Field(
        default_factory=list,
        description="One entry per distinct quiz, each nesting its submissions and answers.",
    )
    quizzes_num: Optional[int] = Field(
        default=None,
        description="How many distinct quizzes the respondent completed.",
    )


@app.cell
def _():
    # class BuildProfilesOutput(BaseModel):
    #     """build_respondent_profiles' output.

    #     Without this, Flow.script() auto-generates an output_schema from the
    #     script's `self.output.X = ...` assignments and -- since it can't infer a
    #     real type from a plain assignment -- always defaults every field to
    #     `string`. That mistypes `profiles` as a string instead of an array, and
    #     the foreach's `items` (mapped from this field) receives it accordingly.
    #     """

    #     profiles: List[RespondentProfileItem] = Field(
    #         default_factory=list,
    #         description="One profile per respondent, nesting quizzes/submissions/answers.",
    #     )
    #     # Run counters live on the node's public output rather than flow.private:
    #     # flow.private.* requires a private_schema on the @flow decorator, and an
    #     # undeclared private write fails inside the first node and kills the run.
    #     # Downstream nodes simply ignore them unless mapped in.
    #     profiles_num: Optional[int] = Field(
    #         default=None, description="How many profiles were built this run."
    #     )
    #     uploaded_num: Optional[int] = Field(
    #         default=None, description="Upload counter, zeroed for this run."
    #     )
    return


@app.class_definition
class MergeProfileInputs(BaseModel):
    """Inputs of the merge_profile_signals script node.

    Declared so the engine AUTO-MAPS them: explicit expressions cannot reach a
    node inside the score_respondent parallel from outside it (every variant
    tried in the prize flow's identical topology resolved to nothing), but
    auto-mapping demonstrably crosses that boundary. Auto-mapping matches on
    names and descriptions, so each description names its source node
    explicitly to keep the binding unambiguous."""

    engagement: Optional[dict] = Field(
        default=None,
        description="The `result` dict emitted by the sustained_engagement_level script node: respondent_id plus the sustained_engagement_level bracket that qualified.",
    )
    brand_fan: Optional[dict] = Field(
        default=None,
        description="The `result` dict emitted by the likely_long_term_brand_fan script node: respondent_id plus the respondent_behavioral_metatags list.",
    )


@app.class_definition
class MergeProfileOutput(BaseModel):
    """merge_profile_signals' output -- same auto-typing problem as
    BuildProfilesOutput, and this one is the flow's final result, so a
    stringified `profile` here means every run returns unusable output."""

    model_config = {"extra": "allow"}

    profile: Optional[dict] = Field(
        default=None,
        description="The respondent profile plus every signal the scorers contributed.",
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.cell
def _():
    # Every logic block is authored and locally tested in its own *_node.py
    # notebook; imported here so there is exactly one definition of each and
    # this notebook only wires them together.
    from wxo_base_profile_node import (
        build_respondent_profiles,
        merge_profile_signals,
    )
    from wxo_sustained_engagement_level_node import (
        sustained_engagement_level,
    )
    from wxo_long_term_fan_node import likely_long_term_brand_fan

    return (
        build_respondent_profiles,
        likely_long_term_brand_fan,
        merge_profile_signals,
        sustained_engagement_level,
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


@app.cell
def _(
    build_respondent_profiles,
    display_name,
    flow_name,
    likely_long_term_brand_fan,
    merge_profile_signals,
    sustained_engagement_level,
):
    @flow(
        name=flow_name,
        display_name=display_name,
        description=(
            "Builds one profile per quiz respondent from the raw quiz tables, then scores "
            "each respondent's sustained engagement level and long-term brand affinity "
            "concurrently, returning the profiles enriched with both signals."
        ),
    )
    def build_respondent_profile_enrichment_flow(aflow: Flow) -> Flow:
        # Collapses the table bundle into one record per respondent. Runs ONCE,
        # before the loop -- it reads whole tables and emits the list to iterate.
        #
        # output_schema is explicit: without it, Flow.script() infers one from
        # the script body and always types every self.output.X field as a bare
        # string, which mistypes `profiles` (an array of profile objects) and
        # breaks the foreach's `items` mapping downstream.
        build_profiles = build_respondent_profiles(
            aflow,
            # output_schema=BuildProfilesOutput,
        )

        # One iteration per respondent; PARALLEL since respondents are independent.
        each: Flow = aflow.foreach(
            item_schema=RespondentProfileItem,
            name="for_each_respondent",
            display_name="For each respondent",
        ).policy(kind=ForeachPolicy.PARALLEL)

        # REQUIRED: foreach with no input_schema auto-generates a required
        # "items" input -- sequencing build_profiles -> each only orders execution, it
        # does not map build_profiles's output.profiles onto that "items" field. Without
        # this map the foreach never receives anything to iterate and nothing
        # downstream runs.
        #
        # `flow.`, not `parent.` or `self.`: input-map expressions address a
        # sibling node's output as `flow.<nodeName>.output.<field>` (the root
        # the ADK's own mapping helper and the official datamap example use).
        # `parent` only reaches the enclosing scope from inside a subflow --
        # at top level it resolves to nothing, the required "items" input
        # stays empty, and the flow dies right here after the first node.
        each.map_input(
            "items", f"flow.{build_profiles.spec.name}.output.profiles"
        )  # we have to add .data to .output in this case as we are nesting several flows within each other.

        # Both scorers run concurrently. Each branch is wired START -> node -> END
        # inside the parallel subflow; that internal END is the join, so `merge`
        # runs only once both have finished.
        scorers: Flow = each.parallel(
            evaluator=None,
            name="score_respondent",
            display_name="Score respondent",
        )

        scorers.map_input(
            "items",
            f"flow.{build_profiles.spec.name}.output.profiles",
        )

        engagement = sustained_engagement_level(scorers)
        # engagement.map_input(
        #     "profiles",
        #     f"parent.{each.spec.name}.output",
        # )

        brand_fan = likely_long_term_brand_fan(scorers)
        # brand_fan.map_input(
        #     "profiles",
        #     f"parent.{each.spec.name}.output",
        # )

        scorers.sequence(START, engagement, END)
        scorers.sequence(START, brand_fan, END)

        # Adds both scorers' results onto this iteration's profile. NO explicit
        # maps here: engagement/brand_fan live inside the score_respondent
        # parallel, and no explicit expression variant (`self.<node>`,
        # `flow.<node>`, chained `flow.<parallelName>.<node>`) resolved an
        # inner node from outside it in the prize flow's identical topology --
        # the defaults filled in instead. Auto-mapping is what crosses that
        # boundary in practice, so merge declares MergeProfileInputs and lets
        # the engine bind each scorer's `result` dict to it -- exactly the
        # shape merge_profile_signals' absorb() flattens onto the profile.
        #
        # output_schema is explicit here too -- same reason as build_respondent_profiles
        # above: without it `profile` would be auto-typed as a bare string.
        merge = merge_profile_signals(
            each,
            input_schema=MergeProfileInputs,
            output_schema=MergeProfileOutput,
        )
        each.sequence(START, scorers, merge, END)

        aflow.sequence(START, build_profiles, each, END)
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


@app.cell
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
    run_flow_import
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
    flow_import_result
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    /// admonition | Test Deployed Flow
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
    )
    flows_client
    return (flows_client,)


@app.function
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
            else (next(iter(flow_selection)) if len(flow_selection) > 0 else None)
        ),
    )
    flow_selection_dropdown
    return (flow_selection_dropdown,)


@app.cell
def _(flow_selection_dropdown):
    print(flow_selection_dropdown.value)
    return


@app.cell
def _():
    flow_run_test = mo.ui.run_button(label="Test Run Deployed Flow")
    flow_run_test
    return (flow_run_test,)


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
        flow_result = None
    return (flow_result,)


@app.cell
def _(flow_result):
    flow_result
    return


if __name__ == "__main__":
    app.run()
