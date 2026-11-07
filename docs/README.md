# Pictova Documentation

**Pictova** — Visual Intelligence for Content

Pictova is an independent image-selection and WordPress placement application. It searches configured local and external sources, but only a candidate supporting its intended heading should be published. The native CLI is the primary surface; a token-authenticated local HTTP service is optional.

---

## Contents

### Concepts
Understand the system before running it.

- [Overview](concepts/overview.md) — What Pictova is and why it exists
- [Visual Memory](concepts/visual-memory.md) — The local image index and Mac Photos integration
- [Semantic Selection](concepts/semantic-selection.md) — How images are matched to content
- [The Pipeline](concepts/pipeline.md) — review → plan → process → attach
- [Image Sources](concepts/sources.md) — All supported providers and local sources

### Guides
Task-oriented walkthroughs.

- [Studio](guides/studio.md) — URL, preview, reject, approve and native WordPress apply
- [Quickstart](guides/quickstart.md) — Review, plan and safely publish
- [Installation](guides/installation.md) — Full setup with all components
- [Mac Photos Setup](guides/mac-photos-setup.md) — Index and enrich your Photos library
- [WordPress Setup](guides/wordpress-setup.md) — Credentials and site profiles
- [Adding Image Sources](guides/adding-sources.md) — Configure Unsplash, DepositPhotos, local paths

### Reference
Complete specification for all interfaces.

- [CLI Reference](reference/cli.md) — All `pictova` commands and flags
- [HTTP API Reference](reference/http-api.md) — All endpoints, payloads, and responses
- [Configuration](reference/configuration.md) — Environment variables and config file
- [Site Profiles](reference/profiles.md) — Per-site rules and customization

### Architecture
How it is built and why.

- [System Overview](architecture/overview.md) — Layers, modules, data flow
- [Native vs Legacy Engine](architecture/native-vs-legacy.md) — Supported native path and compatibility limits
- [Engine Modules](architecture/engine-modules.md) — selector, processor, publisher, quality, metadata
- [Brand & Naming](architecture/naming.md) — Independent product and package identity

### Ops
Operating the local application and controlled WordPress publishing.

- [Runbook](ops/runbook.md) — Day-to-day operation commands
- [Indexing](ops/indexing.md) — Visual memory index maintenance
- [Monitoring](ops/monitoring.md) — Health checks and observability

---

- [Changelog](../CHANGELOG.md)
- [Contributing](../CONTRIBUTING.md)
