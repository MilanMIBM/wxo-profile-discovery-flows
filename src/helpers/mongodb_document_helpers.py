"""Minimal MongoDB document helpers: upload, update, and purge.

Every function takes a ``pymongo.MongoClient`` (or a ``Database``) as its first
argument, so there is no client class or ``self`` to carry around::

    from pymongo import MongoClient
    mongodb = MongoClient(mongodb_endpoint)

    upload_documents(mongodb, "quiz_meta", docs)
    update_documents(mongodb, "quiz_meta", docs)
    purge_documents(mongodb, "quiz_meta")

The database is taken from the connection URI's default database unless a
``db_name`` is passed explicitly (Atlas ``mongodb+srv://`` URIs usually carry
no default database, so pass ``db_name`` there).

Uploads can be made idempotent with ``check_for_existing``: name the field that
identifies a document and already-present documents are skipped instead of
duplicated, refreshed in place with ``on_existing="update"``, or replaced
wholesale with ``on_existing="overwrite"``::

    upload_documents(mongodb, "quiz_meta", docs, check_for_existing="quiz_id")
    upload_documents(mongodb, "quiz_meta", docs,
                check_for_existing="quiz_id", on_existing="update")
    upload_documents(mongodb, "quiz_meta", docs,
                check_for_existing="quiz_id", on_existing="overwrite")

``"update"`` merges the incoming fields into the stored document and leaves its
other fields alone; ``"overwrite"`` re-uploads the document as given, so stored
fields the incoming document does not carry are dropped (the stored ``_id`` is
kept either way).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union

import uuid

from pymongo import MongoClient, ReplaceOne, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import BulkWriteError, ConfigurationError

# A MongoClient or an already-selected Database is accepted everywhere.
MongoTarget = Union[MongoClient, Database]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_database(mongodb: MongoTarget, db_name: Optional[str] = None) -> Database:
    """Resolve the working ``Database`` from a client (or pass a Database through).

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        db_name: Explicit database name. When omitted, the URI's default
            database is used (and a ``Database`` argument is returned as-is).

    Raises:
        ValueError: When no database can be determined.
    """
    if isinstance(mongodb, Database):
        return mongodb.client[db_name] if db_name else mongodb
    if mongodb is None:
        raise ValueError("mongodb client is None.")
    if db_name:
        return mongodb[db_name]
    try:
        return mongodb.get_default_database()
    except ConfigurationError as exc:
        raise ValueError(
            "No database name given and the connection URI carries no default "
            "database. Pass db_name=... (required for mongodb+srv:// Atlas URIs)."
        ) from exc


def _resolve_collection(
    mongodb: MongoTarget,
    collection: str,
    db_name: Optional[str] = None,
) -> Collection:
    """Return the ``Collection`` object for *collection* in the resolved database."""
    return _resolve_database(mongodb, db_name)[collection]


def _as_doc_list(docs: Union[Dict, List[Dict]]) -> List[Dict[str, Any]]:
    """Normalise the accepted document inputs into a plain list of dicts.

    Accepts a list of docs, a single doc, or a ``{"results": [...]}`` wrapper.
    """
    if isinstance(docs, dict):
        if "results" in docs and isinstance(docs["results"], list):
            return list(docs["results"])
        return [docs]
    if isinstance(docs, list):
        return list(docs)
    raise ValueError(
        "docs must be a list of dicts, a single dict, or a dict with a 'results' list."
    )


def _batched(items: Sequence[Any], batch_size: int) -> Iterator[Sequence[Any]]:
    """Yield consecutive slices of *items* of at most *batch_size* elements."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


# Sentinel marking an absent path, so a stored ``None`` stays distinguishable
# from a key that was never there.
_MISSING = object()


def _stringify_ids(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert non-string ``_id`` values (e.g. ObjectId) to ``str`` in place."""
    for doc in docs:
        if "_id" in doc and not isinstance(doc["_id"], str):
            doc["_id"] = str(doc["_id"])
    return docs


# ---------------------------------------------------------------------------
# Existence checks (shared by the upload / update paths)
# ---------------------------------------------------------------------------


def _stored_key_values(
    target: Collection,
    key: str,
    values: List[Any],
    batch_size: int,
) -> set:
    """Return the subset of *values* already stored in *target* under *key*.

    Resolved with batched ``$in`` queries, so checking a large upload costs a
    handful of round trips rather than one per document. Unhashable values (a
    list or dict used as an identity key) cannot be collected into a set and are
    left to the per-document fallback in :func:`_partition_by_existing`.
    """
    candidates: List[Any] = []
    seen: set = set()
    for value in values:
        try:
            if value in seen:
                continue
            seen.add(value)
        except TypeError:
            continue  # unhashable; handled per-document by the caller
        candidates.append(value)

    stored: set = set()
    for batch in _batched(candidates, batch_size):
        for doc in target.find({key: {"$in": list(batch)}}, {key: 1}):
            if key in doc:
                stored.add(doc[key])
    return stored


def _partition_by_existing(
    target: Collection,
    docs: List[Dict[str, Any]],
    key: str,
    batch_size: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split *docs* into ``(new, existing)`` on whether *key*'s value is stored.

    Documents that do not carry *key* at all are treated as new. Within *docs*
    itself, a repeated key value counts as existing after its first occurrence,
    so a payload listing the same document twice still inserts it once.
    """
    stored = _stored_key_values(
        target, key, [doc[key] for doc in docs if key in doc], batch_size
    )

    new_docs: List[Dict[str, Any]] = []
    existing_docs: List[Dict[str, Any]] = []
    seen_in_payload: set = set()

    for doc in docs:
        if key not in doc:
            new_docs.append(doc)
            continue
        value = doc[key]
        try:
            already_present = value in stored or value in seen_in_payload
            seen_in_payload.add(value)
        except TypeError:
            already_present = target.count_documents({key: value}, limit=1) > 0
        (existing_docs if already_present else new_docs).append(doc)

    return new_docs, existing_docs


def _build_update_operations(
    docs: List[Dict[str, Any]],
    keys: List[str],
    upsert: bool,
    collection: str,
) -> List[UpdateOne]:
    """Turn documents into ``UpdateOne`` ops filtered on their own *keys* fields.

    Raises:
        ValueError: When a document lacks one of *keys*, or when ``$set`` would
            be empty because the document holds nothing but the key fields.
    """
    operations: List[UpdateOne] = []
    for i, doc in enumerate(docs):
        missing = [key for key in keys if key not in doc]
        if missing:
            raise ValueError(
                f"Document at index {i} is missing {missing}, required to match "
                f"an existing document in '{collection}'."
            )
        update_data = {k: v for k, v in doc.items() if k not in keys}
        if not update_data:
            raise ValueError(
                f"Document at index {i} has no fields to update besides {keys}."
            )
        operations.append(
            UpdateOne(
                {key: doc[key] for key in keys},
                {"$set": update_data},
                upsert=upsert,
            )
        )
    return operations


def _build_replace_operations(
    docs: List[Dict[str, Any]],
    keys: List[str],
    upsert: bool,
    collection: str,
) -> List[ReplaceOne]:
    """Turn documents into ``ReplaceOne`` ops filtered on their own *keys* fields.

    Unlike :func:`_build_update_operations`, the stored document is replaced
    wholesale: fields it holds that the incoming document does not are dropped.
    ``_id`` is stripped from the replacement so the stored document keeps its
    own id (MongoDB rejects a replacement that alters ``_id``).

    Raises:
        ValueError: When a document lacks one of *keys*.
    """
    operations: List[ReplaceOne] = []
    for i, doc in enumerate(docs):
        missing = [key for key in keys if key not in doc]
        if missing:
            raise ValueError(
                f"Document at index {i} is missing {missing}, required to match "
                f"an existing document in '{collection}'."
            )
        replacement = {k: v for k, v in doc.items() if k != "_id"}
        operations.append(
            ReplaceOne(
                {key: doc[key] for key in keys},
                replacement,
                upsert=upsert,
            )
        )
    return operations


def _run_bulk_update(
    target: Collection,
    operations: Sequence[Union[UpdateOne, ReplaceOne]],
    batch_size: int,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Execute *operations* with batched ``bulk_write`` and total up the results.

    Batches are unordered, so one failing operation does not stop the rest; its
    message is collected into ``errors`` instead of raising.
    """
    matched = modified = upserted = 0
    errors: List[str] = []

    for index, batch in enumerate(_batched(operations, batch_size), start=1):
        try:
            result = target.bulk_write(list(batch), ordered=False)
            matched += result.matched_count
            modified += result.modified_count
            upserted += result.upserted_count
        except BulkWriteError as exc:
            details = exc.details or {}
            matched += details.get("nMatched", 0)
            modified += details.get("nModified", 0)
            upserted += details.get("nUpserted", 0)
            for write_error in details.get("writeErrors", []):
                errors.append(write_error.get("errmsg", str(write_error)))
        if verbose:
            print(f"  batch {index}: {modified} modified, {matched} matched")

    return {
        "matched": matched,
        "modified": modified,
        "upserted": upserted,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Document sanitisation
# ---------------------------------------------------------------------------


def strip_surrogates(text: str) -> str:
    """Drop lone/unpaired UTF-16 surrogates from a string.

    Such surrogates (e.g. from broken emoji like flag pairs) are valid Python
    ``str`` but cannot be UTF-8 encoded, which crashes serialization on upload.
    Properly-paired emoji survive.
    """
    return text.encode("utf-8", "surrogatepass").decode("utf-8", "ignore")


def clean_document(obj: Any) -> Any:
    """Recursively strip whitespace, drop empty values, and remove lone
    UTF-16 surrogates from dict keys and string values so the document is
    safe to serialize and upload.
    """
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            if k is None:
                continue
            key = strip_surrogates(str(k)).strip()
            if key == "":
                continue
            cleaned_value = clean_document(v)
            if cleaned_value in (None, "", [], {}):
                continue
            cleaned[key] = cleaned_value
        return cleaned
    if isinstance(obj, list):
        cleaned_list = []
        for item in obj:
            cleaned_item = clean_document(item)
            if cleaned_item in (None, "", [], {}):
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list
    if isinstance(obj, str):
        return strip_surrogates(obj).strip()
    return obj


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


def ensure_collection_exists(
    mongodb: MongoTarget,
    collection: str,
    db_name: Optional[str] = None,
    create: bool = True,
) -> bool:
    """Ensure a collection exists, optionally creating it.

    MongoDB creates collections implicitly on first write, so this is only
    needed when you want the collection to exist before any document lands in
    it (or want to check without writing).

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Collection name.
        db_name: Database name; defaults to the URI's default database.
        create: Create the collection when missing. When False, only report.

    Returns:
        True if the collection exists (or was created), False otherwise.
    """
    database = _resolve_database(mongodb, db_name)
    if collection in set(database.list_collection_names()):
        return True
    if not create:
        return False
    database.create_collection(collection)
    return True


def count_documents(
    mongodb: MongoTarget,
    collection: str,
    selectors: Optional[Dict[str, Any]] = None,
    db_name: Optional[str] = None,
) -> int:
    """Return the number of documents matching *selectors* (all documents by default)."""
    return _resolve_collection(mongodb, collection, db_name).count_documents(
        selectors or {}
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def upload_document(
    mongodb: MongoTarget,
    collection: str,
    doc: Dict[str, Any],
    doc_id: Optional[str] = None,
    check_for_existing: Optional[str] = None,
    on_existing: str = "skip",
    db_name: Optional[str] = None,
    clean: bool = False,
) -> Dict[str, Any]:
    """Insert a single document, optionally only when it is not already stored.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Target collection name.
        doc: The document to insert.
        doc_id: Custom ``_id``. When the document has no ``_id`` and none is
            given, a ``<uuid4>_<DDMMYYYY>`` id is generated.
        check_for_existing: Field identifying the document (e.g. ``"quiz_id"``).
            When given, the collection is checked for a document holding the
            same value under that field before inserting. Ignored when *doc*
            does not carry the field.
        on_existing: What to do when a match is found - ``"skip"`` (default)
            leaves the stored document untouched, ``"update"`` overwrites its
            fields with the ones from *doc*, ``"overwrite"`` replaces the stored
            document wholesale so fields absent from *doc* are dropped.
        db_name: Database name; defaults to the URI's default database.
        clean: Run the document through :func:`clean_document` first.

    Returns:
        ``{"id": str | None, "ok": bool, "action": "inserted" | "skipped" |
        "updated" | "overwritten"}``. ``id`` is None for an update matched on a
        field other than ``_id``.
    """
    if on_existing not in ("skip", "update", "overwrite"):
        raise ValueError("on_existing must be one of 'skip', 'update' or 'overwrite'.")

    payload = clean_document(doc) if clean else dict(doc)
    target = _resolve_collection(mongodb, collection, db_name)

    if check_for_existing and check_for_existing in payload:
        selector = {check_for_existing: payload[check_for_existing]}
        if target.count_documents(selector, limit=1) > 0:
            if on_existing == "skip":
                return {
                    "id": str(payload.get("_id")) if "_id" in payload else None,
                    "ok": True,
                    "action": "skipped",
                }
            if on_existing == "overwrite":
                replacement = {k: v for k, v in payload.items() if k != "_id"}
                target.replace_one(selector, replacement)
                return {
                    "id": str(payload["_id"]) if "_id" in payload else None,
                    "ok": True,
                    "action": "overwritten",
                }
            update_data = {k: v for k, v in payload.items() if k != check_for_existing}
            if not update_data:
                raise ValueError(
                    f"Document has no fields to update besides '{check_for_existing}'."
                )
            target.update_one(selector, {"$set": update_data})
            return {
                "id": str(payload["_id"]) if "_id" in payload else None,
                "ok": True,
                "action": "updated",
            }

    if "_id" not in payload:
        payload["_id"] = doc_id or f"{uuid.uuid4()}_{datetime.now():%d%m%Y}"

    result = target.insert_one(payload)
    return {"id": str(result.inserted_id), "ok": True, "action": "inserted"}


def upload_documents(
    mongodb: MongoTarget,
    collection: str,
    docs: Union[Dict, List[Dict]],
    check_for_existing: Optional[str] = None,
    on_existing: str = "skip",
    batch_size: int = 100,
    db_name: Optional[str] = None,
    clean: bool = False,
    ordered: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Insert documents in batches, optionally skipping or refreshing existing ones.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Target collection name.
        docs: A list of documents, a single document, or a dict with a
            ``"results"`` list.
        check_for_existing: Field identifying a document (e.g. ``"quiz_id"``).
            When given, the collection is first queried for documents already
            holding those values; matches are not re-inserted. Documents that
            do not carry the field are always inserted. Without it, every
            document is inserted as-is.
        on_existing: What to do with documents that already exist -
            ``"skip"`` (default) leaves them untouched, ``"update"`` overwrites
            their fields with the incoming values, ``"overwrite"`` replaces each
            stored document wholesale with the incoming one, so fields it holds
            that the incoming document does not are dropped. Only meaningful
            alongside *check_for_existing*.
        batch_size: Documents per ``insert_many`` / ``bulk_write`` call.
            Defaults to 100.
        db_name: Database name; defaults to the URI's default database.
        clean: Run each document through :func:`clean_document` first.
        ordered: Passed to ``insert_many``. False (default) keeps inserting
            after a failing document; True aborts the batch at the first error.
        verbose: Print per-batch progress.

    Returns:
        ``{"inserted": int, "skipped": int, "updated": int, "overwritten": int,
        "matched": int, "ids": [str, ...], "errors": [str, ...]}``. With
        ``ordered=False`` a duplicate-key or invalid document fails only that
        document; the error text is collected instead of raised.

    Note:
        The existence check and the insert are separate operations, so a
        concurrent writer can still create a duplicate in between. A unique
        index on the *check_for_existing* field is what makes that impossible;
        this check keeps a re-run from duplicating its own earlier upload.
    """
    if on_existing not in ("skip", "update", "overwrite"):
        raise ValueError("on_existing must be one of 'skip', 'update' or 'overwrite'.")

    payload = _as_doc_list(docs)
    if not payload:
        raise ValueError("No documents provided for upload.")
    if clean:
        payload = [clean_document(doc) for doc in payload]

    target = _resolve_collection(mongodb, collection, db_name)

    existing_docs: List[Dict[str, Any]] = []
    if check_for_existing:
        payload, existing_docs = _partition_by_existing(
            target, payload, check_for_existing, batch_size
        )
        if verbose and existing_docs:
            verb = {
                "skip": "skipping",
                "update": "updating",
                "overwrite": "overwriting",
            }[on_existing]
            print(
                f"{len(existing_docs)} document(s) already in '{collection}' "
                f"by '{check_for_existing}' - {verb}"
            )

    inserted_ids: List[str] = []
    errors: List[str] = []

    for index, batch in enumerate(_batched(payload, batch_size), start=1):
        try:
            result = target.insert_many(list(batch), ordered=ordered)
            inserted_ids.extend(str(oid) for oid in result.inserted_ids)
        except BulkWriteError as exc:
            details = exc.details or {}
            inserted_ids.extend(str(oid) for oid in details.get("insertedIds", []))
            for write_error in details.get("writeErrors", []):
                errors.append(write_error.get("errmsg", str(write_error)))
        if verbose:
            print(f"  batch {index}: {len(inserted_ids)}/{len(payload)} inserted")

    summary: Dict[str, Any] = {
        "inserted": len(inserted_ids),
        "skipped": 0,
        "updated": 0,
        "overwritten": 0,
        "matched": 0,
        "ids": inserted_ids,
        "errors": errors,
    }

    if existing_docs:
        if on_existing == "skip":
            summary["skipped"] = len(existing_docs)
        else:
            builder = (
                _build_replace_operations
                if on_existing == "overwrite"
                else _build_update_operations
            )
            operations = builder(
                existing_docs, [check_for_existing], upsert=False, collection=collection
            )
            write_result = _run_bulk_update(target, operations, batch_size, verbose)
            key = "overwritten" if on_existing == "overwrite" else "updated"
            summary[key] = write_result["modified"]
            summary["matched"] = write_result["matched"]
            summary["errors"].extend(write_result["errors"])

    if verbose:
        print(
            f"'{collection}': {summary['inserted']} inserted, "
            f"{summary['skipped']} skipped, {summary['updated']} updated, "
            f"{summary['overwritten']} overwritten"
        )

    return summary


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def update_documents(
    mongodb: MongoTarget,
    collection: str,
    docs: Union[Dict, List[Dict]],
    match_on: Union[str, Sequence[str]] = "_id",
    check_for_existing: Optional[str] = None,
    batch_size: int = 100,
    db_name: Optional[str] = None,
    upsert: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Update existing documents, matching each on one or more of its own fields.

    Each document is turned into an ``UpdateOne`` whose filter is built from the
    *match_on* field(s) of that document and whose ``$set`` payload is every
    remaining field. Documents are sent with ``bulk_write`` so a batch is one
    round trip.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Target collection name.
        docs: A list of documents, a single document, or a dict with a
            ``"results"`` list. Every document must carry the key field(s).
        match_on: Field name (or sequence of field names) used to locate the
            existing document. Defaults to ``"_id"``; use e.g. ``"quiz_id"`` or
            ``("quiz_id", "language")`` for natural keys.
        check_for_existing: Same identifying field as in :func:`upload_documents`.
            When given it takes the place of *match_on* and turns on *upsert*,
            so documents that already exist under that key are updated and those
            that do not are created.
        batch_size: Operations per ``bulk_write`` call. Defaults to 100.
        db_name: Database name; defaults to the URI's default database.
        upsert: Insert the document when no match is found. Implied by
            *check_for_existing*.
        verbose: Print per-batch progress.

    Returns:
        ``{"matched": int, "modified": int, "upserted": int, "errors": [str, ...]}``.
        ``matched`` counts documents the filter found, ``modified`` those whose
        stored values actually changed (an update to identical values matches
        without modifying).

    Raises:
        ValueError: When a document is missing a key field, or when ``$set``
            would be empty (document consists only of key fields).
    """
    payload = _as_doc_list(docs)
    if not payload:
        raise ValueError("No documents provided for update.")

    if check_for_existing:
        keys = [check_for_existing]
        upsert = True
    else:
        keys = [match_on] if isinstance(match_on, str) else list(match_on)
    if not keys:
        raise ValueError("match_on must name at least one field.")

    operations = _build_update_operations(payload, keys, upsert, collection)
    target = _resolve_collection(mongodb, collection, db_name)
    result = _run_bulk_update(target, operations, batch_size, verbose)

    if verbose:
        print(
            f"'{collection}': {result['modified']} modified, "
            f"{result['upserted']} inserted"
        )

    return result


def update_document_fields(
    mongodb: MongoTarget,
    collection: str,
    selectors: Dict[str, Any],
    fields: Dict[str, Any],
    db_name: Optional[str] = None,
    many: bool = False,
    upsert: bool = False,
) -> Dict[str, Any]:
    """Set *fields* on the document(s) matching *selectors*.

    The partial-update counterpart to :func:`update_documents`: use it when you
    have a filter and a handful of values rather than whole documents.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Target collection name.
        selectors: Query filter identifying the document(s).
        fields: Field/value pairs applied via ``$set``. May use dotted paths
            (``"metadata.updated_at"``) to reach nested values.
        db_name: Database name; defaults to the URI's default database.
        many: Update every match instead of only the first.
        upsert: Insert a document when nothing matches.

    Returns:
        ``{"matched": int, "modified": int, "upserted_id": str | None}``.
    """
    if not fields:
        raise ValueError("No fields provided for update.")

    target = _resolve_collection(mongodb, collection, db_name)
    update = {"$set": fields}
    result = (
        target.update_many(selectors, update, upsert=upsert)
        if many
        else target.update_one(selectors, update, upsert=upsert)
    )

    return {
        "matched": result.matched_count,
        "modified": result.modified_count,
        "upserted_id": (
            str(result.upserted_id) if result.upserted_id is not None else None
        ),
    }


# ---------------------------------------------------------------------------
# Purge / delete
# ---------------------------------------------------------------------------


def purge_documents(
    mongodb: MongoTarget,
    collections: Union[str, List[str]],
    selectors: Optional[Dict[str, Any]] = None,
    db_name: Optional[str] = None,
    drop: bool = False,
    verbose: bool = True,
) -> Dict[str, int]:
    """Delete documents from one or more collections.

    By default every document is removed and the (now empty) collection is left
    in place. Pass *selectors* to delete a subset, or ``drop=True`` to remove
    the collections themselves along with their indexes.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collections: A collection name or list of names.
        selectors: Filter limiting what is deleted. Defaults to ``{}`` (all).
            Ignored when ``drop=True``.
        db_name: Database name; defaults to the URI's default database.
        drop: Drop each collection instead of emptying it. The reported count
            is the document count taken immediately before the drop.
        verbose: Print a line per collection.

    Returns:
        Mapping of collection name -> number of documents removed. A collection
        that fails to purge is reported as 0 and the error is printed rather
        than raised, so one bad name does not abort the rest.
    """
    if isinstance(collections, str):
        collections = [collections]

    database = _resolve_database(mongodb, db_name)
    purged: Dict[str, int] = {}

    for name in collections:
        try:
            if drop:
                purged[name] = database[name].count_documents({})
                database.drop_collection(name)
            else:
                result = database[name].delete_many(selectors or {})
                purged[name] = result.deleted_count
            if verbose:
                action = "Dropped" if drop else "Purged"
                print(f"{action} '{name}' ({purged[name]} document(s))")
        except Exception as exc:
            purged[name] = 0
            print(f"Failed to purge '{name}': {exc}")

    return purged


def delete_document(
    mongodb: MongoTarget,
    collection: str,
    selectors: Dict[str, Any],
    db_name: Optional[str] = None,
    many: bool = False,
) -> int:
    """Delete the document(s) matching *selectors* and return how many were removed.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Target collection name.
        selectors: Query filter. Must be non-empty - use :func:`purge_documents`
            to clear a whole collection.
        db_name: Database name; defaults to the URI's default database.
        many: Delete every match instead of only the first.
    """
    if not selectors:
        raise ValueError(
            "Empty selectors would delete every document. "
            "Use purge_documents() if that is the intent."
        )

    target = _resolve_collection(mongodb, collection, db_name)
    result = target.delete_many(selectors) if many else target.delete_one(selectors)
    return result.deleted_count


# ---------------------------------------------------------------------------
# Read-back
# ---------------------------------------------------------------------------


def retrieve_documents(
    mongodb: MongoTarget,
    collection: str,
    selectors: Optional[Dict[str, Any]] = None,
    fields: Optional[List[str]] = None,
    sort: Optional[Dict[str, int]] = None,
    limit: int = 100,
    db_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch documents, with ``_id`` values normalised to strings.

    Args:
        mongodb: ``MongoClient`` or ``Database``.
        collection: Collection to query.
        selectors: Query filter. Defaults to ``{}`` (all documents).
        fields: Field names to return; ``None`` returns whole documents.
        sort: ``{field: 1 | -1}`` sort specification.
        limit: Maximum documents to return; 0 means no limit.
        db_name: Database name; defaults to the URI's default database.

    Returns:
        List of document dicts.
    """
    target = _resolve_collection(mongodb, collection, db_name)
    projection = {field: 1 for field in fields} if fields else None

    cursor = target.find(selectors or {}, projection)
    if sort:
        cursor = cursor.sort(list(sort.items()))
    if limit:
        cursor = cursor.limit(limit)

    return _stringify_ids(list(cursor))


def pluck_document_values(
    items: Optional[Sequence[Any]],
    path: str,
    default: Any = None,
    skip_missing: bool = False,
) -> List[Any]:
    """Return *path* from each dict in *items*, like ``.get()`` mapped over the list.

    Pairs with :func:`retrieve_documents` for pulling one field out of a result
    set, and works on any nested list of dicts::

        docs = retrieve_documents(mongodb, "respondents")
        pluck_document_values(docs, "identity.email", skip_missing=True)
        pluck_document_values(docs[0]["quizzes"], "title")

    A dotted path stops at the first list it meets, so ``"quizzes.title"``
    across whole documents yields *default* - pluck the list first, then the
    field within it.

    Args:
        items: List of dicts (``None`` is treated as empty). Entries that are
            not dicts, or that lack the path, yield *default*.
        path: Key name, or a dotted path (``"identity.email"``) for nested dicts.
        default: Value used when the path is absent. A stored ``None`` counts as
            present and is returned as-is.
        skip_missing: Drop absent entries instead of emitting *default*, so the
            result is no longer positionally aligned with *items*.

    Returns:
        List of the retrieved values.
    """
    keys = path.split(".")
    plucked: List[Any] = []

    for item in items or []:
        value: Any = item
        for key in keys:
            value = value[key] if isinstance(value, dict) and key in value else _MISSING
            if value is _MISSING:
                break
        if value is not _MISSING:
            plucked.append(value)
        elif not skip_missing:
            plucked.append(default)

    return plucked


def _walk_field_paths(
    value: Any,
    prefix: str,
    depth: int,
    seen: Dict[str, Dict[str, Any]],
) -> None:
    """Record every dotted path reachable under *value* into *seen*.

    Lists are descended into rather than treated as leaves, so the fields of a
    list of dicts (``quizzes[].title``) are reported as ``quizzes.title``. Each
    entry tracks the value types met at that path and how many documents it
    occurred in.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            entry = seen.setdefault(
                path,
                {"path": path, "depth": depth, "types": set(), "count": 0},
            )
            entry["count"] += 1
            entry["types"].add(type(child).__name__)
            _walk_field_paths(child, path, depth + 1, seen)
    elif isinstance(value, list):
        # The list itself is already recorded by the caller; recurse into its
        # dict entries under the same prefix so nested fields surface.
        for item in value:
            if isinstance(item, (dict, list)):
                _walk_field_paths(item, prefix, depth, seen)


def discover_document_fields(
    items: Optional[Sequence[Any]],
    sample_size: int = 50,
    max_depth: int = 0,
) -> "Any":
    """Map every field path present in *items* into a DataFrame of the schema.

    Walks the documents and reports each dotted path that occurs at least once,
    descending through nested dicts and through lists of dicts. Use it to see
    what :func:`retrieve_documents` can actually project, or to populate a field
    picker::

        docs = retrieve_documents(mongodb, "respondents", limit=0)
        schema = discover_document_fields(docs)
        schema[schema["level_1"].notna()]          # nested paths only
        schema["path"].tolist()                    # every projectable field

    Args:
        items: Documents to inspect (``None`` is treated as empty).
        sample_size: How many documents to walk. Defaults to 50; pass 0 to walk
            every document. Fields appearing only in unsampled documents are
            missed, so raise it when the collection is ragged.
        max_depth: Deepest nesting level to report, counting the top level as 1.
            0 (default) means no limit.

    Returns:
        A ``pandas.DataFrame`` with one row per field path, sorted by path.
        Columns: ``path`` (full dotted name), ``level_0`` .. ``level_n`` (the
        path split into its segments, ``None`` past the path's own depth),
        ``depth``, ``types`` (comma-separated value types seen), ``count``
        (occurrences across the sampled documents), and ``coverage`` (that count
        as a fraction of the documents sampled).

    Raises:
        ValueError: When *sample_size* or *max_depth* is negative.
    """
    if sample_size < 0:
        raise ValueError("sample_size must be >= 0 (0 means every document).")
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0 (0 means no limit).")

    import pandas as pd

    documents = list(items or [])
    if sample_size:
        documents = documents[:sample_size]

    seen: Dict[str, Dict[str, Any]] = {}
    for document in documents:
        if isinstance(document, (dict, list)):
            _walk_field_paths(document, "", 1, seen)

    entries = sorted(seen.values(), key=lambda entry: entry["path"])
    if max_depth:
        entries = [entry for entry in entries if entry["depth"] <= max_depth]

    if not entries:
        return pd.DataFrame(
            columns=["path", "level_0", "depth", "types", "count", "coverage"]
        )

    widest = max(entry["path"].count(".") for entry in entries) + 1
    sampled = len(documents) or 1

    rows = []
    for entry in entries:
        segments = entry["path"].split(".")
        row = {"path": entry["path"]}
        row.update(
            {
                f"level_{i}": segments[i] if i < len(segments) else None
                for i in range(widest)
            }
        )
        row["depth"] = entry["depth"]
        row["types"] = ", ".join(sorted(entry["types"]))
        row["count"] = entry["count"]
        row["coverage"] = round(entry["count"] / sampled, 3)
        rows.append(row)

    return pd.DataFrame(rows)
