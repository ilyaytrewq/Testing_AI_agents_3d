---
title: "Package and verify the project"
description: "Document setup and prove the application and tests run from a clean checkout."
id: 10
status: "Done"
labels: []
weight: 2
references: {}
---

# Package and verify the project

## Acceptance

Document setup and prove the application and tests run from a clean checkout.

## Verification

The clean-checkout run passed 57 tests with PostgreSQL and one Chromium end-to-end test. The wheel built successfully. A non-root Compose container retained both the session and a saved chat turn after recreation. The independent delivery review approved `62cbef3`; GitHub Actions was linted locally, not run on GitHub. Gemini was checked against a mocked HTTP transport, not the live service.
