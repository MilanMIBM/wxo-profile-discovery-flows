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
    from pydantic import BaseModel, Field
    from typing import List, Dict
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block

    class SustainedEngagementOutput(BaseModel):
        """Outputs of the sustained_engagement_level script node — all optional."""

        respondent_id: str = Field(
            default="", description="Id of the respondent."
        )
        sustained_engagement_level: int = Field(
            default=0,
            description="Highest engagement bracket that qualified; 0 when none did.",
        )
        respondent_id_obj: dict = Field(
            default_factory=dict, description='{"respondent_id": ...}'
        )
        sustained_engagement_level_obj: dict = Field(
            default_factory=dict,
            description='{"sustained_engagement_level": ...}',
        )
        result: dict = Field(
            default_factory=dict, description="Both fields together, as a dict."
        )
        result_json: str = Field(
            default="", description="Both fields together, as a JSON string."
        )
        preview_inputs: dict = Field(
            default_factory=dict,
            description="Preview of the input for debugging purposes.",
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
    ## Logic blocks
    """)
    return


@app.cell
def _():
    # Authored and locally tested in wxo_base_profile_node.py; imported here
    # so there is exactly one definition of it. Needed only to produce the
    # profiles this notebook's local test scores.
    from wxo_base_profile_node import (
        build_respondent_profiles,
    )

    return (build_respondent_profiles,)


@app.function
# 🧩 Highest sustained-engagement bracket the respondent qualifies for.
#
# Runs in the flow engine's restricted sandbox, NOT as a normal module: `flow`,
# `self` and `parent` are injected, `json` and `datetime` are pre-bound (no
# imports), and there is no return value -- output happens by assignment.
#
# Reads:  parent._current_item -- this iteration's respondent profile, whose
#                                 nested quizzes[].submissions[] are flattened
#                                 back into submission rows here
#         flow.input.levels    -- optional bracket list; defaults below
# Writes: self.output.respondent_id / .sustained_engagement_level  (raw values)
#         self.output.*_obj                                        (single-key dicts)
#         self.output.result / .result_json                        (all fields)
#
# Declare in the flow only the outputs you consume -- assigning an undeclared
# output is harmless, and a declared-but-unassigned output is just empty.
#
# One completion per distinct quizId at its EARLIEST submittedAt; keep a
# maximally-spaced subsequence of those dates (each >= min_days_between apart);
# a bracket passes if any run of `number_of_quizzes` spans <= timeframe_days;
# emit the single highest passing bracket's level (None when none qualify).
@logic_block(
    display_name="Sustained engagement level",
    output_schema=SustainedEngagementOutput,
)
def sustained_engagement_level(flow, self, parent, json, datetime):
    """Scores a respondent's submission history against a ladder of engagement brackets and emits the highest one whose quiz-count, spacing and timeframe conditions all hold."""
    # This node runs INSIDE the foreach, so its data comes from the current
    # iteration's profile, not from flow.input -- flow.input is identical on
    # every iteration and would score all respondents the same.
    # Cursor first: a data map targeting `self.input.input` never lands (the
    # field name collides with the input container itself), so self["input"]
    # arrived {}. The mapped fallback keeps working if a named field is wired.
    profile = dict(parent._current_item or {}) or (self["input"] or {}).get(
        "profile"
    ) or {}

    # build_respondent_profiles emits a nested profile (quizzes[].submissions[]);
    # flatten it back to the one-row-per-submission shape this block scores.
    rows = []
    for q in profile.get("quizzes") or []:
        qid = q.get("quiz_id")
        if qid is None:
            continue
        for s in q.get("submissions") or []:
            rows.append(
                {
                    "quizId": qid,
                    "submittedAt": s.get("submitted_at"),
                    "_id": s.get("submission_id"),
                }
            )

    identifier = profile.get("respondent_id")
    levels = flow["input"].get("levels") or [
        {
            "level": "1",
            "timeframe_days": 30,
            "min_days_between": 7,
            "number_of_quizzes": 1,
        },
        {
            "level": "2",
            "timeframe_days": 30,
            "min_days_between": 7,
            "number_of_quizzes": 2,
        },
        {
            "level": "3",
            "timeframe_days": 30,
            "min_days_between": 7,
            "number_of_quizzes": 3,
        },
    ]

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

    # Collapse many submissions to the EARLIEST one per distinct quizId, as
    # {quizId: {"epoch_day": int, <extra fields from that earliest row>}}.
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

    # Greedily keep a maximally-spaced subsequence: walking the sorted days,
    # keep each one at least `min_gap` days after the last kept one.
    def greedy_spaced(days, min_gap):
        kept = []
        for day in sorted(days):
            if not kept or (day - kept[-1]) >= min_gap:
                kept.append(day)
        return kept

    # True if any run of `count` consecutive (ascending) days spans <= `span`.
    def has_run_within(sorted_days, count, span):
        if count <= 0:
            return True
        if len(sorted_days) < count:
            return False
        for i in range(len(sorted_days) - count + 1):
            if (sorted_days[i + count - 1] - sorted_days[i]) <= span:
                return True
        return False

    # Step 1: one completion per quiz, as a sorted list of day counts.
    earliest = earliest_completions(rows)
    ordinals = sorted(rec["epoch_day"] for rec in earliest.values())

    # Step 2: rank every passing bracket so a plain sort picks the winner.
    # Key = [need, gap, -window, -idx, level]; ascending sort + take the last
    # => most quizzes, then widest gap, then narrowest window, then the
    # earlier-listed bracket. Each bracket spaces the dates by its own gap.
    ranked = []
    for idx, b in enumerate(levels):
        need = int(b.get("number_of_quizzes") or 1)
        gap = int(b.get("min_days_between") or 0)
        window = int(b.get("timeframe_days") or 0)
        kept = greedy_spaced(ordinals, gap)
        if has_run_within(kept, need, window):
            ranked.append([need, gap, -window, -idx, str(b.get("level"))])

    # Step 3: winner is the top-ranked bracket's level (None if none passed).
    level = int(sorted(ranked)[-1][4]) if ranked else None

    # respondent_id = identifier if given, else the first row's _id, else None.
    # level is JSON null when no bracket qualifies.
    respondent_id = (
        identifier
        if identifier is not None
        else (rows[0].get("_id") if rows else None)
    )
    result = {
        "respondent_id": respondent_id,
        "sustained_engagement_level": level,
    }

    # Three flavors per field: the raw value, the same value wrapped as a
    # single-key dict, and result / result_json holding every field together.
    self.output.respondent_id = respondent_id
    self.output.sustained_engagement_level = level

    self.output.respondent_id_obj = {"respondent_id": respondent_id}
    self.output.sustained_engagement_level_obj = {
        "sustained_engagement_level": level
    }

    self.output.result = result
    self.output.result_json = json.dumps(result)
    self.output.preview_inputs = profile


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
        _engagement = []
        for _profile in _profiles:
            _sandbox = make_sandbox({**test_flow, "input": {}}, _profile)
            sustained_engagement_level.run(**_sandbox)
            _engagement.append(_sandbox["self"].output.result)

        result = {
            "profiles": _profiles,
            "engagement": _engagement,
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
        "engagement": result.get("engagement")[_selected_index],
    } if run_tests.value and _selected_index is not None else None
    return


@app.cell
def _(result):
    mo.accordion({"Full Results List": result})
    return


if __name__ == "__main__":
    app.run()
