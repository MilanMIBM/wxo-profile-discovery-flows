import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")

with app.setup(hide_code=True):
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
    from dotenv import load_dotenv

    ### --- Only use if you nest it in a subfolder ---
    # parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # if parent_dir not in sys.path:
    #     sys.path.insert(0, parent_dir)
    ### --- --- --- --- ---

    from sqlalchemy import text, inspect
    from sqlalchemy.dialects.postgresql import JSONB
    from pymongo import MongoClient

    # Custom helper imports
    from src.helpers.ensure_wxo_env import ensure_wxo_env
    from src.helpers.logic_block import logic_block
    from src.helpers.inference_helper_functions_v3 import InferenceClient
    from src.helpers.marimo_ui_helpers import accordion_preview
    from src.helpers.marimo_floating_card_view_v2 import floating_card_view
    from src.helpers.mongodb_document_helpers import (
        upload_documents,
        update_documents,
        purge_documents,
        retrieve_documents,
    )

    wxo_env_status = ensure_wxo_env(env_file="config/.env", reactivate=True)
    load_dotenv("config/.env", override=True)
    print(wxo_env_status)


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


@app.cell(hide_code=True)
def _(postgresql_engine):
    # Drop existing tables before reloading them from CSV. Compare the string, since
    # bool("False") is True.
    rewrite_tables = os.getenv("REWRITE_TABLES", "false").lower() == "true"
    print(f"Rewrite tables: {rewrite_tables}")

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
    pg_endpoint = os.path.expandvars(os.getenv("POSTGRESQL_ENDPOINT", ""))
    mongodb_endpoint = os.path.expandvars(os.getenv("MONGODB_ENDPOINT", ""))
    return mongodb_endpoint, pg_endpoint


@app.cell
def _():
    ibmcloud_cert_path = os.path.expandvars(
        os.getenv("IBMCLOUD_DB_CERT_PATH", "")
    )
    return (ibmcloud_cert_path,)


@app.cell
def _(pg_endpoint):
    postgresql_engine = sqlalchemy.create_engine(
        pg_endpoint, connect_args={"sslmode": "require"}
    )
    return (postgresql_engine,)


@app.cell
def _(ibmcloud_cert_path, mongodb_endpoint):
    if ibmcloud_cert_path:
        mongodb_client = MongoClient(
            mongodb_endpoint,
            tls=True,
            tlsCAFile=ibmcloud_cert_path or None,
        )
        mongodb = mongodb_client.get_default_database()
        print(mongodb)
        print(
            f"Existing MongoDB collections: {mongodb.list_collection_names()}"
        )
    else:
        mongodb_client = MongoClient(mongodb_endpoint)
        mongodb = mongodb_client.get_default_database()
        print(mongodb)
        print(
            f"Existing MongoDB collections: {mongodb.list_collection_names()}"
        )
    return mongodb, mongodb_client


@app.cell
def _():
    flows_client = InferenceClient(
        provider="wxo",
        api_key=os.getenv("IBMCLOUD_APIKEY") or os.getenv("WXO_APIKEY", ""),
        url=os.getenv("WXO_ENDPOINT", ""),
        timeout=360,
    )
    # flows_client
    return (flows_client,)


@app.cell
def _():
    refresh_flow_list = mo.ui.run_button(
        label="**Refresh watsonx orchestrate flow list**"
    )
    return (refresh_flow_list,)


@app.cell
def _(flows_client, refresh_flow_list):
    _refresh_flows = refresh_flow_list.value or True
    flows_list = flows_client.get_wxo_tools(tool_types=["wxflows", "flow"])
    flow_selection = value_select_mapping(
        pd.DataFrame(flows_list), key_col="name", value_col="id"
    )
    return (flow_selection,)


@app.cell
def _(flow_selection):
    flow_selection_dropdown = mo.ui.dropdown(
        label="**Select flow to test:**",
        options=flow_selection,
        value=(next(iter(flow_selection)) if len(flow_selection) > 0 else None),
    )
    return (flow_selection_dropdown,)


@app.cell
def _():
    retrieve_number = mo.ui.number(
        label="**Control number of records to retrieve:**",
        start=0,
        stop=1000,
        step=1,
        value=2,
    )
    # retrieve_number
    return (retrieve_number,)


@app.cell
def _(retrieve_number):
    limit = int(retrieve_number.value) or 10
    return (limit,)


@app.cell
def _(retrieve_number, select_account):
    filter_stack = mo.hstack(
        [select_account, retrieve_number], justify="space-around"
    )
    # filter_stack
    return (filter_stack,)


@app.cell
def _():
    flow_run_test = mo.ui.run_button(label="**Test Run Deployed Flow**")
    # flow_run_test
    return (flow_run_test,)


@app.cell
def _(flow_run_test, flow_selection_dropdown, run_flow_async):
    test_stack = mo.hstack(
        [flow_selection_dropdown, run_flow_async, flow_run_test],
        justify="space-around",
    )
    return (test_stack,)


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
    quiz_id_list = quiz_ids_unique.quiz_id.to_list()
    select_quiz_id = mo.ui.dropdown(
        label="**Select Quiz ID:**", options=quiz_id_list, value=quiz_id_list[0]
    )
    # select_quiz_id
    return


@app.cell
def _():
    # --- SQL cells ----
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
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


@app.cell(hide_code=True)
def _(limit, postgresql_engine, select_account):
    if select_account.value:
        quiz_meta = mo.sql(
            f"""
            SELECT * FROM "quiz_meta"
            WHERE "account_id" = '{select_account.value}'
            LIMIT {limit}
            """,
            engine=postgresql_engine,
            output=False,
        )
    else:
        quiz_meta = mo.sql(
            f"""
            SELECT * FROM "quiz_meta"
            LIMIT {limit}
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
def _(quiz_details, quiz_meta, quiz_scoring, quiz_structure):
    preview_tables_accordion = accordion_preview(
        name="#### **Preview Data Tables from PostgreSQL**",
        nest_accordion=True,
        nested_value=[quiz_meta, quiz_structure, quiz_details, quiz_scoring],
    )
    return (preview_tables_accordion,)


@app.cell
def _(preview_tables_accordion):
    preview_tables_accordion
    return


@app.cell
def _(filter_stack):
    filter_stack
    return


@app.cell
def _():
    return


@app.cell
def _(test_stack):
    test_stack
    return


@app.cell
def _():
    run_flow_async = mo.ui.switch(label="**Run Flow Async**", value=False)
    return (run_flow_async,)


@app.cell
def _(
    flow_run_test,
    flow_selection_dropdown,
    flows_client,
    run_flow_async,
    test_flow,
):
    if (
        flow_run_test.value
        and flow_selection_dropdown.value
        and run_flow_async.value
    ):
        flow_invoke = flows_client.run_wxo_flow_async(
            flow_id=flow_selection_dropdown.value,
            flow_input=test_flow,
            retries=1,
            auto_retrieve=True,
            retrieve_interval=10,
            max_checks=3,
        )
        flow_result = flow_invoke.retrieve()
    elif flow_run_test.value and flow_selection_dropdown.value:
        flow_result = flows_client.run_wxo_flow(
            flow_id=flow_selection_dropdown.value,
            flow_input=test_flow,
            retries=1,
        )
    else:
        flow_result = {}
    return (flow_result,)


@app.cell
def _(flow_result):
    flow_result_as_table = (
        pd.DataFrame(flow_result.get("rows"))
        if flow_result is not None
        else pd.DataFrame({})
    )
    return (flow_result_as_table,)


@app.cell
def _(flow_result, flow_result_as_table):
    result_accordion = accordion_preview(
        name="#### **View Flow Results**",
        nest_accordion=True,
        nested_value=[flow_result, flow_result_as_table],
    )
    return (result_accordion,)


@app.cell
def _(result_accordion):
    result_accordion
    return


@app.cell
def _():
    import_documents_to_mongodb = mo.ui.run_button(
        label="**Import output records into MongoDB**"
    )
    return (import_documents_to_mongodb,)


@app.cell
def _(import_documents_to_mongodb, on_existing_documents):
    mo.hstack(
        [import_documents_to_mongodb, on_existing_documents],
        justify="start",
        gap=3,
    )
    return


@app.cell
def _(flow_selection_dropdown):
    mongodb_collection_name = flow_selection_dropdown.selected_key
    print(f"MongoDB collection name: {mongodb_collection_name}")
    return (mongodb_collection_name,)


@app.cell
def _():
    on_existing_documents = mo.ui.dropdown(
        label="**On existing document:**",
        options=["update", "overwrite", "skip"],
        value="overwrite",
    )
    return (on_existing_documents,)


@app.cell
def _(
    flow_result,
    import_documents_to_mongodb,
    mongodb,
    mongodb_collection_name,
    on_existing_documents,
):
    if import_documents_to_mongodb.value and flow_result:
        mongodb_import_docs = upload_documents(
            mongodb,
            mongodb_collection_name,
            flow_result.get("enriched_profiles")
            or flow_result.get("rows")
            or [],
            check_for_existing="respondent_id",
            on_existing=str(on_existing_documents.value) or "overwrite",
            clean=True,
            verbose=True,
        )
    else:
        mongodb_import_docs = None
    return (mongodb_import_docs,)


@app.cell
def _(mongodb_import_docs):
    mongodb_import_docs
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ---
    """)
    return


@app.cell
def _():
    retrieve_documents_test = mo.ui.run_button(
        label="**Retrieve MongoDB Documents Test**"
    )
    return (retrieve_documents_test,)


@app.cell
def _(retrieve_documents_test):
    retrieve_documents_test
    return


@app.cell
def _(
    mongodb,
    mongodb_client,
    mongodb_collection_name,
    retrieve_documents_test,
):
    if (
        mongodb_client
        and mongodb_collection_name
        and retrieve_documents_test.value
    ):
        retrieve_mongodb_documents = retrieve_documents(
            mongodb, mongodb_collection_name
        )
        view_retrieved_mongodb_docs = accordion_preview(
            floating_card_view(retrieve_mongodb_documents),
            name="**Preview MongoDB documents as floating cards**",
            nested_value=[retrieve_mongodb_documents],
            nested_name="retrieve_mongodb_documents JSON list",
        )
    else:
        retrieve_mongodb_documents = view_retrieved_mongodb_docs = None
    return (view_retrieved_mongodb_docs,)


@app.cell
def _(view_retrieved_mongodb_docs):
    view_retrieved_mongodb_docs
    return


if __name__ == "__main__":
    app.run()
