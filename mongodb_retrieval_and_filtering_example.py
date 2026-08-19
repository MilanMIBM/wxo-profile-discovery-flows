import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")

with app.setup:
    import marimo as mo
    import pandas as pd
    import subprocess
    import datetime
    import json
    import sys
    import os
    import re

    from pathlib import Path
    from typing import List, Dict, Any
    from dotenv import load_dotenv

    ### --- Only use if you nest it in a subfolder ---
    # parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    # if parent_dir not in sys.path:
    #     sys.path.insert(0, parent_dir)
    ### --- --- --- --- ---
    from pymongo import MongoClient

    # Custom helper imports
    from src.helpers.marimo_ui_helpers import accordion_preview
    from src.helpers.marimo_floating_card_view_v2 import floating_card_view
    from src.helpers.mongodb_document_helpers import (
        upload_documents,
        update_documents,
        purge_documents,
        retrieve_documents,
        pluck_document_values,
        discover_document_fields,
    )

    load_dotenv("config/.env", override=True)


@app.cell
def _():
    mongodb_endpoint = os.path.expandvars(os.getenv("MONGODB_ENDPOINT", ""))
    ibmcloud_cert_path = os.path.expandvars(
        os.getenv("IBMCLOUD_DB_CERT_PATH", "")
    )
    return ibmcloud_cert_path, mongodb_endpoint


@app.cell
def _(ibmcloud_cert_path, mongodb_endpoint, mongodblist_collection_names):
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
        print(f"Existing MongoDB collections: {mongodblist_collection_names()}")
    return mongodb, mongodb_client


@app.cell
def _(mongodb):
    mongodb_collections = mongodb.list_collection_names()
    return (mongodb_collections,)


@app.cell
def _(mongodb_collections):
    select_collection = mo.ui.dropdown(
        label="**Select the Collection**",
        options=mongodb_collections,
        value=(mongodb_collections[0] if mongodb_collections else None),
    )
    # select_collection
    return (select_collection,)


@app.cell
def _():
    retrieve_documents_test = mo.ui.run_button(
        label="**Retrieve MongoDB Documents Test**"
    )
    # retrieve_documents_test
    return (retrieve_documents_test,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## **MongoDB document retrieval and filtering example**
    ----
    """)
    return


@app.cell
def _():
    fields_to_retrieve_input = mo.ui.text_area(
        label="**Add Fields to retrieve, delineated by commas:**",
        rows=3,
        full_width=True,
        placeholder="Leave blank for all fields.",
    )
    # fields_to_retrieve_input
    return (fields_to_retrieve_input,)


@app.cell
def _(fields_to_retrieve_input):
    fields_to_retrieve = [
        f.strip()
        for f in fields_to_retrieve_input.value.split(",")
        if f.strip()
    ]
    print(fields_to_retrieve)
    return (fields_to_retrieve,)


@app.cell
def _():
    selectors_input = mo.ui.text_area(
        label="**Add Selectors (query filter), one per line as `field: value`:**",
        rows=3,
        full_width=True,
        placeholder="Leave blank for all documents.\nstatus: active\nlanguage: en",
    )
    # selectors_input
    return (selectors_input,)


@app.cell(hide_code=True)
def _(selectors_input):
    def _coerce_selector_value(raw: str):
        """Turn a typed value into int/float/bool/null/JSON where it plainly is one."""
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    selectors_to_apply = {}
    for selector_chunk in re.split(r"[,\n]", selectors_input.value):
        selector_chunk = selector_chunk.strip()
        if not selector_chunk or ":" not in selector_chunk:
            continue
        selector_field, _, selector_raw = selector_chunk.partition(":")
        selector_field = selector_field.strip()
        if selector_field:
            selectors_to_apply[selector_field] = _coerce_selector_value(
                selector_raw.strip()
            )
    print(selectors_to_apply)
    return (selectors_to_apply,)


@app.cell
def _():
    sort_input = mo.ui.text_area(
        label="**Add Sort fields, as `field: asc / desc` pairs:**",
        rows=3,
        full_width=True,
        placeholder="Leave blank for no sorting.\ncreated_at: desc, name: asc",
    )
    # sort_input
    return (sort_input,)


@app.cell(hide_code=True)
def _(sort_input):
    _SORT_DIRECTIONS = {
        "asc": 1,
        "ascending": 1,
        "1": 1,
        "desc": -1,
        "descending": -1,
        "-1": -1,
    }
    sort_to_apply = {}
    for sort_chunk in re.split(r"[,\n]", sort_input.value):
        sort_chunk = sort_chunk.strip()
        if not sort_chunk:
            continue
        sort_field, _, sort_direction = sort_chunk.partition(":")
        sort_field = sort_field.strip()
        if sort_field:
            sort_to_apply[sort_field] = _SORT_DIRECTIONS.get(
                sort_direction.strip().lower(), 1
            )
    print(sort_to_apply)
    return (sort_to_apply,)


@app.cell
def _():
    retrieve_number = mo.ui.number(
        label="**Control number of records to retrieve:**",
        start=0,
        stop=1000,
        step=1,
        value=100,
        # full_width=True,
    )
    # retrieve_number
    return (retrieve_number,)


@app.cell
def _(select_collection):
    mongodb_collection_name = select_collection.value
    return (mongodb_collection_name,)


@app.cell
def _(retrieve_documents_test, retrieve_number, select_collection):
    retrieve_stack = mo.hstack(
        [select_collection, retrieve_number, retrieve_documents_test],
        justify="space-around",
    )
    retrieve_stack
    return


@app.cell
def _(fields_to_retrieve_input, selectors_input, sort_input):
    filter_stack = accordion_preview(
        name="**Filter setup** *(click to fold/unfold)*",
        value=mo.hstack(
            [
                fields_to_retrieve_input,
                selectors_input,
                sort_input,
            ],
            justify="space-around",
            gap=1,
        ),
    )
    filter_stack
    return


@app.cell
def _(retrieved_docs):
    field_option_preview = (
        accordion_preview(
            name="Preview fields accessible in the retrieved documents",
            value=discover_document_fields(retrieved_docs),
        )
        if retrieved_docs is not None
        else None
    )
    field_option_preview
    return


@app.cell
def _(
    fields_to_retrieve,
    mongodb,
    mongodb_client,
    mongodb_collection_name,
    retrieve_documents_test,
    retrieve_number,
    selectors_to_apply,
    sort_to_apply,
):
    if (
        mongodb_client
        and mongodb_collection_name
        and retrieve_documents_test.value
    ):
        retrieved_docs = retrieve_documents(
            mongodb,
            mongodb_collection_name,
            selectors=selectors_to_apply or None,
            fields=fields_to_retrieve or None,
            sort=sort_to_apply or None,
            limit=retrieve_number.value or None,
        )
        print(len(retrieved_docs))
    else:
        retrieved_docs = None
    return (retrieved_docs,)


@app.cell
def _(retrieved_docs):
    view_retrieved_mongodb_docs = (
        accordion_preview(
            floating_card_view(retrieved_docs),
            name="**Preview MongoDB documents as floating cards**",
            nested_value=[retrieved_docs],
            nested_name="retrieve_mongodb_documents JSON list",
        )
        if retrieved_docs is not None
        else None
    )
    return (view_retrieved_mongodb_docs,)


@app.cell
def _(view_retrieved_mongodb_docs):
    view_retrieved_mongodb_docs
    return


@app.cell
def _(retrieved_docs):
    retrieved_docs_df = (
        pd.DataFrame(retrieved_docs)
        if retrieved_docs is not None
        else pd.DataFrame({})
    )
    return


if __name__ == "__main__":
    app.run()
