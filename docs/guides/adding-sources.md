# Adding Image Sources

Source integrations belong in `src/pictova/providers/` and are called by the
native selector. Do not add a standalone script that downloads media or writes
to WordPress outside the attach pipeline.

## Available sources

| Source | CLI value | Configuration |
|---|---|---|
| Visual Memory | `semantic` | `YO_VISUAL_MEMORY_DB` |
| DepositPhotos | `deposit` | `DEPOSIT_API_KEY`, `DEPOSIT_LOGIN_USER`, `DEPOSIT_LOGIN_PASSWORD` |
| Wikimedia Commons | `wikimedia` | None |
| Unsplash | `unsplash` | `UNSPLASH_ACCESS_KEY` |

## Provider contract

A provider must:

1. return source evidence needed by the selector to test the heading anchor;
2. keep discovery separate from a paid or licensed download;
3. cache safe discovery/download state locally when retries are possible;
4. fail closed on an ambiguous candidate; and
5. return a useful error to the structured Pictova receipt.

Add focused tests for both a valid exact match and a rejected generic match.
The selector owns cross-provider fallback and must never turn a failed exact
match into an unrelated image.
