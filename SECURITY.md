# Security Policy

Pictova operates on local photo indexes, private article content, external
image services and WordPress credentials. A successful offline test run is
not a security certification or a real-world visual-accuracy evaluation.

## Operational boundaries

- Run the HTTP service only on loopback with a private
  `PICTOVA_HTTP_TOKEN`. Do not publish its port to a LAN or public network.
- Store WordPress application passwords and provider API keys in the local
  environment, never in the repository, CLI arguments, issue reports or test
  fixtures. Revoke exposed credentials.
- Treat model prompts and responses as potentially private photo/article
  data. The local OpenAI-compatible path limits model replies and does not
  echo malformed model output or HTTP error bodies in operator errors.
- `review`, `plan` and `process` do not change WordPress content.
  `process` can still use provider APIs or download licensed images.
  `attach`, and explicit `guard` mutation modes, write to WordPress.
- Do not lower exact-match requirements or silently substitute a generic
  image when a named H2/H3 candidate is not proven.
- A configured external image provider is not a trusted URL sandbox.
  In particular, source-controlled download URLs and redirects need
  continued SSRF/redirect review before deployment in untrusted networks.

## Offline tests versus live assurance

The synthetic OpenAI-compatible completion tests send **no external
requests** and require **no model API key**. Their descriptions are authored
fixtures, not output inferred from image pixels. They verify parsing, privacy
of error messages, processing of metadata and relevant quality rejection.
They cannot validate a true image's place identity.

Before live publication, check the actual image, licensing rights, selected
section, media ownership and the preview plan. Never use a live paid provider
or WordPress write as an unattended CI test.

## Reporting vulnerabilities

Use GitHub's private vulnerability-reporting mechanism where available or
contact repository maintainers via an agreed private channel. Do not post
private photos, passwords, signed download URLs or working exploit details
in public issues. Include the affected revision, minimal synthetic steps and
scope of the potential impact.
