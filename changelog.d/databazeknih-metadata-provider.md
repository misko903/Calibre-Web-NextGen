### Added

- **Czech and Slovak books can pull metadata from Databáze knih
  (databazeknih.cz).** The new provider fills in title, authors, cover,
  description, genres, series, rating, ISBN and publisher, and links the book
  back to its databazeknih.cz page. It is a best-effort scraper, so it starts
  switched off: turn it on in the metadata provider settings.
- **Automatic metadata fetch retries Databáze knih by ISBN.** When a book's
  title does not find it — for example a Czech title stored without
  diacritics — and the book has an ISBN, the fetch searches again by that
  ISBN. The result must still match the book before anything is applied. In
  the metadata search box you can also type `isbn:<number>` or a bare ISBN.
