---
title: "Support OpenAI-compatible text generation"
description: "Select the native Gemini or OpenAI-compatible chat adapter in Compose and Helm."
id: 17
status: "In progress"
labels: []
weight: 2
references: {}
---

# Support OpenAI-compatible text generation

Keep native Gemini as the default. Add an asynchronous Chat Completions client with a configurable base URL, model, and provider-specific secret. Exercise the SDK over a stub HTTP transport, verify provider routing through the API and render the Helm chart in both modes.
