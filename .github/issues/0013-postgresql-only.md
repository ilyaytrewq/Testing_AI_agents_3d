---
title: "Use PostgreSQL as the only database"
description: "Replace file-backed storage with persistent local or managed PostgreSQL."
id: 13
status: "Done"
labels: []
weight: 2
references: {}
---

# Use PostgreSQL as the only database

## Acceptance

Require a PostgreSQL DSN instead of falling back to a local file. Start PostgreSQL automatically with the local Compose stack and keep its data on a named volume. Document how to use managed PostgreSQL instead. Do not delete or copy any prior data.

## Verification

Run `make check` and the browser suite against PostgreSQL. Check the two Compose modes, persistence after container recreation, and absence of obsolete runtime dependencies.
