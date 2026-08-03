import marimo

__generated_with = "0.23.16"
app = marimo.App(width="columns")

with app.setup:
    import marimo as mo
    import pandas as pd
    import subprocess
    import sqlalchemy
    import psycopg2
    import requests
    import certifi
    import json
    import sys
    import os

    from pathlib import Path
    from typing import List, Union
    from pydantic import BaseModel, Field
    from pymongo import MongoClient
    from dotenv import load_dotenv
    from decimal import Decimal

    parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # `flows` must be imported before `node`, otherwise importing PromptNode
    # directly trips a circular import inside the ADK.
    from ibm_watsonx_orchestrate.flow_builder.flows import Flow
    from ibm_watsonx_orchestrate.flow_builder.node import PromptNode
    from ibm_watsonx_orchestrate.agent_builder.tools import tool


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
        full_width=False,
    )
    # select_prize_url
    return (select_prize_url,)


@app.cell
def _():
    run_tests = mo.ui.run_button(label="Run Node Tests")
    # run_tests
    return (run_tests,)


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


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Python tools
    """)
    return


@app.function
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


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Prompt Nodes
    """)
    return


@app.function
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


@app.function
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


@app.cell(column=2, hide_code=True)
def _():
    mo.md(r"""
    ### Local Flow Node Test
    """)
    return


@app.cell
def _(run_tests, select_prize_url):
    mo.hstack(
        [select_prize_url, run_tests], justify="space-around", align="center"
    )
    return


@app.cell
def _(run_tests, select_prize_url):
    test_url_fetch = (
        fetch_url_data(urls=[select_prize_url.value])
        if select_prize_url.value is not None and run_tests.value
        else None
    )
    return (test_url_fetch,)


@app.cell
def _(run_tests, test_url_fetch):
    url_contents = test_url_fetch.content if run_tests.value else None
    url_contents
    return (url_contents,)


@app.cell
def _(url_contents):
    mo.md(url_contents[0]) if url_contents is not None else None
    return


@app.cell
def _():
    # The prompt nodes cannot be tested locally
    return


if __name__ == "__main__":
    app.run()
