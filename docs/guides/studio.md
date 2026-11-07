# Studio

Studio is Pictova's local, single-screen review interface. It uses the same native publisher as the CLI.

```bash
pictova studio
```

The browser opens with a temporary token. The server binds to loopback only. To open it manually, set `PICTOVA_HTTP_TOKEN`, run `pictova studio --no-open`, then enter the token at `http://127.0.0.1:8040/studio`.

## Workflow

1. Paste the HTTPS permalink of a post on a configured WordPress site.
2. Create a plan (1–8 candidates). No paid license or WordPress write occurs.
3. Inspect thumbnails and proposed H2/H3 placements. Uncheck wrong candidates.
4. Approve publication. Licensed stock requires a separate cost acknowledgment.
5. Apply. Studio publishes **only selected candidate identities** through the native quality gate.

Plans expire after 20 minutes and can be applied only once. A changed post or local photo blocks publication. No candidate, no upload.

## Limits

- Native `auto` selection only; existing CLI source modes remain available.
- Local images have authenticated thumbnails. DepositPhotos previews come from its remote HTTPS service.
- iCloud-only candidates without a safe preview cannot be approved in Studio.
- A paid license may be consumed before an image is rejected by the later quality gate.
- Plan/review and synthetic tests do not prove real-world visual accuracy. CI does not publish to a live site.

See [CLI](../reference/cli.md), [Security](../../SECURITY.md), and [HTTP API](../reference/http-api.md).
