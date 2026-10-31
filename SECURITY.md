# Security policy

## Supported versions

vmigrate is pre-1.0. Security fixes go into the latest release on `main` only.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub:
[Report a vulnerability](https://github.com/vanalex/vmigrate/security/advisories/new).

Include what you found, how to reproduce it, and the impact you expect. You should get a reply
within a week. Once a fix is released, the advisory is published with credit to you, unless you
prefer not to be named.

## Handling data and credentials safely

vmigrate moves your data between databases, so a few things are worth knowing:

- **Credentials:** keep API keys out of `migrate.yaml` and use environment variables instead
  (`api_key: ${QDRANT_API_KEY:-}`). The run fingerprint stored in the checkpoint database
  excludes credentials.
- **Dead-letter files** (`.vmigrate/deadletter/`) contain complete records, including payloads
  and vectors, for every record that failed. Treat them as sensitive as the source data and
  delete them when you're done.
- **Checkpoint database** (`.vmigrate/state.db`) stores read cursors (point IDs), not payloads.
- **Transform hooks** (`transforms: ["module:function"]`) import and run Python code named in
  the config. Only run configs you trust.
