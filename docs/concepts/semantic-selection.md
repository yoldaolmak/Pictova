# Semantic Selection

The unit of selection is the article **section**, not an image count or a
general travel destination. Pictova should leave a heading empty before
attaching an image that could belong to a different place.

## Selection contract

1. Read the WordPress title/slug and H2/H3 headings.
2. Derive the subject of each eligible heading. For a numbered route heading
   such as “Bodrum'dan Kos'a Kaçış”, the subject is **Kos**, not Bodrum.
3. Search the local index first, then configured external sources if enabled.
4. Check candidate identity against the heading's own specific words. A
   general article title cannot substitute for the heading's place.
5. Keep the same identity requirement when an optional model proposes a broader
   search query. The model proposes searches; it never approves an image.

A candidate needing multiple meaningful topic anchors cannot pass with just
one incidental word. A single named place can pass on an exact or normalized
name match. Broad category tags or a nearby country are insufficient.

## Language support

Turkish diacritics and case are normalized for comparison. Limited, general
Turkish/English editorial nouns can be matched (for instance, *valiz* /
*suitcase* or *vize* / *visa*), and a pluralized place name can match its
obvious singular spelling (*Aladağlar* / *Aladag*).

Different proper names that are not simple spelling variants require
independent identity evidence. This version does **not** infer that two
unrelated strings identify the same landmark, nor does it assume an unknown
place belongs to a particular country. A missing bilingual alias remains an
unmatched section, not an invitation to use an approximate image.

## Scope and source quality

The native `auto` and heading-aware `semantic` routes apply the section
contract. Explicit direct-file/provider modes have separate limits; a
human-supplied file path or a free-provider result is not automatically
validated against every heading. Licensed DepositPhotos candidates must also
pass a provider-title match before a chargeable download.

```bash
pictova plan --site yoldaolmak --post 265713 --count 4 --source auto
```

Inspect `files`, `heading_assignments` and `warnings` before publishing.
Tests cover normal matches and known rejection cases; they do not constitute
human evaluation of the visual content of every photograph.
