---
title: "Move database deployment out of application YAML"
description: "Keep local persistence in the Compose volume and select external PostgreSQL with a secret DSN."
id: 12
status: "Done"
labels: []
weight: 1
references: {}
---

# Move database deployment out of application YAML

## Acceptance

Use the existing named volume for SQLite without application YAML storage settings. Select PostgreSQL when `DATABASE_URL` is configured. Reject missing SQLite paths and conflicting backend settings rather than creating an unexpected database. Keep existing data and document the deployment options.

## Verification

Run the storage selection tests and verify both database modes with Docker Compose.
