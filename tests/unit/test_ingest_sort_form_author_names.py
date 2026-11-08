# SPDX-License-Identifier: GPL-3.0-or-later
"""Authors stored in sort form ("Lasica, Milan") are restored on ingest.

Many Czech and Slovak EPUBs carry
``<dc:creator opf:file-as="Lasica, Milan">Lasica, Milan</dc:creator>``:
the sort form is written into the display name too. Calibre takes the element
text as the name, so every such book landed under a reversed author that never
merged with the same author imported correctly.

The helper is exercised with a stand-in for Calibre's ``Metadata`` (the Calibre
modules are stubbed, as in ``test_acquisition_calibre_transaction``); the
end-to-end proof is ingesting such an EPUB into a running container.

Also pins the companion fix in ``cps.metadata_helper``: an author created by the
automatic metadata fetch gets a real sort value instead of the name repeated.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def helper(monkeypatch):
    modules = {
        "calibre.db.adding": ["run_import_plugins", "run_import_plugins_before_metadata"],
        "calibre.db.legacy": ["LibraryDatabase"],
        "calibre.db.utils": ["find_identical_books"],
        "calibre.ebooks.metadata": ["string_to_authors"],
        "calibre.ebooks.metadata.meta": ["get_metadata"],
        "calibre.ptempfile": ["TemporaryDirectory"],
    }
    for name, attributes in modules.items():
        module = types.ModuleType(name)
        for attribute in attributes:
            setattr(module, attribute, lambda *args, **kwargs: None)
        monkeypatch.setitem(sys.modules, name, module)
    path = REPO / "scripts/calibre_ingest_transaction.py"
    spec = importlib.util.spec_from_file_location("_sort_form_author_helper_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mi(authors, author_sort="", author_sort_map=None):
    return types.SimpleNamespace(
        authors=list(authors),
        author_sort=author_sort,
        author_sort_map=dict(author_sort_map or {}),
    )


def test_reversed_name_with_matching_file_as_is_restored(helper):
    # The exact shape of the reported EPUB (Milan Lasica - Bodka II).
    mi = _mi(["Lasica, Milan"], "Lasica, Milan", {"Lasica, Milan": "Lasica, Milan"})
    assert helper.restore_sort_form_author_names(mi) is True
    assert mi.authors == ["Milan Lasica"]
    assert mi.author_sort_map == {"Milan Lasica": "Lasica, Milan"}
    assert mi.author_sort == "Lasica, Milan"


def test_reversed_name_without_sort_map_uses_book_sort(helper):
    mi = _mi(["Lasica, Milan"], "Lasica, Milan")
    assert helper.restore_sort_form_author_names(mi) is True
    assert mi.authors == ["Milan Lasica"]


def test_reversed_name_without_any_declared_sort_is_restored(helper):
    mi = _mi(["Lasica, Milan"])
    assert helper.restore_sort_form_author_names(mi) is True
    assert mi.authors == ["Milan Lasica"]
    assert mi.author_sort == "Lasica, Milan"


def test_display_form_is_left_alone(helper):
    mi = _mi(["Milan Lasica"], "Lasica, Milan", {"Milan Lasica": "Lasica, Milan"})
    assert helper.restore_sort_form_author_names(mi) is False
    assert mi.authors == ["Milan Lasica"]
    assert mi.author_sort == "Lasica, Milan"


def test_comma_name_with_a_different_declared_sort_is_deliberate(helper):
    # The file says the sort is something else, so the comma is intended.
    mi = _mi(["Smith, Barney"], "Barney Smith", {"Smith, Barney": "Barney Smith"})
    assert helper.restore_sort_form_author_names(mi) is False
    assert mi.authors == ["Smith, Barney"]


@pytest.mark.parametrize("name", ["King, Jr.", "Gates, III", "Doe, PhD"])
def test_name_suffix_after_comma_is_not_a_reversal(helper, name):
    mi = _mi([name], name, {name: name})
    assert helper.restore_sort_form_author_names(mi) is False
    assert mi.authors == [name]


@pytest.mark.parametrize("name", ["Lasica, Milan, ml.", ", Milan", "Lasica,", "Unknown"])
def test_ambiguous_names_are_not_touched(helper, name):
    mi = _mi([name], name, {name: name})
    assert helper.restore_sort_form_author_names(mi) is False
    assert mi.authors == [name]


def test_only_the_reversed_coauthor_changes(helper):
    mi = _mi(
        ["Lasica, Milan", "Július Satinský"],
        "Lasica, Milan & Satinský, Július",
        {"Lasica, Milan": "Lasica, Milan", "Július Satinský": "Satinský, Július"},
    )
    assert helper.restore_sort_form_author_names(mi) is True
    assert mi.authors == ["Milan Lasica", "Július Satinský"]
    assert mi.author_sort_map == {
        "Milan Lasica": "Lasica, Milan",
        "Július Satinský": "Satinský, Július",
    }
    # A combined sort the file declared on its own stays as declared.
    assert mi.author_sort == "Lasica, Milan & Satinský, Július"


def test_prepare_book_restores_before_overrides(helper, monkeypatch, tmp_path):
    """The ingest path runs the restore, and an explicit override still wins."""
    from contextlib import contextmanager

    book = tmp_path / "Bodka II.epub"
    book.write_bytes(b"epub")

    @contextmanager
    def _temp_dir(*args, **kwargs):
        yield str(tmp_path)

    @contextmanager
    def _before_metadata(*args, **kwargs):
        yield

    monkeypatch.setattr(helper, "TemporaryDirectory", _temp_dir)
    monkeypatch.setattr(helper, "run_import_plugins_before_metadata", _before_metadata)
    monkeypatch.setattr(helper, "run_import_plugins", lambda paths: paths)
    monkeypatch.setattr(helper, "string_to_authors", lambda value: [value])

    def _read(mi_authors):
        return lambda stream, stream_type, use_libprs_metadata: types.SimpleNamespace(
            title="Bodka II", authors=list(mi_authors), author_sort="Lasica, Milan",
            author_sort_map={"Lasica, Milan": "Lasica, Milan"})

    monkeypatch.setattr(helper, "get_metadata", _read(["Lasica, Milan"]))
    for metadata, extension, _path in helper.prepare_book(str(book), {}):
        assert metadata.authors == ["Milan Lasica"]
        assert extension == "epub"

    for metadata, _extension, _path in helper.prepare_book(str(book), {"authors": "Lasica, Milan"}):
        assert metadata.authors == ["Lasica, Milan"]


def test_autofetched_new_author_gets_a_real_sort(monkeypatch):
    import cps.metadata_helper as m

    created = []

    class _Authors:
        def __init__(self, name, sort, link=""):
            self.name, self.sort = name, sort
            created.append(self)

    class _List(list):
        pass

    class _Session:
        def add(self, *a, **k):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

    class _CDB:
        session = _Session()

        def get_author_by_name(self, name):
            return None

        def get_publisher_by_name(self, name):
            return None

        def get_tag_by_name(self, name):
            return None

        def get_series_by_name(self, name):
            return None

    settings = {
        "auto_metadata_smart_application": False,
        "auto_metadata_update_authors": True,
    }
    monkeypatch.setattr(m, "CWA_DB", lambda: types.SimpleNamespace(get_cwa_settings=lambda: settings))
    monkeypatch.setattr(m.db, "Authors", _Authors)

    book = types.SimpleNamespace(
        id=1, title="Bodka II", authors=_List(), comments=_List(), publishers=_List(),
        tags=_List(), series=_List(), series_index="1.0", pubdate=None,
        ratings=_List(), identifiers=_List())
    meta = types.SimpleNamespace(
        title="", authors=["Milan Lasica"], description="", publisher="", tags=[],
        series=None, series_index=None, publishedDate=None, rating=None,
        identifiers={}, cover=None)

    m._apply_metadata_to_book(book, meta, _CDB())

    assert [(a.name, a.sort) for a in created] == [("Milan Lasica", "Lasica, Milan")]
