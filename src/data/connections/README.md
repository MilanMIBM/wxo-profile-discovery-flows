# Connections

Connection specs are shareable; **credentials are never in these files**. Import the spec,
then set credentials via the CLI (or, for `member` connections, via the chat prompt).

Connections must exist **before** importing any tool that binds to them (`-a <app_id>`) --
a tool import fails if the connection is missing or its kind doesn't match the tool's
`expected_credentials`.

## `mongodb-conn-string`

`key_value` connection read by the `upload_enriched_profile` tool
(`../tools/upload-enriched-profile/`).

```bash
orchestrate connections import -f src/helpers/connections/mongodb-conn-string.yaml

orchestrate connections set-credentials -a mongodb-conn-string --env draft \
  -e "MONGODB_CONN_STRING=mongodb://<user>:<password>@<host>:<port>/ibmclouddb?authSource=admin&tls=true&replicaSet=replset" \
  -e "MONGODB_CA_CERT_BASE64=$(base64 -i "$IBMCLOUD_DB_CERT_PATH" | tr -d '\n')"
```

| Key | Required | Read by the tool for |
| --- | --- | --- |
| `MONGODB_CONN_STRING` | yes | The full MongoDB connection URL. `MONGODB_ENDPOINT` is accepted as an alias. |
| `MONGODB_CA_CERT_BASE64` | for IBM Cloud Databases | The CA certificate, base64-encoded. The tool sandbox has no cert file on disk, so the tool decodes this to a temp file and passes it as `tlsCAFile`. Omit only if the deployment's TLS chain is already trusted. |

`server_url` in the spec is a placeholder: `key_value` connections expose their pairs to
the tool rather than a URL, and the real endpoint travels in `MONGODB_CONN_STRING`. The
`live` block is ignored in Developer Edition.

Verify with `orchestrate connections list`.

## `postgres-conn-string`

`key_value` connection read by the `retrieve_database_tables` tool
(`../tools/retrieve-database-tables/`), holding `POSTGRES_CONN_STRING_PUBLIC` and/or
`POSTGRES_CONN_STRING_PRIVATE`. No spec file is checked in yet.
