### Fixed

- **Ingested books no longer list their author as "Surname, Given".** Many
  EPUBs, especially Czech and Slovak releases, store the author's sort form
  as the display name too (`Lasica, Milan`). Ingest now restores the display
  form (`Milan Lasica`) when the name is unambiguously a sort form — one comma,
  the file's declared sort equal to the name or absent, and no suffix such as
  "Jr." — and keeps the original as the author's sort value. Contributed by
  @misko903.
- **Authors added by the automatic metadata fetch sort by surname.** A new
  author created by the fetch used to get its full name as its sort value, so
  "Milan Lasica" sorted under M. It now gets the same sort a manual edit would
  give it ("Lasica, Milan").
