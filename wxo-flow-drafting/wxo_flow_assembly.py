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

    The blocks are defined here rather than imported because marimo's
    `@app.function` cells are not importable across notebooks as plain symbols;
    each node notebook remains the place to *author and locally test* its block,
    and this notebook is the place to *wire and ship* them.
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

    Loose by design: `extra="allow"` lets the full nested profile that
    build_respondent_profiles emits (identity, quizzes, submissions, answers)
    ride through without every level having to be declared here.
    """

    model_config = {"extra": "allow"}

    respondent_id: Optional[str] = Field(
        default=None, description="Id of the respondent."
    )


@app.class_definition
class SustainedEngagementOutput(BaseModel):
    """Outputs of the sustained_engagement_level script node — all optional."""

    respondent_id: Optional[str] = Field(
        default=None, description="Id of the respondent."
    )
    sustained_engagement_level: Optional[int] = Field(
        default=None,
        description="Highest engagement bracket that qualified; empty when none did.",
    )
    respondent_id_obj: Optional[dict] = Field(
        default=None, description='{"respondent_id": ...}'
    )
    sustained_engagement_level_obj: Optional[dict] = Field(
        default=None, description='{"sustained_engagement_level": ...}'
    )
    result: Optional[dict] = Field(
        default=None, description="Both fields together, as a dict."
    )
    result_json: Optional[str] = Field(
        default=None, description="Both fields together, as a JSON string."
    )


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


@app.cell
def _():
    # Authored and locally tested in wxo_base_profile_node.py; imported here
    # so there is exactly one definition of each.
    from wxo_base_profile_node import (
        build_respondent_profiles,
        merge_profile_signals,
    )

    return build_respondent_profiles, merge_profile_signals


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


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
    profile = dict(parent._current_item or {})

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


@app.cell(column=3, hide_code=True)
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
    merge_profile_signals,
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
        build = build_respondent_profiles(aflow)

        # One iteration per respondent; PARALLEL since respondents are independent.
        each: Flow = aflow.foreach(
            item_schema=RespondentProfileItem,
            name="for_each_respondent",
            display_name="For each respondent",
        ).policy(kind=ForeachPolicy.PARALLEL)

        # Both scorers run concurrently. Each branch is wired START -> node -> END
        # inside the parallel subflow; that internal END is the join, so `merge`
        # runs only once both have finished.
        scorers: Flow = each.parallel(
            evaluator=None,
            name="score_respondent",
            display_name="Score respondent",
        )
        engagement = sustained_engagement_level(scorers)
        brand_fan = likely_long_term_brand_fan(scorers)
        scorers.sequence(START, engagement, END)
        scorers.sequence(START, brand_fan, END)

        # Adds both scorers' results onto this iteration's profile.
        merge = merge_profile_signals(each)
        each.sequence(START, scorers, merge, END)

        aflow.sequence(START, build, each, END)
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
def _(flows_client):
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
            flow_input=test_flow.get("retrieve_tables"),
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
