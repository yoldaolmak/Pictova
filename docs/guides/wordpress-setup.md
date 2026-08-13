# WordPress Setup

Pictova uses WordPress Application Passwords. They can be revoked separately
from the user’s normal login password.

1. Open **Users → Profile → Application Passwords** in WordPress.
2. Create an application password named `Pictova`.
3. Copy the generated value into `.env`.

## Supported sites

```bash
# yoldaolmak.com
WP_URL=https://yoldaolmak.com
WP_USER=your-user
WP_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx

# gezievreni.com
GEZIEVRENI_URL=https://gezievreni.com
GEZIEVRENI_USER=your-user
GEZIEVRENI_PASS=xxxx xxxx xxxx xxxx xxxx xxxx

# gezgindunyasi.com
GEZGINDUNYASI_URL=https://gezgindunyasi.com
GEZGINDUNYASI_USER=your-user
GEZGINDUNYASI_PASS=xxxx xxxx xxxx xxxx xxxx xxxx
```

Run `pictova health` after configuration. It reports missing configuration
without returning secret values. `--site auto` resolves a post only when it is
found on exactly one configured site; use an explicit site if IDs overlap.

The account needs permission to upload media and update posts. Pictova verifies
the post content again before committing an anchored media block, so an editor’s
concurrent change is not overwritten.
