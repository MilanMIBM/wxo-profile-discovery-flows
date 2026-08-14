import marimo

__generated_with = "0.23.16"
app = marimo.App(width="columns")

with app.setup:
    import marimo as mo
    import pandas as pd
    import subprocess
    import sqlalchemy
    import datetime
    import psycopg2
    import json
    import sys
    import os

    from pathlib import Path
    from pydantic import BaseModel, Field
    from typing import List, Dict, Any
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block

    class BuildProfilesOutput(BaseModel):
        """build_respondent_profiles' output.

        Without this, Flow.script() auto-generates an output_schema from the
        script's `self.output.X = ...` assignments and -- since it can't infer a
        real type from a plain assignment -- always defaults every field to
        `string`. That mistypes `profiles` as a string instead of an array, and
        the foreach's `items` (mapped from this field) receives it accordingly.
        """

        base_profiles: List[dict] = Field(
            default_factory=list,
            description="One profile per respondent, nesting quizzes/submissions/answers.",
        )
        profiles_num: int = Field(
            default=0, description="How many profiles were built this run."
        )
        uploaded_num: int = Field(
            default=0, description="Upload counter, zeroed for this run."
        )
        preview_inputs: Any = Field(
            default=dict,
            description="Preview inputs from the flow for debugging purposes",
        )


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


@app.cell(hide_code=True)
def _(postgresql_engine):
    from sqlalchemy import text, inspect
    from sqlalchemy.dialects.postgresql import JSONB

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
                connection.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
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
    filter_stack = mo.hstack([select_account, retrieve_number], justify="space-around")
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
        engine=postgresql_engine
    )
    return (quiz_ids_unique,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    account_ids_unique = mo.sql(
        f"""
        SELECT DISTINCT "account_id" FROM "quiz_meta"
        """,
        output=False,
        engine=postgresql_engine
    )
    return (account_ids_unique,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    user_emails = mo.sql(
        f"""
        SELECT DISTINCT "email" FROM "quiz_scoring"
        """,
        output=False,
        engine=postgresql_engine
    )
    return (user_emails,)


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


@app.cell
def _(user_emails):
    user_emails_list = user_emails.email.to_list()
    select_user = mo.ui.dropdown(
        label="**Select user email :**",
        options=user_emails_list,
        value=user_emails_list[0],
    )
    # select_user
    return (select_user,)


@app.cell
def _(quiz_ids_unique):
    quiz_id_list = quiz_ids_unique.quiz_id.to_list()
    select_quiz_id = mo.ui.dropdown(
        label="**Select Quiz ID :**",
        options=quiz_id_list,
        value=quiz_id_list[0],
    )
    # select_quiz_id
    return


@app.function(hide_code=True)
def as_table_entry(name, df):
    """Shape a dataframe like one `retrieve_database_tables` result entry."""
    # mo.sql returns pandas here (.to_dict(orient="records")), but returns polars, (.to_dicts()) when marimo's dataframe backend is switched, so accept both.
    rows = df.to_dicts() if hasattr(df, "to_dicts") else df.to_dict(orient="records")
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
    test_flow = {"retrieved_tables": db_records}
    return (test_flow,)


@app.cell
def _():
    run_tests = mo.ui.run_button(label="Run Node Tests")
    return (run_tests,)


@app.cell(column=1, hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.function
@logic_block(
    display_name="Build respondent profiles",
    output_schema=BuildProfilesOutput,
)
def build_respondent_profiles(flow, self, parent, json):
    """Builds one profile per quiz respondent from the raw table bundle, nesting each respondent's quizzes, submissions and answers.

    Runs in the flow engine's restricted sandbox, NOT as a normal module:
    `flow`, `self` and `parent` are injected, `json` is pre-bound (no imports),
    and there is no return value -- output happens by assignment. The
    parameters exist so linters resolve those names; the engine never calls
    this function.

    Reads:  the table bundle (scoring + details + quiz_meta) from the flow's own
            input -- bare, or nested under "retrieved_tables" / an "output"
            wrapper. This is the first node in the flow, so there is no
            upstream node to read from.
    Writes: self.output.profiles      -- list of base profiles, one per respondent
            self.output.profiles_num  -- how many were built
            self.output.uploaded_num  -- upload counter, zeroed for this run"""

    # Normally a bare list of {"table": ..., "rows": [...]} entries, but a
    # caller passing a retrieval node's context through verbatim wraps it.
    flow_input = flow["input"] or {}
    tables = flow_input.get("retrieved_tables")
    if isinstance(tables, dict):
        tables = tables.get("output")
    if not isinstance(tables, list):
        tables = []

    identifier = flow["input"].get("identifier")

    # Best-effort int, 0 on missing/unparseable.
    def as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):  # fmt: skip
            return 0

    # DB rows arrive typed, CSV-style rows arrive as strings.
    def as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "t")
        return bool(value)

    # Tags are stored as JSON-array strings ('["a","b"]') but may also arrive
    # as a real list, empty, or "[]". Normalise to a list or None.
    def parse_tags(value):
        if value is None:
            return None
        if isinstance(value, list):
            return value or None
        if isinstance(value, str):
            s = value.strip()
            if s in ("", "[]"):
                return None
            try:
                parsed = json.loads(s)
            except ValueError:
                return None
            return parsed if isinstance(parsed, list) and parsed else None
        return None

    by_table = {t.get("table"): (t.get("rows") or []) for t in tables}
    scoring = by_table.get("scoring") or []
    details = by_table.get("details") or []
    quiz_meta = by_table.get("quiz_meta") or []

    # Step 1: quiz context keyed by quiz_id, nesting the flat prize.* columns
    # into a `prize` object.
    ctx = {}
    for m in quiz_meta:
        qid = m.get("quiz_id")
        if qid is None:
            continue
        prize = {
            "prize_name": m.get("prize.prize_name") or None,
            "prize_url": m.get("prize.prize_url") or None,
            "prize_value": m.get("prize.prize_value") or None,
            "prize_currency": m.get("prize.prize_currency") or None,
            "prize_description": m.get("prize.prize_description") or None,
        }
        if not any(prize.values()):
            prize = None
        ctx[qid] = {
            "account_id": m.get("account_id"),
            "title": m.get("title"),
            "status": m.get("status"),
            "brand_name": m.get("brand_name"),
            "brand_tags": parse_tags(m.get("brand_tags")),
            "language": m.get("language"),
            "prize": prize,
            "prize_type": parse_tags(m.get("prize_type")),
        }

    # Step 2: answers grouped by submission_id.
    answers_by_sub = {}
    for d in details:
        sid = d.get("submission_id")
        if sid is None:
            continue
        answers_by_sub.setdefault(sid, []).append(
            {
                "submission_id": sid,
                "question": d.get("question"),
                "answer": d.get("answer"),
                "correct": as_bool(d.get("correct")),
            }
        )

    # Step 3: group scoring by respondent (email), bucketing per quiz. One
    # scoring row == one submission. `quiz_index` maps quiz_id -> bucket within
    # the current respondent, so repeat submissions accumulate rather than
    # opening a second bucket for the same quiz.
    profiles = {}
    order = []
    for s in scoring:
        email = s.get("email")
        key = email if email is not None else s.get("submission_id")
        if key not in profiles:
            profiles[key] = {
                "respondent_id": s.get("submission_id"),
                # Sourced from quiz_meta via ctx (scoring rows carry no
                # account_id); filled from the first quiz row that resolves.
                "account_id": None,
                "identity": {
                    "display_name": s.get("display_name"),
                    "email": email,
                    "anonymous": as_bool(s.get("anonymous")),
                    "is_owner": as_bool(s.get("is_owner")),
                    "placeholder_email": bool(email) and email.startswith("temp@"),
                },
                "quiz_index": {},
                "quizzes": [],
            }
            order.append(key)
        prof = profiles[key]

        # anonymous / is_owner: any true across the respondent's rows wins.
        if as_bool(s.get("anonymous")):
            prof["identity"]["anonymous"] = True
        if as_bool(s.get("is_owner")):
            prof["identity"]["is_owner"] = True

        # Resolve (or create) this row's quiz bucket, pulling meta from ctx.
        qid = s.get("quiz_id")
        if qid not in prof["quiz_index"]:
            meta = ctx.get(qid) or {}
            if prof["account_id"] is None:
                prof["account_id"] = meta.get("account_id")
            bucket = {
                "quiz_id": qid,
                "title": meta.get("title"),
                "brand_name": meta.get("brand_name"),
                "brand_tags": meta.get("brand_tags"),
                "language": meta.get("language"),
                "prize": meta.get("prize"),
                "prize_type": meta.get("prize_type"),
                "correct": 0,
                "incorrect": 0,
                "time_seconds": 0,
                "submissions": [],
                "answers": [],
            }
            prof["quiz_index"][qid] = bucket
            prof["quizzes"].append(bucket)
        bucket = prof["quiz_index"][qid]

        # Metrics for THIS submission, summed into the bucket.
        c = as_int(s.get("correct_answers"))
        i = as_int(s.get("incorrect_answers"))
        t = as_int(s.get("completion_time"))
        bucket["correct"] += c
        bucket["incorrect"] += i
        bucket["time_seconds"] += t

        # One submission entry + its joined answers.
        sid = s.get("submission_id")
        bucket["submissions"].append(
            {
                "submission_id": sid,
                "submitted_at": s.get("submitted_at"),
                "correct": c,
                "incorrect": i,
                "time_seconds": t,
            }
        )
        for a in answers_by_sub.get(sid, []):
            bucket["answers"].append(a)

    # Step 4: finalize each profile -- per-quiz accuracy, counts, drop scratch.
    records = []
    for key in order:
        prof = profiles[key]
        del prof["quiz_index"]
        for q in prof["quizzes"]:
            answered = q["correct"] + q["incorrect"]
            q["answered"] = answered
            q["accuracy"] = round(q["correct"] / answered, 4) if answered > 0 else None
        prof["quizzes_num"] = len(prof["quizzes"])
        prof["context_record_id"] = (
            identifier if identifier is not None else prof["respondent_id"]
        )
        prof["analysis"] = {}
        records.append(prof)

    self.output.base_profiles = records
    self.output.profiles_num = len(records)
    self.output.uploaded_num = 0
    self.output.preview_inputs = flow_input

    flow.private.base_profiles = records


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ### Local Flow Test
    """)
    return


@app.cell(hide_code=True)
def _():
    class _Bag(dict):
        """Attribute bag standing in for the engine's `flow` / `self` / `parent`.

        Subclasses dict and keeps both views in sync, because the engine's
        namespaces are reachable BOTH ways and different blocks pick different
        forms: `flow["input"]` and `flow.input`, `self.input.rows` and
        `dict(self.input)`. Missing keys read back as an empty _Bag rather than
        raising, so `flow.input.get("absent_criteria")` behaves like the engine's
        (chained access on an unmapped field yields nothing, not AttributeError).
        """

        def __init__(self, data=None):
            super().__init__(data or {})

        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return self.setdefault(name, _Bag())

        def __setattr__(self, name, value):
            self[name] = value

        def as_dict(self):
            return {
                k: v.as_dict() if isinstance(v, _Bag) else v for k, v in self.items()
            }

    def _bag(data=None):
        """Wrap nested mappings as _Bags so `flow.input.criteria.window_days` chains."""
        if isinstance(data, dict):
            return _Bag({k: _bag(v) for k, v in data.items()})
        if isinstance(data, list):
            return [_bag(v) for v in data]
        return data

    def make_sandbox(flow_data, current_item=None, node_input=None):
        flow = _bag(flow_data)
        flow.private = _Bag()

        node = _Bag()
        node.output = _Bag()
        node.input = _bag(node_input or {})

        parent = _Bag()
        parent._current_item = current_item
        return {
            "flow": flow,
            "self": node,
            "parent": parent,
            "json": json,
            "datetime": datetime,
        }

    return (make_sandbox,)


@app.cell
def _(make_sandbox, run_tests, test_flow):
    if run_tests.value:
        build_sandbox = make_sandbox({"input": {"identifier": None, **test_flow}})
        build_respondent_profiles.run(**build_sandbox)
        result = {
            "base_profiles": build_sandbox["self"].output.base_profiles,
            "profiles_num": build_sandbox["self"].output.profiles_num,
            # "preview_inputs": build_sandbox["self"].output.preview_inputs,
        }
    else:
        result = {}
    return (result,)


@app.cell
def _(run_tests, select_user):
    test_stack = mo.hstack([select_user, run_tests], justify="space-around")
    return (test_stack,)


@app.cell
def _(filter_stack):
    filter_stack
    return


@app.cell
def _(test_stack):
    test_stack
    return


@app.cell
def _(result, run_tests, select_user):
    # One profile at a time, chosen by email.
    _selected_index = (
        next(
            (
                i
                for i, prof in enumerate(result.get("base_profiles") or [])
                if prof.get("identity", {}).get("email") == select_user.value
            ),
            None,
        )
        if run_tests.value
        else None
    )

    specific_result = (
        result.get("base_profiles")[_selected_index]
        if run_tests.value and _selected_index is not None
        else None
    )
    num_profiles = result.get("profiles_num") if run_tests.value else 0
    specific_result
    return (num_profiles,)


@app.cell
def _(num_profiles, result):
    mo.accordion({f"Full Results List (**Profile count: {num_profiles}**)": result})
    return


if __name__ == "__main__":
    app.run()
