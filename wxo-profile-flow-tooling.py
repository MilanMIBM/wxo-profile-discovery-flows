import marimo

__generated_with = "0.23.14"
app = marimo.App(width="columns")

with app.setup:
    import marimo as mo
    import pandas as pd
    import sqlalchemy
    import psycopg2
    import requests
    import certifi
    import json
    import sys
    import os

    from pathlib import Path
    from typing import List, Union, Optional, Any
    from pydantic import BaseModel, Field
    from pymongo import MongoClient
    from dotenv import load_dotenv
    from decimal import Decimal


@app.cell
def _():
    from ibm_watsonx_orchestrate.flow_builder.flows import (
        END,
        START,
        Flow,
        flow,
    )
    from ibm_watsonx_orchestrate.flow_builder.types import (
        ForeachPolicy,
        PythonTool,
    )
    from ibm_watsonx_orchestrate.agent_builder.tools import tool

    return Flow, tool


@app.cell
def _():
    from src.helpers.logic_block import logic_block

    return (logic_block,)


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
    postgresql_engine
    return (postgresql_engine,)


@app.cell
def _(mongodb_endpoint):
    mongodb = MongoClient(mongodb_endpoint)
    mongodb
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Test Data Import**
    """)
    return


@app.cell
def _():
    rewrite_tables = True
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
        engine=postgresql_engine,
    )
    return (quiz_meta,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_structure = mo.sql(
        f"""
        SELECT * FROM "quiz_structure" LIMIT 1000
        """,
        engine=postgresql_engine,
    )
    return (quiz_structure,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_details = mo.sql(
        f"""
        SELECT * FROM "quiz_details" LIMIT 1000
        """,
        engine=postgresql_engine,
    )
    return (quiz_details,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    quiz_scoring = mo.sql(
        f"""
        SELECT * FROM "quiz_scoring" LIMIT 1000
        """,
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
        engine=postgresql_engine,
    )
    return (quiz_ids_unique,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    user_emails = mo.sql(
        f"""
        SELECT DISTINCT "email" FROM "quiz_scoring"
        """,
        engine=postgresql_engine,
    )
    return (user_emails,)


@app.cell(hide_code=True)
def _(postgresql_engine):
    prize_urls = mo.sql(
        f"""
        SELECT DISTINCT "prize.prize_name", "prize.prize_url" FROM "quiz_meta" WHERE "prize.prize_url" IS NOT NULL
        """,
        engine=postgresql_engine,
    )
    return (prize_urls,)


@app.cell
def _(prize_urls):
    prize_urls_list = prize_urls["prize.prize_url"].to_list()
    prize_names_list = prize_urls["prize.prize_name"].to_list()
    _prize_url_mapping = dict(zip(prize_names_list, prize_urls_list))

    select_prize_url = mo.ui.dropdown(
        label="**Select prize URL:**",
        options=_prize_url_mapping,
        value=prize_names_list[0],
        full_width=True,
    )
    select_prize_url
    return (select_prize_url,)


@app.cell
def _(select_prize_url):
    print(select_prize_url.value)
    return


@app.cell
def _(user_emails):
    user_emails_list = user_emails.email.to_list()
    select_user = mo.ui.dropdown(
        label="**Select user email:**",
        options=user_emails_list,
        value=user_emails_list[0],
    )
    select_user
    return


@app.cell
def _(quiz_ids_unique):
    quiz_id_list = quiz_ids_unique.quizId.to_list()
    select_quiz_id = mo.ui.dropdown(
        label="**Select Quiz ID:**", options=quiz_id_list, value=quiz_id_list[0]
    )
    select_quiz_id
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


@app.cell(column=1, hide_code=True)
def _():
    mo.md(r"""
    ### Class definitions
    """)
    return


@app.class_definition
class FetchUrlDataOutput(BaseModel):
    """The converted documents, one string per requested URL."""

    documents: List[str] = Field(
        ...,
        description="""The converted content, one entry per requested URL, in the order the URLs were supplied. Always a list, even for a single URL. A URL that failed to convert yields an entry beginning with 'ERROR:' followed by the reason.""",
    )


@app.class_definition
class PrizeInfo(BaseModel):
    brand_name: str = Field(description="Brand that provides the prize.")
    prize_name: str = Field(description="Name of the prize.")
    prize_description: str = Field(
        description="Free-text description of the prize."
    )
    prize_value: Decimal = Field(
        description="Numeric price of the prize, excluding currency. Supports decimals."
    )
    prize_currency: str = Field(
        description="ISO 4217 currency code for the price, e.g. 'USD', 'EUR', 'NOK'."
    )
    tag_type: str = Field(
        description="Descriptor the generated tags must match, e.g. 'material', 'use case', 'audience'."
    )
    number_of_tags: int = Field(
        description="How many metadata tags to generate."
    )


@app.class_definition
class Tags(BaseModel):
    metadata_tags: list[str] = Field(description="Output tags.")


@app.class_definition
class MetadataTags(BaseModel):
    tags: Tags = Field(
        description="Object wrapper for the metadata tag output."
    )


@app.class_definition
class PrizePageContent(BaseModel):
    """The fetched page text handed to the cleaner."""

    page_content: str = Field(
        description="""Raw converted page content (Markdown or plain text) for a single prize page, as produced by the fetch_url_data tool."""
    )


@app.class_definition
class CleanedPrizeDescription(BaseModel):
    """The prize specification text, stripped of everything else."""

    prize_description: str = Field(
        description="""The cleaned prize description containing only specification-related content: what the prize is, its physical and technical specs, materials, dimensions, capacities, compatibility, included contents and variants. Empty string if the page contained no prize specifications."""
    )


@app.cell
def _(QuizEngagement, RespondentIdentity):
    class RespondentProfile(BaseModel):
        """Base profile of one quiz respondent, aggregated across their submissions."""

        respondent_id: Optional[str] = Field(
            default=None,
            description="Id of the respondent (first submission id).",
        )
        context_record_id: Optional[str] = Field(
            default=None,
            description="Caller-supplied identifier, or the respondent_id when unset.",
        )
        quizzes_num: int = Field(
            default=0,
            description="Number of distinct quizzes the respondent took.",
        )
        identity: Optional[RespondentIdentity] = Field(
            default=None, description="Identity fields of the respondent."
        )
        quizzes: List[QuizEngagement] = Field(
            default_factory=list,
            description="Per-quiz engagement records for this respondent.",
        )

    return (RespondentProfile,)


@app.cell
def _(RespondentProfile):
    class BuildProfilesOutput(BaseModel):
        """Output of the build_respondent_profiles script node."""

        profiles: List[RespondentProfile] = Field(
            default_factory=list,
            description="One base profile per quiz respondent, ready to iterate.",
        )

    return (BuildProfilesOutput,)


@app.cell
def _():
    return


@app.cell
def _():
    return


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ## Logic blocks
    """)
    return


@app.cell
def _(BuildProfilesOutput, logic_block):
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
        output_schema=BuildProfilesOutput,
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

    return (build_respondent_profiles,)


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

    def make_sandbox(flow_data):
        node = _Bag()
        node.output = _Bag()
        return {"flow": _FlowStub(flow_data), "self": node, "json": json}

    return (make_sandbox,)


@app.cell
def _(build_respondent_profiles, make_sandbox, test_flow):
    sandbox = make_sandbox({**test_flow, "input": {"identifier": None}})
    build_respondent_profiles.run(**sandbox)
    result = {
        "profiles": sandbox["self"].output.profiles,
        "private": sandbox["flow"].private.as_dict(),
    }
    return (result,)


@app.cell
def _(result):
    result.get("profiles")[2]
    return


@app.cell
def _():
    return


@app.cell(column=3, hide_code=True)
def _():
    mo.md(r"""
    ## Python tools
    """)
    return


@app.cell
def _(tool):
    @tool(
        name="fetch_url_data",
        display_name="Fetch URL Data",
        description="""Fetches one or more URLs and converts each document into Markdown or plain text using Docling. Use this to read the contents of a web page or an online document (PDF, DOCX, PPTX, HTML) so the text can be summarized or analyzed.""",
    )
    def fetch_url_data(
        urls: Union[str, List[str]],
        return_markdown_output: bool = True,
    ) -> FetchUrlDataOutput:
        """Fetches and converts the content of one or more URLs using Docling.

        Each URL is downloaded and parsed with Docling's DocumentConverter, then exported
        as Markdown or plain text. The result is always a list of strings, one per URL, in
        the order supplied - a single URL yields a one-element list. A failure on one URL
        does not abort the others; that entry is an 'ERROR: ...' string instead.

        Args:
            urls (Union[str, List[str]]): A single URL or a list of URLs to fetch and convert.
            return_markdown_output (bool): True (default) to export Markdown, False for plain text.

        Returns:
            FetchUrlDataOutput: The converted content, one string per requested URL.
        """
        from docling.document_converter import DocumentConverter

        url_list: List[str] = [urls] if isinstance(urls, str) else list(urls)

        converter = DocumentConverter()
        documents: List[str] = []

        for url in url_list:
            try:
                result = converter.convert(url)
                documents.append(
                    result.document.export_to_markdown()
                    if return_markdown_output
                    else result.document.export_to_text()
                )
            except Exception as exc:  # noqa: BLE001 - one bad URL must not fail the batch
                documents.append(
                    f"ERROR: {url} could not be converted - {type(exc).__name__}: {exc}"
                )

        return documents
        # return FetchUrlDataOutput(documents=documents)
    return (fetch_url_data,)


@app.cell
def _(fetch_url_data, select_prize_url):
    test_url_fetch = (
        fetch_url_data(urls=[select_prize_url.value])
        if select_prize_url.value is not None
        else None
    )
    return (test_url_fetch,)


@app.cell
def _(test_url_fetch):
    test_url_fetch.content
    return


@app.cell
def _():
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Prompt Nodes
    """)
    return


@app.cell
def _(Flow, PromptNode):
    def build_prompt_extract_prize_details(aflow: Flow) -> PromptNode:
        extract_prize_details = aflow.prompt(
            name="extract_prize_details",
            display_name="extract_prize_details",
            description="Reduce a fetched prize text from a url to only its product specification content.",
            system_prompt=[
                """Parse the provided prize content information according to the elements to preserve while dropping the ones specified as irrelevant.
                    - Elements to Preserve: what the product is, model and variant names, materials and construction, dimensions, weight, capacity, power, performance figures, technical and compatibility details, certifications, included contents, available sizes and colours. 
                    - Elements to Drop: navigation, menus, breadcrumbs, cookie and consent banners, legal and privacy text, pricing, stock and delivery information, promotions and discounts, customer reviews and ratings, social and sharing links, newsletter signups, related or recommended products, company and brand marketing copy, and any other page furniture.
                    Preserve the original wording of specs rather than paraphrasing. Do not add headings, commentary, or preamble. If the text contains no product specifications, or begins with 'ERROR:' return 'No Text'""",
            ],
            user_prompt=[
                """
                        Fetched prize content:
                        ---

                        {self.input.page_content}

                        ---
                        """
            ],
            llm="groq/openai/gpt-oss-120b",
            llm_parameters={
                "temperature": 0,
                "min_new_tokens": 1,
                "max_new_tokens": 4096,
                "top_k": 50,
                "top_p": 1,
                "stop_sequences": ["<|return|>"],
            },
            error_handler_config={
                "error_message": "An error has occurred while invoking the LLM",
                "max_retries": 1,
                "retry_interval": 1000,
            },
            input_schema=PrizePageContent,
            output_schema=CleanedPrizeDescription,
        )

        return extract_prize_details

    return


@app.cell
def _(Flow, PromptNode):
    def build_prompt_metadata_tag_generation(aflow: Flow) -> PromptNode:
        metadata_tag_generation = aflow.prompt(
            name="prize_metadata_tag_generation",
            display_name="prize_metadata_tag_generation",
            description="Use data about the prize to generate metadata tags as additional descriptors.",
            system_prompt=[
                """Generate {self.input.number_of_tags} metadata tags related to the provided prize. Generate tags that match the following descriptor: {self.input.tag_type}."""
            ],
            user_prompt=[
                """
                Brand Name: {self.input.brand_name}
                Prize Name: {self.input.prize_name}
                Prize Value: {self.input.prize_value} {self.input.prize_currency}
                Prize Description:
                ---

                {self.input.prize_description}

                ---   
                """
            ],
            llm="groq/openai/gpt-oss-120b",
            llm_parameters={
                "temperature": 0.7,
                "min_new_tokens": 1,
                "max_new_tokens": 1024,
                "top_k": 50,
                "top_p": 1,
                "stop_sequences": ["<|return|>"],
            },
            error_handler_config={
                "error_message": "An error has occurred while invoking the LLM",
                "max_retries": 1,
                "retry_interval": 1000,
            },
            input_schema=PrizeInfo,
            output_schema=MetadataTags,
        )
        return metadata_tag_generation

    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
