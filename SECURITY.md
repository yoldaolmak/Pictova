# Security

Pictova can read private photos and WordPress content, use paid providers, and modify Gutenberg posts. Treat those actions as separate trust boundaries.

## Deployment

- Run Studio and HTTP only on loopback. Do not expose the port to a network.
- Keep WordPress passwords, API keys and signed provider URLs out of Git, logs and issue reports.
- Browser requests require the local Bearer token. Studio write requests also enforce same-origin and Host checks.
- The static Studio shell is public; image previews, post data and job results require authentication.
- Studio accepts only configured WordPress HTTPS hosts, not arbitrary URLs. Candidate IDs, paths and heading assignments stay server-side.
- Plans expire after 20 minutes, are single-use, and check local asset and post state before an approved native attach.
- Licensed images may incur charges before the quality gate. Studio requires separate paid consent.

`review` and `plan` do not write to WordPress. `process` may download/license. `attach`, explicit `guard` mutations, and `health --verify-upload` can write.

## Known limits

- Local or provider metadata is not ground truth for image identity.
- Signed CDN URLs and redirects still need a separate SSRF/redirect-policy review.
- Studio jobs are process-local; a restart can lose their status. Check the WordPress post and operation receipt before retrying.
- CI uses synthetic images, mocked WordPress and model responses; it does not verify a real publish or real-world visual recognition.

## Reporting

Use a private vulnerability-reporting channel. Include a minimal synthetic reproduction and affected revision. Do not publish secrets, private photos, signed download links or exploit details in public issues.
