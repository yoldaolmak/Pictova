# Pictova Studio

Pictova Studio is a single-screen, local visual-review interface beside the
existing CLI. It uses the same native selection, processing, quality and
WordPress publishing engine; it does not introduce a second publishing path.

## Start

After configuring WordPress credentials and intended image sources:

    pictova studio

Pictova opens the local browser. The access secret is passed in the browser
URL fragment, not an HTTP query or request. The page immediately removes
that fragment and retains the token only in memory. The service binds to
loopback only.

For an existing 'pictova serve' session, open
http://127.0.0.1:8040/studio and type the already configured
PICTOVA_HTTP_TOKEN in the local login field.

For headless operation, set PICTOVA_HTTP_TOKEN in the environment and run:

    pictova studio --no-open

Do not expose the Studio port to a LAN or the public Internet.

## Editorial workflow

1. Paste the public HTTPS permalink of a post on a site already configured
   in Pictova. The server resolves its ID through that configured site's
   authenticated WordPress REST API; it never fetches arbitrary URLs.
2. Choose an upper bound of 1–8 images and create a plan. Discovery and
   heading matching run without WordPress writes or paid stock downloads.
3. Review each actual preview and its proposed H2/H3 placement. Uncheck
   wrong or unwanted images. An unmatched section is left empty.
4. Check publishing consent. If DepositPhotos candidates remain, acknowledge
   the possible licensing charge separately.
5. Apply. Only the approved candidate identities enter the existing native
   image processing, metadata quality and WordPress publishing stages.
   The page shows the resulting job status and inserted-media outcome.

The browser cannot supply arbitrary file paths or heading assignments.
The plan lives on the local server, expires after 20 minutes, and can be
applied only once. The application compares the WordPress post and local
source-photo state against the approved plan before publishing; WordPress
also checks for concurrent edits when committing content.

## Image source limits

Local images receive authenticated, locally rendered previews.
DepositPhotos previews use the provider's HTTPS preview URL; the exact
approved licensed asset ID is downloaded only after separate paid consent.
This may incur a licensing cost even if the later quality gate rejects
the image. The original candidate already passed the native provider
title/heading match.

An iCloud-only candidate without a safe preview is shown as unavailable:
Studio will not publish a visual that the operator could not inspect.
Existing CLI support for iCloud and direct-source modes remains unchanged.
Studio uses the native automatic selector; it does not offer legacy writes.

The interface does not prove whether the image really depicts a place.
Human visual review and the original quality gate remain necessary.

## Verification

    python3.10 -m pytest tests/unit/test_studio.py -q
    python3.10 -m pytest -q

Tests use offline fixtures and mocked services, without live publication
or licensed downloads.

See [HTTP API](../reference/http-api.md),
[Semantic Selection](../concepts/semantic-selection.md) and
[Security](../../SECURITY.md).
