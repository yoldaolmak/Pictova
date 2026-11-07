# Image Sources

Pictova's native selector is the supported selection entry point. Source
capabilities differ: a configured provider can return candidates without
proving that they depict the article's named H2/H3 subject.

## Sources

| Source | CLI value | Requirements | Behaviour |
|---|---|---|---|
| Visual Memory | `semantic` | `YO_VISUAL_MEMORY_DB` | Searches indexed local and iCloud candidates. |
| DepositPhotos | `deposit` | `DEPOSIT_API_KEY`, login credentials | Searches and downloads licensed exact matches. |
| Wikimedia Commons | `wikimedia` | Network access | Uses a free fallback only when its exact-match gate passes. |
| Unsplash | `unsplash` | `UNSPLASH_ACCESS_KEY` | Free-source candidate search. |
| Automatic chain | `auto` | One or more configured sources | Attempts heading-specific exact candidates in source order. |

`vil` and `local` remain compatibility values for existing indexed local
assets. New integrations should enter through the native provider/selector
boundary.

## Exact-match rule

For a numbered destination or named-product heading, Pictova requires the
specific anchor in the candidate evidence. A generic waterfall cannot satisfy
“Kapuzbaşı Şelaleleri”; a beach portrait cannot satisfy an application heading.
If a source cannot provide an exact candidate, that slot stays empty and the
receipt reports why.

The native heading-aware `auto` / `semantic` routes enforce section identity;
DepositPhotos checks the provider title before a licensed download. Cached or
resumed licensed images are capped at 64 MiB, and nonnumeric asset IDs are
rejected before any filesystem or licensing operation. Explicit
`local`, `vil`, and `unsplash` modes are not interchangeable with that gate:
a caller-provided path or free-provider search ranking is not independent
identity evidence. Use a reviewed plan for direct source modes.

Selection hints such as the article title or heading never become visual facts
in image metadata.

## Choosing a source

```bash
# Local index only
pictova plan --site yoldaolmak --post 265713 --source semantic

# Licensed exact candidates only
pictova plan --site yoldaolmak --post 265713 --source deposit

# Let the native selector use its source chain
pictova plan --site yoldaolmak --post 265713 --source auto
```

`plan` previews candidates. A subsequent `attach` runs the same selection
contract before any licensed download or WordPress write.
