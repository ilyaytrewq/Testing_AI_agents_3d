---
title: "Consolidate project documentation"
description: "Keep operational instructions in the README and remove the redundant Python version file."
id: 16
status: "Done"
labels: []
weight: 1
references: {}
---

# Consolidate project documentation

Remove `docs/` and move the setup, deployment and recovery guidance into the root README. Preserve the local issue history in `.github/issues`. Remove the duplicate Python version file without changing the interpreter selected by the project or container. Verify the docs gate and rebuild from the resulting Docker context.
