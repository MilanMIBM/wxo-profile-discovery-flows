from typing import Optional

from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType
from ibm_watsonx_orchestrate.agent_builder.tools import tool

# app_id of the key/value connection this tool reads the MongoDB connection
# string from. The connection holds the full URL under MONGODB_CONN_STRING (or
# MONGODB_ENDPOINT) and, for IBM Cloud Databases, the CA certificate under
# MONGODB_CA_CERT_BASE64.
MONGO_CONNECTOR_APP_ID = "mongodb-conn-string"


@tool(
    name="upload_enriched_profile",
    description="Uploads one enriched respondent profile into a MongoDB collection as its own document. Upserts by respondent_id when the document carries one, so re-runs replace instead of duplicating.",
    expected_credentials=[
        {"app_id": MONGO_CONNECTOR_APP_ID, "type": ConnectionType.KEY_VALUE},
    ],
    # Declare the concrete return shape so downstream nodes can bind to the
    # individual fields. Every description must be a single flat string literal --
    # the flow builder rejects multi-part (implicitly concatenated) strings.
    output_schema={
        "type": "object",
        "description": "Summary of the write that was performed.",
        "properties": {
            "database": {
                "type": "string",
                "description": "Database written to.",
            },
            "collection": {
                "type": "string",
                "description": "Collection written to.",
            },
            "operation": {
                "type": "string",
                "description": "Either inserted or replaced.",
            },
            "document_id": {
                "type": "string",
                "description": "Mongo _id of an inserted document, or the upsert key value of a replaced one.",
            },
        },
        "required": ["database", "collection", "operation", "document_id"],
    },
)
def upload_enriched_profile(
    document: dict,
    collection: str = "enriched_profiles",
    database: str = "ibmclouddb",
    document_json: Optional[str] = None,
    mongodb_endpoint: Optional[str] = None,
    upsert_key: Optional[str] = "respondent_id",
) -> dict:
    """Uploads one enriched respondent profile document into MongoDB.

    Connects to MongoDB and writes the given document into the target
    collection. When `upsert_key` names a field present in the document, the
    write is an upsert on that field, so re-runs replace the existing document
    instead of duplicating it; otherwise a plain insert is performed.

    Args:
        document (dict): The enriched profile document to upload.
        collection (str): Target collection name. Defaults to
            "enriched_profiles".
        database (str): Target database name. Defaults to "ibmclouddb".
        document_json (Optional[str]): JSON-encoded fallback for `document`,
            parsed only when `document` is empty. Useful when the caller can
            only pass a string.
        mongodb_endpoint (Optional[str]): Full MongoDB connection URL. When
            omitted, the URL is resolved, in order, from: the
            `mongodb-conn-string` key/value connection (its MONGODB_CONN_STRING
            / MONGODB_ENDPOINT keys), then the MONGODB_ENDPOINT environment
            variable (with $VAR expansion).
        upsert_key (Optional[str]): Document field to upsert on. Pass None or an
            empty string to always insert. Defaults to "respondent_id".

    Returns:
        dict: {"database", "collection", "operation", "document_id"} where
            operation is either "inserted" or "replaced".

    Raises:
        ValueError: If no document is given, or no connection string can be
            resolved.
    """
    import json
    import os

    from pymongo import MongoClient

    doc = document or (json.loads(document_json) if document_json else None)
    if not doc:
        raise ValueError("`document` (or `document_json`) is required.")

    creds = _resolve_credentials()
    endpoint = (
        mongodb_endpoint
        or creds.get("MONGODB_CONN_STRING")
        or creds.get("MONGODB_ENDPOINT")
        or os.path.expandvars(os.getenv("MONGODB_ENDPOINT", ""))
    )
    if not endpoint:
        raise ValueError(
            "No connection string: pass `mongodb_endpoint`, configure the "
            f"{MONGO_CONNECTOR_APP_ID!r} key/value connection with "
            "MONGODB_CONN_STRING / MONGODB_ENDPOINT, or set the "
            "MONGODB_ENDPOINT environment variable."
        )

    connect_kwargs = {}
    ca_file = _resolve_ca_file(creds)
    if ca_file:
        connect_kwargs["tlsCAFile"] = ca_file

    client = MongoClient(endpoint, serverSelectionTimeoutMS=10000, **connect_kwargs)
    try:
        coll = client[database][collection]
        key_val = doc.get(upsert_key) if upsert_key else None
        if key_val is not None:
            # Upsert: a re-run of the flow replaces the respondent's document
            # rather than appending a second copy of it.
            result = coll.replace_one({upsert_key: key_val}, doc, upsert=True)
            operation = "inserted" if result.upserted_id is not None else "replaced"
            document_id = (
                str(result.upserted_id)
                if result.upserted_id is not None
                else str(key_val)
            )
        else:
            inserted = coll.insert_one(doc)
            operation = "inserted"
            document_id = str(inserted.inserted_id)
    finally:
        client.close()

    return {
        "database": database,
        "collection": collection,
        "operation": operation,
        "document_id": document_id,
    }


def _resolve_credentials():
    """Return the key/value pairs of the bound connection, or {} if unavailable.

    Falls back to an empty dict when the connection isn't bound (running outside
    Orchestrate, e.g. a local unit test), so the caller can fall back to
    environment variables. The accessor raises SystemExit -- a BaseException, not
    an Exception -- when no credentials are bound, hence the broad catch.
    """
    try:
        from ibm_watsonx_orchestrate.run import connections

        return connections.key_value(MONGO_CONNECTOR_APP_ID) or {}
    except BaseException:
        return {}


def _resolve_ca_file(creds):
    """Return a path to the CA cert file, or "" when none is configured.

    IBM Cloud Databases requires its CA certificate, but the Orchestrate tool
    sandbox has no cert on disk, so the connection carries it base64-encoded
    (MONGODB_CA_CERT_BASE64) and it is materialized to a temp file here. A local
    path (IBMCLOUD_DB_CERT_PATH) is honoured as a fallback for local runs.
    """
    import base64
    import os
    import tempfile

    ca_b64 = creds.get("MONGODB_CA_CERT_BASE64") or os.getenv(
        "MONGODB_CA_CERT_BASE64", ""
    )
    if ca_b64:
        tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
        tmp.write(base64.b64decode(ca_b64))
        tmp.close()
        return tmp.name

    ca_path = os.path.expandvars(os.getenv("IBMCLOUD_DB_CERT_PATH", ""))
    if ca_path and os.path.exists(ca_path):
        return ca_path

    return ""


if __name__ == "__main__":
    import json

    # Upload a single throwaway profile document. Reads MONGODB_ENDPOINT from the
    # environment; run against a scratch collection.
    print(
        json.dumps(
            upload_enriched_profile.fn(
                document={
                    "respondent_id": "local-test-1",
                    "identity": {"email": "test@example.com"},
                    "categorization": {
                        "sustained_engagement_level": 2,
                        "respondent_behavioral_metatags": ["likely_long_term_brand_fan"],
                    },
                },
                collection="enriched_profiles_scratch",
            ),
            indent=2,
        )
    )


# Import this tool into watsonx Orchestrate (run from the project root), binding
# the `mongodb-conn-string` key/value connection it reads from. The connection
# must exist first -- see src/helpers/connections/.
#
#   orchestrate tools import -k python \
#       -f src/helpers/tools/upload-enriched-profile/upload_enriched_profile.py \
#       -r src/helpers/tools/upload-enriched-profile/upload_enriched_profile_requirements.txt \
#       -a mongodb-conn-string
