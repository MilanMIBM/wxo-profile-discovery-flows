from typing import List, Optional, Union

from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType
from ibm_watsonx_orchestrate.agent_builder.tools import tool

# ----- ----- ----- ----- -----
### IMPORTANT NOTE! These are not utilized in the current setup, as they were made for the original concept of baking in the connectors into the flows themselves as connections/python tools, retrieval logic and upload logic are decoupled from the flows and occur outside. The flows in their current version act as a data processing api making them more reusable and easier to manage.
# ----- ----- ----- ----- -----

# A single filter value (str/int/float/bool) or a list of them (match any).
MatchValue = Union[str, int, float, bool, List[Union[str, int, float, bool]]]

# app_id of the key/value connection this tool reads the Postgres connection string from. The connection holds full SQLAlchemy URLs under POSTGRES_CONN_STRING_PUBLIC and/or POSTGRES_CONN_STRING_PRIVATE.
PG_CONNECTOR_APP_ID = "postgres-conn-string"


@tool(
    name="retrieve_database_tables",
    description="Connects to a PostgreSQL database via SQLAlchemy and retrieves rows from one or more tables, optionally filtered by a single column matching a value. Returns a list of results, one entry per table, each carrying the table name and its matching rows as dicts.",
    expected_credentials=[
        {"app_id": PG_CONNECTOR_APP_ID, "type": ConnectionType.KEY_VALUE},
    ],
    # Declare the concrete return shape so downstream tools/agents can bind to `table` and `rows`. Row objects vary per table, so each row is an untyped object (its own keys aren't fixed across tables). Every description must be  a single flat string literal -- the flow builder rejects multi-part (implicitly concatenated) strings.
    output_schema={
        "type": "array",
        "description": "One entry per requested table, each with the table name and its matching rows.",
        "items": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Name of the table these rows came from.",
                },
                "rows": {
                    "type": "array",
                    "description": "Rows from the table as objects keyed by column name. Columns vary per table, so row objects carry no fixed properties.",
                    # The flow object builder requires every `object` to declare `properties`; an empty map keeps rows free-form (arbitrary column keys) while satisfying that rule.
                    "items": {"type": "object", "properties": {}},
                },
            },
            "required": ["table", "rows"],
        },
    },
)
def retrieve_database_tables(
    tables: list,
    match_column: Optional[str] = None,
    match_value: Optional[MatchValue] = None,
    pg_endpoint: Optional[str] = None,
    prefer_private: bool = False,
    limit: Optional[int] = 100,
) -> list:
    """Retrieve rows from one or more database tables.

    Opens a SQLAlchemy engine against a full PostgreSQL connection URL and, for
    each table in `tables`, selects its rows. When `match_column` and
    `match_value` are given, only rows where `match_column = match_value` are
    returned; otherwise every row (up to `limit`) comes back.

    Table and column names can't be bound as SQL parameters, so they are
    whitelisted: table names are validated as safe identifiers and the match
    column is checked against the table's real columns before interpolation.

    Args:
        tables (list): Table names to read from. Each may be schema-qualified
            (e.g. "public.scoring"). At least one is required.
        match_column (Optional[str]): Column to filter each table by. When set,
            only tables that actually have this column are filtered; tables
            lacking it are returned unfiltered. Requires `match_value`.
        match_value (Optional[MatchValue]): Value to match in `match_column`.
            Accepts a single scalar (str/int/float/bool) or a list of them
            (matches any of the values).
        pg_endpoint (Optional[str]): Full SQLAlchemy PostgreSQL connection URL
            (e.g. "postgresql+psycopg2://user:pass@host:port/db?sslmode=..."").
            When omitted, the URL is resolved, in order, from: the
            `postgres-conn-string` key/value connection (its
            POSTGRES_CONN_STRING_PUBLIC / POSTGRES_CONN_STRING_PRIVATE keys),
            then the POSTGRES_CONN_STRING_PUBLIC / POSTGRES_CONN_STRING_PRIVATE
            environment variables (with $VAR expansion).
        prefer_private (bool): When True, prefer the private connection string
            (POSTGRES_CONN_STRING_PRIVATE) over the public one. Falls back to
            whichever is available. Defaults to False (public first).
        limit (Optional[int]): Max rows to return per table. Pass None for no
            limit. Defaults to 100.

    Returns:
        list: One dict per requested table, each shaped as
            {"table": <name>, "rows": [<row dict>, ...]}.

    Raises:
        ValueError: If `tables` is empty, no connection string can be resolved, a
            table name is unsafe, or `match_column` is given without
            `match_value`.
    """
    import sqlalchemy
    from sqlalchemy import text

    if not tables:
        raise ValueError("`tables` must contain at least one table name.")

    endpoint = pg_endpoint or _resolve_conn_string(prefer_private=prefer_private)
    if not endpoint:
        raise ValueError(
            "No connection string: pass `pg_endpoint`, configure the "
            f"{PG_CONNECTOR_APP_ID!r} key/value connection with "
            "POSTGRES_CONN_STRING_PUBLIC / POSTGRES_CONN_STRING_PRIVATE, or set "
            "them as environment variables."
        )

    endpoint = _normalize_conn_string(endpoint)

    if match_column is not None and match_value is None:
        raise ValueError("`match_column` requires a `match_value` to filter on.")

    for tbl in tables:
        if not _is_safe_identifier(tbl):
            raise ValueError(f"unsafe table name: {tbl!r}")

    # Normalise to a list so single value and multi-value share one code path.
    values = None
    if match_column is not None:
        values = (
            list(match_value)
            if isinstance(match_value, (list, tuple, set))
            else [match_value]
        )

    # sslmode is baked into the (normalised) connection string - verify-full is downgraded to require there - so we don't override it via connect_args.
    engine = sqlalchemy.create_engine(endpoint)

    results = []
    with engine.connect() as conn:
        for tbl in tables:
            sql = f"SELECT * FROM {tbl}"
            params = {}

            # Only filter tables that actually have the requested column, so a shared match_column across heterogeneous tables doesn't blow up.
            if match_column is not None and match_column in _table_columns(conn, tbl):
                sql += f' WHERE "{match_column}" IN :vals'
                params = {"vals": values}

            if limit is not None:
                sql += f" LIMIT {int(limit)}"

            stmt = text(sql)
            if params:
                stmt = stmt.bindparams(sqlalchemy.bindparam("vals", expanding=True))

            rows = conn.execute(stmt, params).mappings().all()
            results.append({"table": tbl, "rows": [_jsonable_row(r) for r in rows]})

    return results


def _jsonable_row(row):
    """Convert a SQLAlchemy row mapping to a plain JSON-serialisable dict.

    Postgres types like UUID, TIMESTAMP/date, Decimal, and bytea come back as
    Python objects the Orchestrate serializer can't emit as JSON. jsonb/json
    columns arrive as native dict/list and pass through untouched; other
    non-primitive values are coerced (Decimal -> float, bytes -> decoded/hex,
    everything else -> str) so the declared `rows: array<object>` output schema
    actually serialises.
    """
    import datetime
    import decimal

    def coerce(val):
        if val is None or isinstance(val, (bool, int, float, str)):
            return val
        if isinstance(val, decimal.Decimal):
            # float keeps it numeric; str would be safer for exact precision but breaks numeric consumers. Prefer numeric here.
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
        # UUID, Enum, and anything else unknown -> string.
        return str(val)

    return {key: coerce(value) for key, value in row.items()}


def _resolve_conn_string(prefer_private=False):
    """Resolve a full SQLAlchemy connection string, or "" if unavailable.

    Reads the public/private connection strings from the `postgres-conn-string`
    key/value connection first, falling back to the POSTGRES_CONN_STRING_PUBLIC /
    POSTGRES_CONN_STRING_PRIVATE environment variables (with $VAR expansion).
    `prefer_private` picks the private string when both are present; either way,
    it falls back to whichever one is actually set.
    """
    import os

    public = ""
    private = ""

    # Prefer the bound Orchestrate connection.
    try:
        from ibm_watsonx_orchestrate.run import connections

        creds = connections.key_value(PG_CONNECTOR_APP_ID) or {}
        public = creds.get("POSTGRES_CONN_STRING_PUBLIC", "") or public
        private = creds.get("POSTGRES_CONN_STRING_PRIVATE", "") or private
    except Exception:
        # Connection not bound / running outside Orchestrate -> fall back to env.
        pass

    # Fall back to environment variables (with $VAR expansion) for anything the connection didn't supply.
    if not public:
        public = os.path.expandvars(os.getenv("POSTGRES_CONN_STRING_PUBLIC", ""))
    if not private:
        private = os.path.expandvars(os.getenv("POSTGRES_CONN_STRING_PRIVATE", ""))

    ordered = (private, public) if prefer_private else (public, private)
    for candidate in ordered:
        if candidate:
            return candidate
    return ""


def _normalize_conn_string(url):
    """Normalise a Postgres URL to something the sandbox can actually connect with.

    Two rewrites:

    1. Dialect name: SQLAlchemy's dialect is `postgresql`, not `postgres`, so
       `postgres+psycopg2://...` / `postgres://...` become
       `postgresql+psycopg2://...` / `postgresql://...`.
    2. SSL mode: `verify-full`/`verify-ca` require a CA root cert on disk
       (`~/.postgresql/root.crt`), which doesn't exist in the Orchestrate tool
       sandbox and makes psycopg2 refuse the connection. We downgrade those to
       `sslmode=require` (still encrypted, but no server-cert verification), and
       add `sslmode=require` when no sslmode is present at all.

    URLs already using `postgresql` and a non-verifying sslmode pass through
    unchanged.
    """
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    for prefix in ("postgres+", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql" + url[len("postgres") :]
            break

    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    # verify-full/verify-ca need a CA cert file the sandbox doesn't have; anything else (or nothing) we leave, then ensure require is set as the floor.
    query = [
        (k, v)
        for (k, v) in query
        if not (k == "sslmode" and v in ("verify-full", "verify-ca"))
    ]
    if not any(k == "sslmode" for (k, _) in query):
        query.append(("sslmode", "require"))

    return urlunsplit(parts._replace(query=urlencode(query)))


def _table_columns(conn, table):
    """Return the set of column names for a (possibly schema-qualified) table."""
    import sqlalchemy

    schema, _, name = table.rpartition(".")
    inspector = sqlalchemy.inspect(conn)
    return {col["name"] for col in inspector.get_columns(name, schema=schema or None)}


def _is_safe_identifier(name):
    """Allow a bare or schema-qualified SQL identifier: letters, digits, _, one dot."""
    parts = name.split(".")
    if len(parts) > 2:
        return False
    return all(
        p
        and (p[0].isalpha() or p[0] == "_")
        and all(c.isalnum() or c == "_" for c in p)
        for p in parts
    )


if __name__ == "__main__":
    import json

    # Retrieve all rows from a couple of tables.
    print(
        json.dumps(
            retrieve_database_tables(tables=["quiz_meta", "quiz_structure"]),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    # Retrieve only rows matching a column value.
    print(
        json.dumps(
            retrieve_database_tables(
                tables=["scoring", "details"],
                match_column="quiz_id",
                match_value="some-quiz-id",
            ),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


# Import this tool into watsonx Orchestrate (run from the project root),
# binding the `postgres-conn-string` key/value connection it reads from:
#
# sh/zsh  ./wxo-python-tools/wxo_import_python_tool.sh \
#       -f wxo-python-tools/retrieve_database_tables.py \
#       -r wxo-python-tools/retrieve_database_tables_requirements.txt \
#       -a postgres-conn-string
