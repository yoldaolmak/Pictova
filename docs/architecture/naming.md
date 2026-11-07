# Pictova Identity and Naming

Pictova is an independent application: **Visual Intelligence for Content**.
Its focus is selecting existing images and placing appropriate ones in
WordPress articles, not generating artwork or running an editorial operating
system.

| Element | Canonical form |
| --- | --- |
| Product | Pictova |
| GitHub | [yoldaolmak/Pictova](https://github.com/yoldaolmak/Pictova) |
| CLI | `pictova` |
| Python app | `src/pictova/` |
| Primary engine | `src/pictova/engine/` |
| Primary publishing surface | `pictova attach --engine native` |

Pictova may be used alongside other content tools but has no architectural
dependency on Meridyen, Atlas, Pictovap, or Pictovap Product. Those names do
not identify modules, framework layers or release lines in this repository.

## Naming rules

Public documentation refers to **Pictova**, not legacy implementation
codenames. Preserve existing compatibility paths where required by tested
callers; do not expose them as separate products.

Do not invent internal product brands, planned sublayers, or new service
boundaries without a corresponding implemented user capability.
