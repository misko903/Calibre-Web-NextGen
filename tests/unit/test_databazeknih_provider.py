# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Recorded-fixture and failure-contract tests for the Databáze knih scraper."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from cps.metadata_constants import metadata_provider_enabled
from cps.metadata_provider.databazeknih import Databazeknih


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata"

pytestmark = pytest.mark.unit


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def ok(text):
    response = Mock(text=text)
    response.raise_for_status.return_value = None
    return response


def http_error(status):
    return requests.HTTPError(f"{status} Client Error", response=Mock(status_code=status))


def test_default_off_but_explicit_choice_wins():
    assert metadata_provider_enabled("databazeknih", {}) is False
    assert metadata_provider_enabled("databazeknih", {"databazeknih": True}) is True


def test_search_page_yields_unique_book_slugs_in_rank_order():
    assert Databazeknih._parse_search(fixture("databazeknih_search.html")) == [
        "saturnin-15",
        "saturnin-se-vraci-24577",
    ]


def test_book_page_fixture():
    record = Databazeknih._parse_book(fixture("databazeknih_book.html"), "saturnin-15", "generic.svg")
    # Nested edition badge is not part of the title
    assert record.title == "Saturnin"
    assert record.authors == ["Zdeněk Jirotka"]
    assert record.url == "https://www.databazeknih.cz/knihy/saturnin-15"
    assert record.cover == "https://www.databazeknih.cz/img/books/15_/15/big_saturnin-15.jpg"
    # Full text from the hidden span, "celý text" toggle stripped
    assert record.description == "Humoristický román o sluhovi Saturninovi a jeho pánovi."
    assert record.tags == ["Literatura česká", "Romány"]
    assert record.rating == 4  # 89 % -> 4 stars
    assert record.series == "Saturnin"
    assert record.series_index == 1
    assert record.identifiers == {"databazeknih": "saturnin-15"}


def test_full_search_merges_lazy_more_info_block():
    responses = [
        ok(fixture("databazeknih_search.html")),
        ok(fixture("databazeknih_book.html")),
        ok(fixture("databazeknih_more_info.html")),
        ok(fixture("databazeknih_book.html")),
        ok(fixture("databazeknih_more_info.html")),
    ]
    with patch("requests.Session.get", side_effect=responses) as get:
        records = Databazeknih().search("Saturnin")
    assert len(records) == 2
    record = records[0]
    assert record.identifiers == {"databazeknih": "saturnin-15", "isbn": "9788072272825"}
    assert record.publisher == "Druhé město"
    assert record.publishedDate == "2008"
    assert get.call_args_list[2].args[0] == "https://www.databazeknih.cz/book-detail-more-info/15"


def test_search_landing_on_book_page_returns_that_book():
    responses = [ok(fixture("databazeknih_book.html")), ok(fixture("databazeknih_more_info.html"))]
    with patch("requests.Session.get", side_effect=responses):
        records = Databazeknih().search("9788072272825")
    assert [r.id for r in records] == ["saturnin-15"]


def test_more_info_failure_keeps_the_record():
    responses = [ok(fixture("databazeknih_book.html")), requests.Timeout("slow")]
    with patch("requests.Session.get", side_effect=responses):
        records = Databazeknih().search("Saturnin Jirotka")
    assert records[0].title == "Saturnin"
    assert "isbn" not in records[0].identifiers


@pytest.mark.parametrize("bad", [None, "", "not html", 7, [], {}])
def test_malformed_pages_are_none_or_empty(bad):
    assert Databazeknih._parse_search(bad) == []
    assert Databazeknih._parse_book(bad, "x-1", "generic.svg") is None


@pytest.mark.parametrize("query", [None, "", "   ", 123])
def test_negative_queries_do_not_touch_network(query):
    with patch("requests.Session.get") as get:
        assert Databazeknih().search(query) == []
    get.assert_not_called()


@pytest.mark.parametrize("failure", [requests.ConnectionError("down"), requests.Timeout("slow")])
def test_unreachable_degrades_quietly(failure):
    with patch("requests.Session.get", side_effect=failure):
        assert Databazeknih().search("Saturnin") == []


@pytest.mark.parametrize("status", [429, 403])
def test_search_refusal_reaches_the_caller(status):
    with patch("requests.Session.get", side_effect=http_error(status)):
        with pytest.raises(requests.HTTPError):
            Databazeknih().search("Saturnin")


def test_refused_book_pages_report_the_refusal_when_nothing_was_read():
    responses = [ok(fixture("databazeknih_search.html")), http_error(429), http_error(429)]
    with patch("requests.Session.get", side_effect=responses):
        with pytest.raises(requests.HTTPError):
            Databazeknih().search("Saturnin")
