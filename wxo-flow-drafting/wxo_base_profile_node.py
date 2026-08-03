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
    from typing import Optional
    from pydantic import BaseModel, Field
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block


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


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_meta = mo.sql(
        f"""
        SELECT * FROM "quiz_meta" LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_meta,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_structure = mo.sql(
        f"""
        SELECT * FROM "quiz_structure" LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_structure,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_details = mo.sql(
        f"""
        SELECT * FROM "quiz_details" LIMIT 1000
        """,
        output=False,
        engine=postgresql_engine,
    )
    return (quiz_details,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_scoring = mo.sql(
        f"""
        SELECT * FROM "quiz_scoring" LIMIT 1000
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
    return (select_user,)


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
    rows = (
        df.to_dicts()
        if hasattr(df, "to_dicts")
        else df.to_dict(orient="records")
    )
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
    test_flow = {"retrieve_tables": {"output": db_records}}
    return (test_flow,)


@app.cell
def _():
    run_tests = mo.ui.run_button(label="Run Node Tests")
    return (run_tests,)


@app.cell(column=1, hide_code=True)
def _():
    mo.md(r"""
    ### Class definitions
    """)
    return


@app.class_definition
class RespondentProfileItem(BaseModel):
    """One respondent profile as iterated by the foreach.

    Loose by design: `extra="allow"` lets the full nested profile that
    build_respondent_profiles emits (identity, quizzes, submissions, answers)
    ride through without every level having to be declared here.
    """

    model_config = {"extra": "allow"}

    respondent_id: Optional[str] = Field(
        default=None, description="Id of the respondent."
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.function
# 🧩 Build one base respondent profile per respondent.
#
# Runs in the flow engine's restricted sandbox, NOT as a normal module: `flow`,
# `self` and `parent` are injected, `json` is pre-bound (no imports), and there
# is no return value -- output happens by assignment. The parameters exist so
# linters resolve those names; the engine never calls this function.
#
# Reads:  the retrieve_tables node's output (scoring + details + quiz_meta)
# Writes: self.output.profiles      -- list of base profiles, one per respondent
#         flow.private.profiles_num -- how many were built
#         flow.private.uploaded_num -- upload counter, zeroed for this run
@logic_block(
    display_name="Build respondent profiles",
)
def build_respondent_profiles(flow, self, json):
    """Collapses the flat quiz tables returned by retrieve_tables into one base profile per respondent, nesting each respondent's quizzes, submissions and answers."""
    node_out = flow.get("retrieve_tables") or {}
    tables = node_out.get("output")

    # The tool returns a bare array; tolerate a wrapped {key: [...]} shape too.
    if isinstance(tables, dict):
        for key in ("result", "output", "value", "tables"):
            if isinstance(tables.get(key), list):
                tables = tables[key]
                break
    if not isinstance(tables, list):
        tables = []

    identifier = flow["input"].get("identifier")

    # Best-effort int, 0 on missing/unparseable.
    def as_int(value):
        try:
            return int(value)
        except TypeError, ValueError:
            return 0

    # Truthy across real bools and common string spellings ("true"/"1"/"yes"/"t"):
    # DB rows arrive typed, CSV-style rows arrive as strings.
    def as_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "t")
        return bool(value)

    # brand_tags / prize_type are stored as JSON-array strings ('["a","b"]') but
    # may also arrive as a real list, empty, or "[]". Normalise to a list or None.
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

    # Step 1: quiz_context keyed by quizId -- nest the flat prize.* columns into
    # a `prize` object and parse the tag strings into real lists.
    ctx = {}
    for m in quiz_meta:
        qid = m.get("quizId")
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

    # Step 3: group scoring by respondent (email), bucketing per quiz.
    # One scoring row == one submission. The respondent key is email, falling
    # back to submission_id when email is missing. `quiz_index` maps quizId ->
    # its bucket within the current respondent so repeat submissions accumulate.
    profiles = {}
    order = []
    for s in scoring:
        email = s.get("email")
        key = email if email is not None else s.get("submission_id")
        if key not in profiles:
            profiles[key] = {
                "respondent_id": s.get("submission_id"),
                "identity": {
                    "display_name": s.get("displayName"),
                    "email": email,
                    "anonymous": as_bool(s.get("anonymous")),
                    "is_owner": as_bool(s.get("isOwner")),
                    "placeholder_email": bool(email)
                    and email.startswith("temp@"),
                },
                "quiz_index": {},
                "quizzes": [],
            }
            order.append(key)
        prof = profiles[key]

        # anonymous / is_owner: any true across the respondent's rows wins.
        if as_bool(s.get("anonymous")):
            prof["identity"]["anonymous"] = True
        if as_bool(s.get("isOwner")):
            prof["identity"]["is_owner"] = True

        # Resolve (or create) this row's quiz bucket, pulling meta from ctx.
        qid = s.get("quizId")
        if qid not in prof["quiz_index"]:
            meta = ctx.get(qid) or {}
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
        c = as_int(s.get("correctAnswers"))
        i = as_int(s.get("incorrectAnswers"))
        t = as_int(s.get("timeSeconds"))
        bucket["correct"] += c
        bucket["incorrect"] += i
        bucket["time_seconds"] += t

        # One submission entry + its joined answers.
        sid = s.get("submission_id")
        bucket["submissions"].append(
            {
                "submission_id": sid,
                "submitted_at": s.get("submittedAt"),
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
            q["accuracy"] = (
                round(q["correct"] / answered, 4) if answered > 0 else None
            )
        prof["quizzes_num"] = len(prof["quizzes"])
        prof["context_record_id"] = (
            identifier if identifier is not None else prof["respondent_id"]
        )
        records.append(prof)

    self.output.profiles = records
    flow.private.profiles_num = len(records)
    flow.private.uploaded_num = 0


@app.function
# 🧩 Add whatever the upstream scorers produced onto the respondent profile.
#
# Node-name agnostic: reads self.input rather than any named node, so adding
# or removing a scorer branch needs no change here -- only a data map wiring
# the new branch's output into this node's input.
#
# Reads:  parent._current_item -- the profile for this iteration
#         self.input.*         -- every scorer's mapped-in output
# Writes: self.output.profile  -- the profile plus every signal it received
@logic_block(
    display_name="Merge profile signals",
)
def merge_profile_signals(flow, self, parent, json):
    """Copies the current respondent profile and layers on every signal handed to this node by the upstream scoring branches, whatever they happen to be."""
    profile = dict(parent._current_item or {})

    # Keys that identify the record rather than describe it -- never let a
    # scorer's echoed id overwrite the profile's own fields.
    skip = ("respondent_id", "context_record_id", "identifier")

    # Flatten one scorer's contribution onto the profile. Each block emits its
    # raw fields plus _obj / result / result_json wrappers of the same values,
    # so prefer `result` when present and ignore the redundant rest.
    def absorb(value):
        if not isinstance(value, dict):
            return
        fields = (
            value.get("result")
            if isinstance(value.get("result"), dict)
            else value
        )
        for key, val in fields.items():
            if key in skip or key.endswith("_obj") or key == "result_json":
                continue
            if key == "result":
                continue
            # Lists accumulate across scorers (metatags from several sources);
            # scalars are set outright.
            if isinstance(val, list):
                existing = profile.get(key)
                merged = (
                    list(existing) if isinstance(existing, list) else []
                )
                for item in val:
                    if item not in merged:
                        merged.append(item)
                profile[key] = merged
            elif val is not None or key not in profile:
                profile[key] = val

    # self.input holds one entry per mapped-in branch, keyed by whatever the
    # data map called it. Walk them all rather than naming any.
    inputs = self["input"] or {}
    for key, value in inputs.items():
        if key == "profile":
            continue
        absorb(value)

    self.output.profile = profile


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ### Local Flow Test
    """)
    return


@app.cell
def _():
    class _Bag:
        """Attribute bag standing in for the engine's `self.output` / `flow.private`."""

        def __init__(self):
            self.__dict__.update()

        def as_dict(self):
            return dict(self.__dict__)

    class _FlowStub(dict):
        """dict-like `flow` (flow.get / flow["input"]) that also carries .private."""

        def __init__(self, data):
            super().__init__(data)
            self.private = _Bag()

    def make_sandbox(flow_data, current_item=None):
        node = _Bag()
        node.output = _Bag()
        # `parent` carries the foreach's current item for nodes inside the loop.
        parent = _Bag()
        parent._current_item = current_item
        return {
            "flow": _FlowStub(flow_data),
            "self": node,
            "parent": parent,
            "json": json,
            "datetime": datetime,
        }

    return (make_sandbox,)


@app.cell
def _(make_sandbox, run_tests, test_flow):
    if run_tests.value:
        build_sandbox = make_sandbox(
            {**test_flow, "input": {"identifier": None}}
        )
        build_respondent_profiles.run(**build_sandbox)
        result = {
            "profiles": build_sandbox["self"].output.profiles,
            "private": build_sandbox["flow"].private.as_dict(),
        }
    else:
        result = {}
    return (result,)


@app.cell
def _(run_tests, select_user):
    mo.hstack([select_user, run_tests], justify="space-around")
    return


@app.cell
def _(result, run_tests, select_user):
    # One profile at a time, chosen by email.
    _selected_index = (
        next(
            (
                i
                for i, prof in enumerate(result.get("profiles") or [])
                if prof.get("identity", {}).get("email") == select_user.value
            ),
            None,
        )
        if run_tests.value
        else None
    )

    result.get("profiles")[
        _selected_index
    ] if run_tests.value and _selected_index is not None else None
    return


@app.cell
def _(result):
    mo.accordion({"Full Results List": result})
    return


if __name__ == "__main__":
    app.run()
