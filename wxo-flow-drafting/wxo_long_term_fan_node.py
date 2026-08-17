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
    from pydantic import BaseModel, Field
    from pymongo import MongoClient
    from dotenv import load_dotenv

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from src.helpers.logic_block import logic_block

    class BrandFanOutput(BaseModel):
        """Outputs of the likely_long_term_brand_fan script node - all optional."""

        respondent_id: str = Field(default="", description="Id of the respondent.")
        likely_long_term_brand_fan: List[dict] = Field(
            default_factory=list,
            description="""One entry per qualifying brand, keyed by brand name: [{"Acme": {"average_success_rate": 85.0, "total_completed_quizzes": 2, "prizes_played_for": ["Tickets"]}}]. Empty when no brand qualifies.""",
        )
        likely_long_term_brand_fan_obj: dict = Field(
            default_factory=dict,
            description="""{"likely_long_term_brand_fan": [...]}""",
        )
        result: dict = Field(
            default_factory=dict,
            description="""All fields together, as a dict.""",
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
        BuildProfilesOutput,
    )

    return (build_respondent_profiles,)


@app.function
@logic_block(
    display_name="Likely long-term brand fan",
    output_schema=BrandFanOutput,
)
def likely_long_term_brand_fan(flow, self, parent, json, datetime):
    """Reports which brands a respondent is a likely long-term fan of, with the stats behind each verdict.

    Runs in the flow engine's restricted sandbox, NOT as a normal module:
    `flow`, `self` and `parent` are injected, `json` and `datetime` are
    pre-bound (no imports), and there is no return value -- output happens by
    assignment.

    Reads:  parent._current_item -- this iteration's respondent profile, whose
                                    nested quizzes[].submissions[] are flattened
                                    into submission rows plus a per-quiz context
                                    carrying brand_name and prize.prize_name
            flow.input.likely_long_term_brand_fan_criteria
                .window_days -- optional int (default 30) - 1 month
                .min_quizzes -- optional int (default 2)
                .success_pct -- optional number (default 60)
    Writes: self.output.respondent_id
            self.output.likely_long_term_brand_fan -- per-brand detail list
            self.output.*_obj   (single-key dicts)
            self.output.result  (all fields)

    One completion per distinct quiz_id at its EARLIEST submitted_at (that same
    submission supplies its score); group distinct quizzes by brand; a brand
    qualifies when some window_days window holds >= min_quizzes of its quizzes
    AND their POOLED success rate exceeds success_pct.

    EVERY brand is evaluated, and the reported stats describe the brand as a
    whole -- all its distinct completed quizzes -- not just the window that
    happened to trigger qualification."""
    profile = dict(parent._current_item or {}) or {}

    # Flatten the nested profile into submission rows plus per-quiz context.
    # prize_name lives one level in, at quiz["prize"]["prize_name"].
    rows = []
    ctx = {}
    for q in profile.get("quizzes") or []:
        qid = q.get("quiz_id")
        if qid is None:
            continue
        prize = q.get("prize") or {}
        ctx[qid] = {
            "brand_name": q.get("brand_name"),
            "prize_name": prize.get("prize_name"),
        }
        for s in q.get("submissions") or []:
            correct = int(s.get("correct") or 0)
            incorrect = int(s.get("incorrect") or 0)
            rows.append(
                {
                    "quiz_id": qid,
                    "submitted_at": s.get("submitted_at"),
                    "correct_answers": correct,
                    "total_answered": correct + incorrect,
                    "_id": s.get("submission_id"),
                }
            )

    identifier = profile.get("respondent_id")

    # Flow input variables to adjust the behavior of the node at runtime.
    criteria = flow.input.get("likely_long_term_brand_fan_criteria") or {}

    window_days = int(criteria.get("window_days") or 30)
    min_quizzes = int(criteria.get("min_quizzes") or 2)
    success_pct = float(criteria.get("success_pct") or 60)

    # ISO date -> integer day count, so date gaps become plain subtraction. Only the leading YYYY-MM-DD is read, so full timestamps work too.
    def epoch_day(value):
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(value[:10]).toordinal()
        except ValueError:
            return None

    # One completion per distinct quiz_id -- its earliest submission, carrying the named `extra` fields (here the score) from that same row.
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

    # 100 * sum(correct)/sum(answered). None when nothing was answered, so "no data" stays distinct from a real 0%.
    def pooled_success_rate(items, correct_field="correct", answered_field="answered"):
        correct = sum(int(i.get(correct_field) or 0) for i in items)
        answered = sum(int(i.get(answered_field) or 0) for i in items)
        if answered <= 0:
            return None
        return 100.0 * correct / answered

    # Step 1: one completion per quiz, keeping its date + score.
    completions = earliest_completions(
        rows, extra=["correct_answers", "total_answered"]
    )

    # Step 2: per-quiz record (day, brand, prize, correct, answered), `answered` falls back to `correct` when total_answered is absent.
    quiz = {}
    for quiz_id, c in completions.items():
        correct = int(c.get("correct_answers") or 0)
        answered_raw = c.get("total_answered")
        answered = int(answered_raw) if answered_raw is not None else correct
        meta = ctx.get(quiz_id) or {}
        quiz[quiz_id] = {
            "ord": c["epoch_day"],
            "brand": meta.get("brand_name"),
            "prize_name": meta.get("prize_name"),
            "correct": correct,
            "answered": answered,
        }

    # Step 3: group the distinct quizzes by brand (skip unknown brands).
    by_brand = {}
    for q in quiz.values():
        if q["brand"] is None:
            continue
        by_brand.setdefault(q["brand"], []).append(q)

    # Step 4: evaluate EVERY brand and describe the ones that qualify. The window test only decides IF a brand qualifies; the reported stats then summarise all of that brand's distinct completed quizzes.
    brands = []
    for brand_name, qs in sorted(by_brand.items()):
        ords = [q["ord"] for q in qs]
        qualifies = False
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
        if not qualifies:
            continue

        # Prizes this respondent actually played for under this brand: de-duplicated, blanks dropped, first-seen order preserved.
        prizes = []
        for q in sorted(qs, key=lambda q: q["ord"]):
            name = q.get("prize_name")
            if name and name not in prizes:
                prizes.append(name)

        overall = pooled_success_rate(qs)
        brands.append(
            {
                brand_name: {
                    # Pooled across the brand's distinct quizzes, as a percentage rounded to 2dp. None only if nothing answered.
                    "average_success_rate": (
                        round(overall, 2) if overall is not None else None
                    ),
                    "total_completed_quizzes": len(qs),
                    "prizes_played_for": prizes,
                }
            }
        )

    # The flow's identifier wins; the first submission's id is the fallback.
    respondent_id = (
        identifier if identifier is not None else (rows[0].get("_id") if rows else None)
    )
    result = {
        "respondent_id": respondent_id,
        "likely_long_term_brand_fan": brands,
    }

    # Each field is published three ways -- raw, wrapped as a single-key dict, and inside `result` -- so a data map can bind whichever shape it needs.
    self.output.respondent_id = respondent_id

    self.output.likely_long_term_brand_fan = brands
    self.output.likely_long_term_brand_fan_obj = {"likely_long_term_brand_fan": brands}

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
    test_window_days = mo.ui.number(
        label="**Window days :**",
        start=0,
        stop=30,
        step=1,
        value=30,
    )
    return (test_window_days,)


@app.cell
def _():
    test_min_quizzes = mo.ui.number(
        label="**Minimum completed quizzes :**",
        start=1,
        stop=10,
        step=1,
        value=2,
    )
    return (test_min_quizzes,)


@app.cell
def _():
    test_success_percentage = mo.ui.slider(
        label="**Required success score :**",
        start=0,
        stop=100,
        step=1,
        value=55,
        show_value=True,
    )
    return (test_success_percentage,)


@app.cell
def _(
    build_respondent_profiles,
    make_sandbox,
    run_tests,
    test_flow,
    test_min_quizzes,
    test_success_percentage,
    test_window_days,
):
    if run_tests.value:
        # Mirrors the real flow: build runs ONCE over the whole table bundle...
        build_sandbox = make_sandbox({"input": {"identifier": None, **test_flow}})
        build_respondent_profiles.run(**build_sandbox)
        _profiles = build_sandbox["self"].output.base_profiles

        # ...then the scorer runs ONCE PER PROFILE, as the foreach does, each iteration seeing its own profile via parent._current_item. The criteria the scorer reads off flow.input; {} would also work (every knob falls back to its default), this exercises the wiring.
        _criteria = {
            "likely_long_term_brand_fan_criteria": {
                "window_days": int(test_window_days.value),
                "min_quizzes": int(test_min_quizzes.value),
                "success_pct": int(test_success_percentage.value),
            }
        }

        _fan = []
        for _profile in _profiles:
            _sandbox = make_sandbox({**test_flow, "input": _criteria}, _profile)
            likely_long_term_brand_fan.run(**_sandbox)
            _fan.append(_sandbox["self"].output.result)

        result = {
            "analysis": _fan,
            "base_profiles": _profiles,
            # "private": build_sandbox["flow"].private.as_dict(),
        }
    else:
        result = {}
    return (result,)


@app.cell
def _(test_min_quizzes, test_success_percentage, test_window_days):
    specific_test_stack = mo.vstack(
        [test_window_days, test_min_quizzes, test_success_percentage],
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
        # "profile": result.get("base_profiles")[_selected_index],
        "analysis": result.get("analysis")[_selected_index],
    } if run_tests.value and _selected_index is not None else None
    return


@app.cell
def _(num_profiles, result):
    mo.accordion({f"Full Results List (**Profile count: {num_profiles}**)": result})
    return


if __name__ == "__main__":
    app.run()
