# Font asset provenance (Roadmap PR18D)

These two files are **Noto Sans Thai**, the same typeface already used by
`frontend/public/fonts/` for Browser Print (Roadmap PR18C) — no font-family
change.

- `NotoSansThai-Regular.ttf` (weight 400)
- `NotoSansThai-Bold.ttf` (weight 700)

## Why this backend copy exists separately from `frontend/public/fonts/`

`frontend/public/fonts/` ships four `.woff2` files split by `unicode-range`
(a Thai-glyph file and a Latin-glyph file per weight) — the format Google
Fonts' CSS2 API serves and the correct choice for a browser, which resolves
`unicode-range` natively.

WeasyPrint 69.0 (the backend PDF renderer) does not reliably resolve that
same two-file/`unicode-range` split: once the rendered text contains enough
distinct Thai glyphs, it silently subsets/merges the two files incorrectly
and draws the wrong glyph for some Latin characters. This was reproduced and
confirmed with two independent PDF text-extraction libraries (pdfplumber,
PyMuPDF) and by visually inspecting a rasterized page. A single, non-split
font file per weight — covering both Thai and Latin glyphs together — does
not trigger this bug.

Both files here are that single-file-per-weight form. This is an
implementation-correctness fix for the backend PDF renderer, not a font,
branding, or typography decision:

- Font family is unchanged (Noto Sans Thai, both places).
- Browser Print (`frontend/public/fonts/`, `frontend/src/styles/print.css`)
  is untouched and continues to use the split `.woff2` files exactly as
  Roadmap PR18C shipped them.
- Only the backend PDF renderer uses these merged static TTF files, because
  only the backend PDF renderer (WeasyPrint) is affected by this bug.

## Source

Upstream: [github.com/notofonts/thai](https://github.com/notofonts/thai)
(the canonical upstream Noto Sans Thai project; Google Fonts serves a build
of this same source).

- Release: `NotoSansThai-v2.002`
- Release asset: `NotoSansThai-v2.002.zip`
- File used from the release archive: `NotoSansThai/full/ttf/NotoSansThai-Regular.ttf`
  and `NotoSansThai/full/ttf/NotoSansThai-Bold.ttf` — the release's "full"
  static TTF build, which merges in the Latin/Latin-1 glyph set (the
  "unhinted"/"hinted" static builds in the same release contain Thai-script
  glyphs only, no Latin letters or digits, and are not usable alone for
  report content that mixes Thai and Latin/numeric text).
- Upstream source commit referenced by this release (per Google Fonts'
  `METADATA.pb` for this family): `f8f3f024703f9d939d02f4e2fe16f1d5a39ca963`.

## License

SIL Open Font License, Version 1.1 (OFL-1.1) — see `OFL.txt` in this
directory (the exact license file from the same release archive). Same
license already accepted for the `frontend/public/fonts/` copy. Royalty-free;
permits bundling and embedding, including in a generated PDF.
