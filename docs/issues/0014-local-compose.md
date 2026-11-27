---
title: "Consolidate local Docker Compose"
description: "Use one explicitly selected Compose file for the local app and PostgreSQL."
id: 14
status: "Done"
labels: []
weight: 1
references: {}
---

# Consolidate local Docker Compose

Keep only `compose.local.yaml`. Preserve the local PostgreSQL service, project-derived volume name, health checks and loopback bind. Verify the new file can use a volume initialized by the prior configuration.
