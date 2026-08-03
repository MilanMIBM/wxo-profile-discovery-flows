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
class BrandFanOutput(BaseModel):
    """Outputs of the likely_long_term_brand_fan script node — all optional."""

    respondent_id: Optional[str] = Field(
        default=None, description="Id of the respondent."
    )
    respondent_behavioral_metatags: List[str] = Field(
        default_factory=list,
        description='["likely_long_term_brand_fan"] when the respondent qualifies, else [].',
    )
    respondent_id_obj: Optional[dict] = Field(
        default=None, description='{"respondent_id": ...}'
    )
    respondent_behavioral_metatags_obj: Optional[dict] = Field(
        default=None,
        description='{"respondent_behavioral_metatags": [...]}',
    )
    result: Optional[dict] = Field(
        default=None, description="Both fields together, as a dict."
    )
    result_json: Optional[str] = Field(
        default=None, description="Both fields together, as a JSON string."
    )


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.cell
def _():
    # Authored and locally tested in wxo_base_profile_node.py; imported here
    # so there is exactly one definition of it. Needed only to produce the
    # profiles this notebook's local test scores.
    from wxo_base_profile_node import build_respondent_profiles

    return (build_respondent_profiles,)


@app.function
# 🧩 Tag a respondent as a likely long-term brand fan.
#
# Runs in the flow engine's restricted sandbox, NOT as a normal module: `flow`,
# `self` and `parent` are injected, `json` and `datetime` are pre-bound (no
# imports), and there is no return value -- output happens by assignment.
#
# Reads:  parent._current_item     -- this iteration's respondent profile,
#                                     whose nested quizzes[].submissions[] are
#                                     flattened here into submission rows and
#                                     a {quizId: {"brand_name": ...}} context
#         flow.input.window_months -- optional int (default 3)
#         flow.input.min_quizzes   -- optional int (default 3)
#         flow.input.success_pct   -- optional number (default 60)
# Writes: self.output.respondent_id / .respondent_behavioral_metatags
#         self.output.*_obj                (single-key dicts)
#         self.output.result / .result_json (all fields)
#
# Declare in the flow only the outputs you consume -- assigning an undeclared
# output is harmless, and a declared-but-unassigned output is just empty.
#
# One completion per distinct quizId at its EARLIEST submittedAt (that same
# submission supplies its score); group distinct quizzes by brand; a brand
# qualifies when some window_months*30-day window holds >= min_quizzes of its
# quizzes AND their POOLED success rate exceeds success_pct.
@logic_block(
    display_name="Likely long-term brand fan",
    output_schema=BrandFanOutput,
)
def likely_long_term_brand_fan(flow, self, parent, json, datetime):
    """Emits the likely_long_term_brand_fan metatag when any single brand shows a dense, high-scoring run of distinct quiz completions inside one rolling window."""
    # This node runs INSIDE the foreach, so its data comes from the current
    # iteration's profile, not from flow.input -- flow.input is identical on
    # every iteration and would tag all respondents the same.
    profile = dict(parent._current_item or {})

    # build_respondent_profiles emits a nested profile (quizzes[].submissions[])
    # carrying brand_name per quiz; flatten it into the submission rows this
    # block scores plus the {quizId: {"brand_name": ...}} context it groups by.
    rows = []
    ctx = {}
    for q in profile.get("quizzes") or []:
        qid = q.get("quiz_id")
        if qid is None:
            continue
        ctx[qid] = {"brand_name": q.get("brand_name")}
        for s in q.get("submissions") or []:
            correct = int(s.get("correct") or 0)
            incorrect = int(s.get("incorrect") or 0)
            rows.append(
                {
                    "quizId": qid,
                    "submittedAt": s.get("submitted_at"),
                    "correctAnswers": correct,
                    # No explicit answered count on a submission; correct +
                    # incorrect matches how the base profile derives accuracy.
                    "totalAnswered": correct + incorrect,
                    "_id": s.get("submission_id"),
                }
            )

    identifier = profile.get("respondent_id")
    window_days = int(flow["input"].get("window_months") or 3) * 30
    min_quizzes = int(flow["input"].get("min_quizzes") or 3)
    success_pct = float(flow["input"].get("success_pct") or 60)

    # ISO date string -> integer day count, so date gaps become plain
    # subtraction. Only the leading YYYY-MM-DD is read, so full timestamps
    # work too. None when unparseable.
    def epoch_day(value):
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return None

    # Collapse many submissions to the EARLIEST one per distinct quizId,
    # carrying the named `extra` fields (here the score) from that same row.
    def earliest_completions(
        rows, key="quizId", date_field="submittedAt", extra=()
    ):
        out = {}
        for row in rows:
            key_val = row.get(key)
            day = epoch_day(row.get(date_field))
            if key_val is None or day is None:
                continue
            current = out.get(key_val)
            if current is None or day < current["epoch_day"]:
                record = {"epoch_day": day}
                for field in extra:
                    record[field] = row.get(field)
                out[key_val] = record
        return out

    # Pooled success rate: 100 * sum(correct)/sum(answered). None when nothing
    # was answered, so "no data" stays distinct from a real 0%.
    def pooled_success_rate(
        items, correct_field="correct", answered_field="answered"
    ):
        correct = sum(int(i.get(correct_field) or 0) for i in items)
        answered = sum(int(i.get(answered_field) or 0) for i in items)
        if answered <= 0:
            return None
        return 100.0 * correct / answered

    # Step 1: one completion per quiz, keeping its date + score.
    completions = earliest_completions(
        rows, extra=["correctAnswers", "totalAnswered"]
    )

    # Step 2: per-quiz record (day, brand, correct, answered). `answered`
    # falls back to `correct` when totalAnswered is absent.
    quiz = {}
    for quiz_id, c in completions.items():
        correct = int(c.get("correctAnswers") or 0)
        answered_raw = c.get("totalAnswered")
        answered = (
            int(answered_raw) if answered_raw is not None else correct
        )
        quiz[quiz_id] = {
            "ord": c["epoch_day"],
            "brand": ctx.get(quiz_id, {}).get("brand_name"),
            "correct": correct,
            "answered": answered,
        }

    # Step 3: group the distinct quizzes by brand (skip unknown brands).
    by_brand = {}
    for q in quiz.values():
        if q["brand"] is None:
            continue
        by_brand.setdefault(q["brand"], []).append(q)

    # Step 4: does any brand qualify? Slide a window anchored at each quiz's
    # date; a brand qualifies when a window holds >= min_quizzes AND their
    # pooled success rate beats success_pct. Stop at the first such brand.
    qualifies = False
    for qs in by_brand.values():
        ords = [q["ord"] for q in qs]
        for anchor in ords:
            win = [
                q
                for q in qs
                if q["ord"] >= anchor and (q["ord"] - anchor) <= window_days
            ]
            if len(win) >= min_quizzes:
                rate = pooled_success_rate(win)
                if rate is not None and rate > success_pct:
                    qualifies = True
                    break
        if qualifies:
            break

    # respondent_id = identifier if given, else the first row's _id, else None.
    # metatags is always a list (possibly empty), never null.
    metatags = ["likely_long_term_brand_fan"] if qualifies else []
    respondent_id = (
        identifier
        if identifier is not None
        else (rows[0].get("_id") if rows else None)
    )
    result = {
        "respondent_id": respondent_id,
        "respondent_behavioral_metatags": metatags,
    }

    # Three flavors per field: the raw value, the same value wrapped as a
    # single-key dict, and result / result_json holding every field together.
    self.output.respondent_id = respondent_id
    self.output.respondent_behavioral_metatags = metatags

    self.output.respondent_id_obj = {"respondent_id": respondent_id}
    self.output.respondent_behavioral_metatags_obj = {
        "respondent_behavioral_metatags": metatags
    }

    self.output.result = result
    self.output.result_json = json.dumps(result)


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ### Local Flow Node Test
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
def _(build_respondent_profiles, make_sandbox, run_tests, test_flow):
    if run_tests.value:
        # Mirrors the real flow: build runs ONCE over the whole table bundle...
        build_sandbox = make_sandbox(
            {**test_flow, "input": {"identifier": None}}
        )
        build_respondent_profiles.run(**build_sandbox)
        _profiles = build_sandbox["self"].output.profiles

        # ...then the scorer runs ONCE PER PROFILE, as the foreach does, each
        # iteration seeing its own profile via parent._current_item.
        _fan = []
        for _profile in _profiles:
            _sandbox = make_sandbox({**test_flow, "input": {}}, _profile)
            likely_long_term_brand_fan.run(**_sandbox)
            _fan.append(_sandbox["self"].output.result)

        result = {
            "profiles": _profiles,
            "fan": _fan,
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
    # Scorer results carry only respondent_id, so find the selected user in the
    # PROFILES (which hold the email) and take the results at the same position
    # -- the lists are built in lockstep, one entry per respondent.
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

    {
        "profile": result.get("profiles")[_selected_index],
        "fan": result.get("fan")[_selected_index],
    } if run_tests.value and _selected_index is not None else None
    return


@app.cell
def _(result):
    mo.accordion({"Full Results List": result})
    return


if __name__ == "__main__":
    app.run()
