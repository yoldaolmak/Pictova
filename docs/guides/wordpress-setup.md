# WordPress setup

Create a revocable Application Password under **Users → Profile →
Application Passwords**. Configure the editorial account in `.env`:

```bash
WP_URL=https://your-wordpress-host.example
WP_USER=your-user
WP_APP_PASSWORD=your-app-password
```

Use the actual authorized endpoint, not the example host. The account needs
access to the target post and media upload/update permissions.

Run `pictova health` to inspect readiness without uploading media.
`health --verify-upload` performs an explicit test upload and cleanup.
Use Studio for review before insertion.

Pictova checks the post before committing and verifies it afterward.
WordPress REST does not provide atomic compare-and-swap; concurrent edits
cannot be ruled out. Inspect uncertain results before retrying.

[Site settings](../reference/profiles.md) · [Security](../../SECURITY.md)
