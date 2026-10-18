### Added

- **Czech and Slovak books can pull metadata from Databáze knih.** A new
  `Databáze knih` (databazeknih.cz) source appears in metadata search and in
  the provider list. It finds editions by ISBN or title, prefers the Slovak or
  Czech edition that matches the query, and fills in the full description,
  series and index, year, publisher, language, genres and tags, rating, cover,
  ISBN, original title, translator and page count. Contributed by @misko903.
- **Automatic metadata fetch retries Databáze knih by ISBN.** When a book's
  title does not find it — for example a Czech title stored without
  diacritics — and the book has an ISBN, the fetch searches again by that
  ISBN. The result must still match the book before anything is applied.
