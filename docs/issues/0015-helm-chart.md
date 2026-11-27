---
title: "Deploy the chat with Helm"
description: "Deploy the chat in Kubernetes against a pre-existing PostgreSQL database."
id: 15
status: "In progress"
labels: []
weight: 2
references: {}
---

# Deploy the chat with Helm

Install a single migration-safe Deployment and a ClusterIP Service. Reference an existing Secret, not values with credentials. Provide a documented registry, namespace, public origin, and external PostgreSQL setup. Verify rendering, probes, and installation into an isolated Kubernetes cluster.
