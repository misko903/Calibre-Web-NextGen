# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Databáze knih (databazeknih.cz) metadata scraper — Czech/Slovak catalog.

The site has no public API. Parsing prefers the schema.org microdata
(``itemprop``) and OpenGraph tags the book pages carry and falls back to the
site's own CSS classes, so a cosmetic redesign degrades fields instead of
emptying the result. Publisher/ISBN live in a block the book page loads
lazily (``/book-detail-more-info/<id>``); it is fetched only when the page
itself lacks them, and its failure is never fatal.

Failure contract matches the other keyless scrapers (#303): unreachable
network and parse failures return no results, an HTTP status refusal is
raised so the search layer can name it instead of showing "no results".
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup, Tag

from cps import constants, logger
from cps.isoLanguages import get_language_name
from cps.services.Metadata import Metadata, MetaRecord, MetaSourceInfo

log = logger.create()

# Book slugs always end with the numeric book id: "saturnin-15".
BOOK_HREF_RE = re.compile(r"(?:^|/)knihy/([\w-]+-(\d+))(?:[/?#]|$)")
YEAR_RE = re.compile(r"\b(1[4-9]\d\d|20\d\d)\b")
SERIES_POSITION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*\.?\s*díl", re.IGNORECASE)

LANGUAGE_MAP = {
    "česky": "ces", "český": "ces", "čeština": "ces",
    "slovensky": "slk", "slovenský": "slk", "slovenština": "slk",
    "anglicky": "eng", "anglický": "eng", "angličtina": "eng",
    "německy": "deu", "německý": "deu", "němčina": "deu",
    "polsky": "pol", "polský": "pol", "polština": "pol",
}

# Trailing "show more/less" toggles in descriptions
DESCRIPTION_NOISE = ("... celý text", "…celý text", "celý text", "méně textu")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.replace("​", "").replace("﻿", "")
    return " ".join(value.split()) or None


def _itemprop(root, prop: str) -> Optional[str]:
    node = root.select_one(f'[itemprop="{prop}"]')
    if node is None:
        return None
    if node.name == "meta":
        return _clean(str(node.get("content") or ""))
    return _clean(node.get_text(" "))


def _valid_isbn(candidate: str) -> Optional[str]:
    digits = candidate.replace("-", "").replace(" ", "").strip()
    if len(digits) == 13 and digits.isdigit():
        return digits
    if len(digits) == 10 and re.fullmatch(r"\d{9}[\dXx]", digits):
        return digits.upper()
    return None


def _is_placeholder_cover(url: str) -> bool:
    lowered = url.lower()
    return "nocover" in lowered or "no_image" in lowered or "noimage" in lowered


class Databazeknih(Metadata):
    __name__ = "Databáze knih"
    __id__ = "databazeknih"
    DESCRIPTION = __name__
    META_URL = "https://www.databazeknih.cz/"
    SEARCH_URL = "https://www.databazeknih.cz/search?q={}"
    BOOK_URL = "https://www.databazeknih.cz/knihy/{}"
    MORE_INFO_URL = "https://www.databazeknih.cz/book-detail-more-info/{}"
    TIMEOUT = (4, 10)
    MAX_RESULTS = 5
    HEADERS = {
        "User-Agent": constants.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "cs-CZ,cs;q=0.9,sk;q=0.8,en;q=0.7",
    }

    def search(self, query: str, generic_cover: str = "", locale: str = "en") -> List[MetaRecord]:
        if not self.active or not isinstance(query, str) or not query.strip():
            return []
        tokens = " ".join(self.get_title_tokens(query, strip_joiners=False)) or query.strip()
        session = requests.Session()
        session.headers.update(self.HEADERS)
        try:
            response = session.get(self.SEARCH_URL.format(quote_plus(tokens)), timeout=self.TIMEOUT)
            response.raise_for_status()
            html = response.text
        except requests.HTTPError as exc:
            # Refused, not empty — see the module docstring (#303).
            log.warning("databazeknih.cz search refused: %s", exc)
            raise
        except (requests.RequestException, ValueError, TypeError) as exc:
            log.warning("databazeknih.cz search failed: %s", exc)
            return []

        # An unambiguous query (an ISBN, say) lands straight on the book page.
        slug = self._book_page_slug(html)
        if slug:
            record = self._parse_book(html, slug, generic_cover, locale)
            if record:
                self._fill_more_info(session, record, locale)
            return [record] if record else []

        records = []
        refusal = None
        for slug in self._parse_search(html)[:self.MAX_RESULTS]:
            try:
                response = session.get(self.BOOK_URL.format(slug), timeout=self.TIMEOUT)
                response.raise_for_status()
                record = self._parse_book(response.text, slug, generic_cover, locale)
                if record:
                    self._fill_more_info(session, record, locale)
                    records.append(record)
            except requests.HTTPError as exc:
                log.warning("databazeknih.cz book fetch refused: %s", exc)
                refusal = exc
            except (requests.RequestException, ValueError, TypeError) as exc:
                log.warning("databazeknih.cz book fetch failed: %s", exc)
        # Search matched but every page was refused: not an empty result.
        if refusal is not None and not records:
            raise refusal
        return records

    @classmethod
    def _parse_search(cls, html: object) -> List[str]:
        """Book slugs from a search results page, in rank order."""
        if not isinstance(html, str) or not html.strip():
            return []
        soup = BeautifulSoup(html, "html.parser")
        found = []
        for anchor in soup.select("a[href]"):
            match = BOOK_HREF_RE.search(str(anchor.get("href") or ""))
            # Cover-image links share the href but carry no text.
            if match and _clean(anchor.get_text(" ")) and match.group(1) not in found:
                found.append(match.group(1))
        return found

    @classmethod
    def _book_page_slug(cls, html: object) -> Optional[str]:
        """The slug if this is a book detail page, else None."""
        if not isinstance(html, str) or not html.strip():
            return None
        soup = BeautifulSoup(html, "html.parser")
        if soup.select_one('h1[itemprop="name"]') is None:
            return None
        for selector, attr in (('link[rel="canonical"]', "href"), ('meta[property="og:url"]', "content")):
            node = soup.select_one(selector)
            if node:
                match = BOOK_HREF_RE.search(str(node.get(attr) or ""))
                if match:
                    return match.group(1)
        return None

    @classmethod
    def _parse_book(cls, html: object, slug: str, generic_cover: str = "",
                    locale: str = "en") -> Optional[MetaRecord]:
        if not isinstance(html, str) or not html.strip():
            return None
        soup = BeautifulSoup(html, "html.parser")
        title = cls._title(soup)
        if not title:
            return None
        record = MetaRecord(
            id=slug,
            title=title,
            authors=cls._authors(soup),
            url=cls.BOOK_URL.format(slug),
            source=MetaSourceInfo(cls.__id__, cls.DESCRIPTION, cls.META_URL),
            cover=cls._cover(soup) or generic_cover,
        )
        record.description = cls._description(soup)
        record.publisher = _itemprop(soup, "publisher")
        record.publishedDate = cls._year(soup)
        record.identifiers = {cls.__id__: slug}
        isbn = cls._isbn(soup)
        if isbn:
            record.identifiers["isbn"] = isbn
        record.tags = cls._tags(soup)
        record.rating = cls._rating(soup)
        series, index = cls._series(soup)
        if series:
            record.series = series
            record.series_index = index if index is not None else 0
        record.languages = [get_language_name(locale, cls._language(soup))]
        return record

    @classmethod
    def _fill_more_info(cls, session: requests.Session, record: MetaRecord, locale: str) -> None:
        """Pull ISBN/publisher/year from the lazily loaded block when missing."""
        if "isbn" in record.identifiers and record.publisher and record.publishedDate:
            return
        match = re.search(r"-(\d+)$", str(record.id))
        if not match:
            return
        try:
            response = session.get(cls.MORE_INFO_URL.format(match.group(1)), timeout=cls.TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            log.debug("databazeknih.cz more-info fetch failed: %s", exc)
            return
        soup = BeautifulSoup(response.text or "", "html.parser")
        if "isbn" not in record.identifiers:
            isbn = cls._isbn(soup)
            if isbn:
                record.identifiers["isbn"] = isbn
        record.publisher = record.publisher or _itemprop(soup, "publisher")
        record.publishedDate = record.publishedDate or cls._year(soup)

    @staticmethod
    def _title(soup: BeautifulSoup) -> Optional[str]:
        node = soup.select_one('h1[itemprop="name"]') or soup.select_one("h1")
        if node:
            # Edition/series badges are nested tags; only direct text is the title.
            direct = _clean("".join(node.find_all(string=True, recursive=False)))
            title = direct or _clean(node.get_text(" "))
            if title:
                return title
        og_title = soup.select_one('meta[property="og:title"][content]')
        if og_title:
            return _clean(str(og_title["content"]).split(" | ")[0])
        return None

    @staticmethod
    def _authors(soup: BeautifulSoup) -> List[str]:
        nodes = soup.select(
            '[itemprop="author"] [itemprop="name"], a[itemprop="author"], '
            '[itemprop="author"] a, h2.jmenaautoru a'
        )
        authors: List[str] = []
        for node in nodes:
            name = _clean(node.get_text(" "))
            if name and name not in authors:
                authors.append(name)
        return authors

    @staticmethod
    def _cover(soup: BeautifulSoup) -> Optional[str]:
        for selector, attr in (
            ("img.kniha_img", "src"),
            ('img[itemprop="image"]', "src"),
            ('meta[property="og:image"]', "content"),
        ):
            node = soup.select_one(selector)
            if node and node.get(attr):
                url = urljoin(Databazeknih.META_URL, str(node.get(attr)))
                if not _is_placeholder_cover(url):
                    return url
        return None

    @staticmethod
    def _description(soup: BeautifulSoup) -> str:
        node = soup.select_one('[itemprop="description"]')
        if node is not None and node.name != "meta":
            # The full text sits in a hidden span next to a truncated preview.
            full = node.select_one(".end_text, .celytext")
            text = _clean((full or node).get_text(" ")) or ""
        else:
            meta = soup.select_one('meta[property="og:description"][content]')
            text = _clean(str(meta["content"])) if meta else ""
            text = text or ""
        for noise in DESCRIPTION_NOISE:
            if text.endswith(noise):
                text = text[: -len(noise)].rstrip()
        return text

    @staticmethod
    def _year(root) -> Optional[str]:
        text = _itemprop(root, "datePublished")
        match = YEAR_RE.search(text) if text else None
        return match.group(1) if match else None

    @staticmethod
    def _isbn(root) -> Optional[str]:
        candidates = [n.get_text(" ") for n in root.select('[itemprop="isbn"]')]
        candidates += re.findall(r"ISBN[:\s]*([\dXx-]{10,17})", root.get_text(" "))
        isbn_10 = None
        for raw in candidates:
            for candidate in re.findall(r"[\dXx-]{10,17}", raw):
                isbn = _valid_isbn(candidate)
                if isbn and len(isbn) == 13:
                    return isbn
                isbn_10 = isbn_10 or isbn
        return isbn_10

    @staticmethod
    def _tags(soup: BeautifulSoup) -> List[str]:
        tags: List[str] = []
        nodes = soup.select('[itemprop="genre"]') or soup.select('a[href*="zanry/"]')
        for node in nodes:
            for part in node.get_text(",").split(","):
                tag = _clean(part)
                if tag and tag not in tags:
                    tags.append(tag)
        return tags

    @staticmethod
    def _rating(soup: BeautifulSoup) -> int:
        """Site rating is a percentage; Calibre wants 0-5 stars."""
        node = soup.select_one(".bpoints, .hodnoceni_rating")
        text = _clean(node.get_text(" ")) if node else _itemprop(soup, "ratingValue")
        match = re.search(r"\d+(?:[.,]\d+)?", text or "")
        if not match:
            return 0
        try:
            return max(0, min(5, round(float(match.group(0).replace(",", ".")) / 20)))
        except ValueError:
            return 0

    @staticmethod
    def _series(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[float]]:
        node = soup.select_one('a[href*="serie/"]')
        name = _clean(node.get_text(" ")) if isinstance(node, Tag) else None
        if not name:
            return None, None
        context = node.parent.get_text(" ") if node.parent else ""
        match = SERIES_POSITION_RE.search(context)
        if not match:
            return name, None
        value = float(match.group(1).replace(",", "."))
        return name, int(value) if value.is_integer() else value

    @staticmethod
    def _language(soup: BeautifulSoup) -> str:
        text = (_itemprop(soup, "inLanguage") or "").lower()
        for word in text.replace(",", " ").split():
            code = LANGUAGE_MAP.get(word)
            if code:
                return code
        return "ces"
