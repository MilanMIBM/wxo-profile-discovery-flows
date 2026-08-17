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
    from typing import List, Dict, Any
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block

    class SustainedEngagementOutput(BaseModel):
        """Outputs of the sustained_engagement_level script node - all optional."""

        respondent_id: str = Field(default="", description="Id of the respondent.")
        sustained_engagement_level: int = Field(
            default=0,
            description="Highest engagement bracket that qualified; 0 when none did.",
        )
        sustained_engagement_level_obj: dict = Field(
            default_factory=dict,
            description='{"sustained_engagement_level": ...}',
        )
        result: dict = Field(
            default_factory=dict, description="Both fields together, as a dict."
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


@app.cell(hide_code=True)
def _(postgresql_engine):
    from sqlalchemy import text, inspect
    from sqlalchemy.dialects.postgresql import JSONB

    # Drop existing tables before reloading them from CSV. Compare the string, since bool("False") is True.
    rewrite_tables = os.getenv("REWRITE_TABLES", "false").lower() == "true"
    print(f"Rewrite tables: {rewrite_tables}")

    TABLES_DIR = Path("src/data/tables")
    existing = set(inspect(postgresql_engine).get_table_names())

    # One table per CSV in TABLES_DIR, named after the file stem -- drop a new CSV in the directory and it gets loaded without touching this cell.
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


@app.cell
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


@app.cell
def _():
    # Authored and locally tested in wxo_base_profile_node.py; imported here so there is exactly one definition of it. Needed only to produce the profiles this notebook's local test scores.
    from wxo_base_profile_node import (
        build_respondent_profiles,
    )

    return (build_respondent_profiles,)


@app.function
@logic_block(
    display_name="Sustained engagement level",
    output_schema=SustainedEngagementOutput,
)
def sustained_engagement_level(flow, self, parent, json, datetime):
    """Awards the highest engagement bracket a respondent's completion history qualifies for.

    Runs in the flow engine's restricted sandbox, NOT as a normal module:
    `flow`, `self` and `parent` are injected, `json` and `datetime` are
    pre-bound (no imports), and there is no return value -- output happens by
    assignment.

    Reads:  parent._current_item -- this iteration's respondent profile, whose
                                    nested quizzes[].submissions[] are flattened
                                    back into submission rows here
            flow.input.sustained_engagement_level_criteria
                .levels -- optional bracket list; defaults below
    Writes: self.output.respondent_id / .sustained_engagement_level (raw values)
            self.output.*_obj   (single-key dicts)
            self.output.result  (all fields)

    Declare in the flow only the outputs you consume -- assigning an undeclared
    output is harmless, and a declared-but-unassigned output is just empty.

    One completion per distinct quiz_id at its EARLIEST submitted_at. A bracket
    cuts its timeframe_days window into consecutive min_days_between
    sub-periods and demands `number_of_quizzes` completions in EVERY one of
    them, so it measures a sustained rhythm rather than a single burst:
    7 days / 30 days / 1 quiz is 4 quizzes a month, one per week, and the same
    cadence at 2 quizzes is 8 a month. A bracket passes when some window
    anchored on a completion sustains that cadence end to end; the single
    highest passing bracket's level is emitted (None when none qualify)."""

    profile = dict(parent._current_item or {}) or {}

    # Flatten the nested profile back to the one-row-per-submission shape this block scores.
    rows = []
    for q in profile.get("quizzes") or []:
        qid = q.get("quiz_id")
        if qid is None:
            continue
        for s in q.get("submissions") or []:
            rows.append(
                {
                    "quiz_id": qid,
                    "submitted_at": s.get("submitted_at"),
                    "_id": s.get("submission_id"),
                }
            )

    identifier = profile.get("respondent_id")

    # Flow input variables to adjust the behavior of the node at runtime.
    criteria = flow.input.get("sustained_engagement_level_criteria") or {}

    # number_of_quizzes is PER SUB-PERIOD, so each level is a denser rhythm over the same month: 1/week = 4 a month, 2/week = 8, 3/week = 12.
    levels = criteria.get("levels") or [
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

    # ISO date -> integer day count, so date gaps become plain subtraction. Only the leading YYYY-MM-DD is read, so full timestamps work too.
    def epoch_day(value):
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return None

    # One completion per distinct quiz_id -- its earliest submission, carrying the named `extra` fields from that same row.
    def earliest_completions(rows, key="quiz_id", date_field="submitted_at", extra=()):
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

    # Does a window starting at `start` sustain the cadence? The window is cut into consecutive `gap`-day sub-periods and EVERY one must hold at least `per_period` completions -- a burst in a single sub-period fails, which is what separates sustained engagement from one busy week.
    def sustains_cadence(sorted_days, start, window, gap, per_period):
        periods = window // gap
        if periods <= 0:
            return False
        for p in range(periods):
            lo = start + p * gap
            hi = lo + gap
            found = 0
            for day in sorted_days:
                if lo <= day < hi:
                    found += 1
                elif day >= hi:
                    break
            if found < per_period:
                return False
        return True

    # Step 1: one completion per quiz, as a sorted list of day counts.
    earliest = earliest_completions(rows)
    ordinals = sorted(rec["epoch_day"] for rec in earliest.values())

    # Step 2: rank every passing bracket so a plain sort picks the winner. Key = [total, gap, -window, -idx, level]; ascending sort + take the last => most quizzes demanded, then widest gap, then narrowest window, then the earlier-listed bracket. A bracket passes when SOME window anchored on a completion sustains its cadence end to end.
    ranked = []
    for idx, b in enumerate(levels):
        per_period = int(b.get("number_of_quizzes") or 1)
        gap = int(b.get("min_days_between") or 0)
        window = int(b.get("timeframe_days") or 0)
        if gap <= 0 or window <= 0:
            continue
        # Anchoring on each completion is enough: a qualifying window can always be slid forward until its first sub-period starts on a completion.
        if any(
            sustains_cadence(ordinals, start, window, gap, per_period)
            for start in ordinals
        ):
            total = (window // gap) * per_period
            ranked.append([total, gap, -window, -idx, str(b.get("level"))])

    # Step 3: winner is the top-ranked bracket's level (None if none passed).
    winner = sorted(ranked)[-1] if ranked else None
    level = int(winner[4]) if winner else None

    # Plain-language restatement of the winning bracket, so consumers see why the level was awarded and not just the number.
    def describe(bracket):
        per_period = int(bracket.get("number_of_quizzes") or 1)
        gap = int(bracket.get("min_days_between") or 0)
        window = int(bracket.get("timeframe_days") or 0)
        periods = window // gap if gap > 0 else 0
        quizzes = "1 quiz" if per_period == 1 else f"{per_period} quizzes"
        days = "day" if gap == 1 else f"{gap} days"
        return (
            f"Completes at least {quizzes} every {days} for {window} days "
            f"running ({periods * per_period} in total)."
        )

    # Key position 3 holds -idx, so negating it indexes back into `levels`.
    rule_description = describe(levels[-winner[3]]) if winner else None

    # The flow's identifier wins; the first submission's id is the fallback.
    respondent_id = (
        identifier if identifier is not None else (rows[0].get("_id") if rows else None)
    )
    result = {
        "respondent_id": respondent_id,
        "sustained_engagement_level": level if level is not None else 0,
        "rule_description": rule_description,
    }

    # Each field is published three ways -- raw, wrapped as a single-key dict, and inside `result` -- so a data map can bind whichever shape it needs.
    self.output.respondent_id = respondent_id

    self.output.sustained_engagement_level = level
    self.output.sustained_engagement_level_obj = {"sustained_engagement_level": level}

    self.output.result = result
    self.output.preview_inputs = profile


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ### Local Flow Node Test
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
def _():
    test_timeframe_days = mo.ui.number(
        label="**Timeframe days  :**",
        start=1,
        stop=365,
        step=1,
        value=30,
    )
    return (test_timeframe_days,)


@app.cell
def _():
    test_min_days_between = mo.ui.number(
        label="**Sub-period length in days  :**",
        start=1,
        stop=90,
        step=1,
        value=7,
    )
    return (test_min_days_between,)


@app.cell
def _():
    test_number_of_levels = mo.ui.slider(
        label="**Number of brackets** *(bracket N = N quizzes per sub-period)* **:**",
        start=1,
        stop=10,
        step=1,
        value=3,
        show_value=True,
    )
    return (test_number_of_levels,)


@app.cell
def _(
    build_respondent_profiles,
    make_sandbox,
    run_tests,
    test_flow,
    test_min_days_between,
    test_number_of_levels,
    test_timeframe_days,
):
    if run_tests.value:
        # Mirrors the real flow: build runs ONCE over the whole table bundle...
        build_sandbox = make_sandbox({"input": {"identifier": None, **test_flow}})
        build_respondent_profiles.run(**build_sandbox)
        _profiles = build_sandbox["self"].output.base_profiles

        # ...then the scorer runs ONCE PER PROFILE, as the foreach does, each iteration seeing its own profile via parent._current_item. The criteria the scorer reads off flow.input; {} would also work (every knob falls back to its default), this exercises the wiring. Bracket N demands N quizzes PER SUB-PERIOD -- at 7 days over 30, that is 4N a month -- so the ladder is generated from the three knobs rather than spelled out one entry at a time.
        _criteria = {
            "sustained_engagement_level_criteria": {
                "levels": [
                    {
                        "level": str(_n),
                        "timeframe_days": int(test_timeframe_days.value),
                        "min_days_between": int(test_min_days_between.value),
                        "number_of_quizzes": _n,
                    }
                    for _n in range(1, int(test_number_of_levels.value) + 1)
                ]
            }
        }

        _engagement = []
        for _profile in _profiles:
            _sandbox = make_sandbox({**test_flow, "input": _criteria}, _profile)
            sustained_engagement_level.run(**_sandbox)
            _engagement.append(_sandbox["self"].output.result)

        result = {
            "engagement": _engagement,
            "base_profiles": _profiles,
            # "private": build_sandbox["flow"].private.as_dict(),
        }
    else:
        result = {}
    return (result,)


@app.cell
def _(test_min_days_between, test_number_of_levels, test_timeframe_days):
    specific_test_stack = mo.vstack(
        [test_timeframe_days, test_min_days_between, test_number_of_levels],
        align="start",
    )
    return (specific_test_stack,)


@app.cell
def _(result, run_tests):
    num_profiles = len(result.get("base_profiles")) if run_tests.value else 0
    return (num_profiles,)


@app.cell
def _(run_tests, select_user):
    test_stack = mo.hstack([select_user, run_tests], justify="space-around")
    return (test_stack,)


@app.cell
def _(specific_test_stack):
    specific_test_stack
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
def _(result, run_tests, select_user):
    # Scorer results carry only respondent_id, so find the selected user in the PROFILES (which hold the email) and take the results at the same position -- the lists are built in lockstep, one entry per respondent.
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

    {
        "profile": result.get("base_profiles")[_selected_index],
        "engagement": result.get("engagement")[_selected_index],
    } if run_tests.value and _selected_index is not None else None
    return


@app.cell
def _(num_profiles, result):
    mo.accordion({f"Full Results List (**Profile count: {num_profiles}**)": result})
    return


if __name__ == "__main__":
    app.run()
