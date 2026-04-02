"""
tests/test_normalizers.py
tests/test_deduplicator.py  (included here in one file for simplicity)
---------------------------------------------------------------------------
Run with:  python -m pytest tests/  OR  python -m unittest discover tests/
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from normalizers import (
    normalize_authors,
    normalize_bulletin_number,
    normalize_date,
    normalize_text,
    normalize_url,
)
from deduplicator import assign_duplicate_groups, build_duplicate_clusters

import pandas as pd


# ===========================================================================
# normalize_text
# ===========================================================================

class TestNormalizeText(unittest.TestCase):

    def test_strip_whitespace(self):
        self.assertEqual(normalize_text("  hello  "), "hello")

    def test_collapse_internal_spaces(self):
        self.assertEqual(normalize_text("hello   world"), "hello world")

    def test_collapse_tabs_and_newlines(self):
        self.assertEqual(normalize_text("hello\t\nworld"), "hello world")

    def test_html_entities(self):
        self.assertEqual(normalize_text("AT&amp;T"), "AT&T")
        self.assertEqual(normalize_text("&lt;title&gt;"), "<title>")

    def test_html_tags_stripped(self):
        self.assertEqual(normalize_text("<b>Hello</b> <i>world</i>"), "Hello world")

    def test_complex_html(self):
        result = normalize_text("<p>  Proyecto &amp; Ley  <br/>\n  de  Presupuesto  </p>")
        self.assertEqual(result, "Proyecto & Ley de Presupuesto")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_text(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_text(""), "")


# ===========================================================================
# normalize_bulletin_number
# ===========================================================================

class TestNormalizeBulletinNumber(unittest.TestCase):

    def test_already_canonical(self):
        self.assertEqual(normalize_bulletin_number("12345-07"), "12345-07")

    def test_missing_dash(self):
        # 7 digits → 5-digit main + 2-digit suffix
        self.assertEqual(normalize_bulletin_number("1142207"), "11422-07")
        # 8 digits → 6-digit main + 2-digit suffix
        self.assertEqual(normalize_bulletin_number("12345607"), "")

    def test_slash_separator(self):
        self.assertEqual(normalize_bulletin_number("12345/07"), "12345-07")

    def test_spaces_around_dash(self):
        self.assertEqual(normalize_bulletin_number("  12345 - 07  "), "12345-07")

    def test_no_pattern_returns_empty(self):
        self.assertEqual(normalize_bulletin_number("ABC"), "")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_bulletin_number(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_bulletin_number(""), "")

    def test_five_digit_main_accepted(self):
        # 5-digit main part is valid (matches real CSV data)
        self.assertEqual(normalize_bulletin_number("11422-07"), "11422-07")
        self.assertEqual(normalize_bulletin_number("1142207"), "11422-07")


# ===========================================================================
# normalize_url
# ===========================================================================

class TestNormalizeUrl(unittest.TestCase):

    def test_lowercase_host(self):
        result = normalize_url("https://WWW.EXAMPLE.COM/path")
        self.assertIn("www.example.com", result)

    def test_remove_utm_params(self):
        url = "https://example.com/page?utm_source=google&id=1"
        result = normalize_url(url)
        self.assertNotIn("utm_source", result)
        self.assertIn("id=1", result)

    def test_remove_gclid(self):
        result = normalize_url("https://example.com/?gclid=abc123&page=2")
        self.assertNotIn("gclid", result)
        self.assertIn("page=2", result)

    def test_remove_fbclid(self):
        result = normalize_url("https://example.com/?fbclid=xyz&q=1")
        self.assertNotIn("fbclid", result)

    def test_remove_trailing_slash(self):
        result = normalize_url("https://example.com/docs/")
        self.assertEqual(result, "https://example.com/docs")

    def test_root_url_no_trailing_slash(self):
        # Root URL: trailing slash removed, empty path
        result = normalize_url("https://example.com/")
        self.assertEqual(result, "https://example.com")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_url(""), "")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_url(None), "")

    def test_no_scheme_returns_empty(self):
        self.assertEqual(normalize_url("example.com/path"), "")

    def test_deterministic(self):
        url = "https://Example.COM/docs/?utm_campaign=X&id=5"
        self.assertEqual(normalize_url(url), normalize_url(url))


# ===========================================================================
# normalize_date
# ===========================================================================

class TestNormalizeDate(unittest.TestCase):

    def test_iso_date(self):
        self.assertEqual(normalize_date("2024-03-15"), "2024-03-15")

    def test_date_with_slashes(self):
        result = normalize_date("15/03/2024")
        self.assertEqual(result, "2024-03-15")

    def test_datetime_iso(self):
        result = normalize_date("2024-03-15T10:30:00")
        self.assertEqual(result, "2024-03-15T10:30:00")

    def test_datetime_with_tz(self):
        result = normalize_date("2024-03-15T10:30:00+03:00")
        self.assertIn("2024-03-15", result)
        self.assertIn("10:30:00", result)

    def test_datetime_natural(self):
        result = normalize_date("March 15, 2024 10:30 AM")
        self.assertIn("2024-03-15", result)

    def test_unparseable_returns_empty(self):
        self.assertEqual(normalize_date("not a date"), "")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_date(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_date(""), "")

    def test_deterministic(self):
        d = "2023-07-04T12:00:00"
        self.assertEqual(normalize_date(d), normalize_date(d))


# ===========================================================================
# normalize_authors
# ===========================================================================

class TestNormalizeAuthors(unittest.TestCase):

    def test_single_author(self):
        self.assertEqual(normalize_authors("Alice"), "Alice")
        print(normalize_authors("Alice"))

    def test_csv_authors(self):
        result = normalize_authors("Alice, Bob, Carol")
        self.assertEqual(result, "Alice | Bob | Carol")

    def test_pipe_authors(self):
        result = normalize_authors("Alice | Bob")
        self.assertEqual(result, "Alice | Bob")

    def test_json_array_strings(self):
        result = normalize_authors('["Alice", "Bob"]')
        self.assertEqual(result, "Alice | Bob")

    def test_json_array_objects(self):
        result = normalize_authors('[{"name": "Alice"}, {"name": "Bob"}]')
        self.assertEqual(result, "Alice | Bob")

    def test_deduplication(self):
        result = normalize_authors("Alice, Alice, Bob")
        self.assertEqual(result, "Alice | Bob")

    def test_case_insensitive_dedup(self):
        result = normalize_authors("alice, Alice")
        self.assertEqual(result, "alice")

    def test_none_returns_empty(self):
        self.assertEqual(normalize_authors(None), "")

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_authors(""), "")


# ===========================================================================
# Deduplication
# ===========================================================================

def _make_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "record_id": "", "source": "", "source_type": "misc",
        "bulletin_number": "", "title": "", "summary": "",
        "published_at": "", "event_date": "", "status": "",
        "initiative": "", "authors": "", "canonical_url": "",
        "canonical_document_url": "", "content_hash_hint": "",
    }
    full_rows = [{**defaults, **r} for r in rows]
    return pd.DataFrame(full_rows)


class TestDeduplication(unittest.TestCase):

    def test_url_dedup(self):
        """Two records with same URL → one kept."""
        df = _make_df([
            {"record_id": "A", "canonical_url": "https://example.com/doc",
             "title": "Title A", "source_type": "misc"},
            {"record_id": "B", "canonical_url": "https://example.com/doc",
             "title": "Title B", "source_type": "detail"},
        ])
        result = assign_duplicate_groups(df)
        # Same group
        grps = result["duplicate_group_id"].unique()
        self.assertEqual(len(grps), 1)
        # detail wins over misc
        canonical = result[result["is_canonical"]]["record_id"].iloc[0]
        self.assertEqual(canonical, "B")

    def test_bulletin_title_dedup(self):
        """Two records, no URL, same bulletin + title → deduplicated."""
        df = _make_df([
            {"record_id": "A", "bulletin_number": "123456-07",
             "title": "Some Law", "source_type": "api"},
            {"record_id": "B", "bulletin_number": "123456-07",
             "title": "Some Law", "source_type": "table"},
        ])
        result = assign_duplicate_groups(df)
        grps = result["duplicate_group_id"].unique()
        self.assertEqual(len(grps), 1)
        # table > api
        canonical = result[result["is_canonical"]]["record_id"].iloc[0]
        self.assertEqual(canonical, "B")

    def test_hash_title_dedup(self):
        """Two records with same content_hash_hint + title → deduplicated."""
        df = _make_df([
            {"record_id": "A", "content_hash_hint": "abc123",
             "title": "Law Text", "source_type": "misc"},
            {"record_id": "B", "content_hash_hint": "abc123",
             "title": "Law Text", "source_type": "news"},
        ])
        result = assign_duplicate_groups(df)
        grps = result["duplicate_group_id"].unique()
        self.assertEqual(len(grps), 1)
        # news > misc
        canonical = result[result["is_canonical"]]["record_id"].iloc[0]
        self.assertEqual(canonical, "B")

    def test_different_urls_not_deduped(self):
        """Two records with different URLs stay separate."""
        df = _make_df([
            {"record_id": "A", "canonical_url": "https://a.com/doc1", "title": "T"},
            {"record_id": "B", "canonical_url": "https://b.com/doc2", "title": "T"},
        ])
        result = assign_duplicate_groups(df)
        self.assertEqual(result["is_canonical"].sum(), 2)

    def test_richness_tiebreak(self):
        """When source_type is equal, richer record wins."""
        df = _make_df([
            {"record_id": "A", "canonical_url": "https://example.com/doc",
             "title": "T", "source_type": "misc", "summary": "", "authors": ""},
            {"record_id": "B", "canonical_url": "https://example.com/doc",
             "title": "T", "source_type": "misc",
             "summary": "Rich summary", "authors": "Author X"},
        ])
        result = assign_duplicate_groups(df)
        canonical = result[result["is_canonical"]]["record_id"].iloc[0]
        self.assertEqual(canonical, "B")

    def test_lexicographic_tiebreak(self):
        """All else equal, lexicographically smaller record_id wins."""
        df = _make_df([
            {"record_id": "Z", "canonical_url": "https://x.com/y",
             "title": "T", "source_type": "misc"},
            {"record_id": "A", "canonical_url": "https://x.com/y",
             "title": "T", "source_type": "misc"},
        ])
        result = assign_duplicate_groups(df)
        canonical = result[result["is_canonical"]]["record_id"].iloc[0]
        self.assertEqual(canonical, "A")

    def test_deterministic(self):
        """Running twice on same input yields identical results."""
        df = _make_df([
            {"record_id": "A", "canonical_url": "https://example.com/doc", "title": "T"},
            {"record_id": "B", "canonical_url": "https://example.com/doc", "title": "T"},
            {"record_id": "C", "canonical_url": "https://other.com/doc", "title": "Other"},
        ])
        r1 = assign_duplicate_groups(df.copy())
        r2 = assign_duplicate_groups(df.copy())
        pd.testing.assert_frame_equal(
            r1[["record_id", "duplicate_group_id", "is_canonical"]].reset_index(drop=True),
            r2[["record_id", "duplicate_group_id", "is_canonical"]].reset_index(drop=True),
        )

    def test_cluster_output(self):
        """build_duplicate_clusters returns correct shape."""
        df = _make_df([
            {"record_id": "A", "canonical_url": "https://x.com/doc", "title": "T"},
            {"record_id": "B", "canonical_url": "https://x.com/doc", "title": "T"},
        ])
        df = assign_duplicate_groups(df)
        clusters = build_duplicate_clusters(df)
        self.assertIn("duplicate_group_id", clusters.columns)
        self.assertIn("record_id", clusters.columns)
        self.assertIn("is_kept", clusters.columns)
        self.assertIn("duplicate_reason", clusters.columns)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters["is_kept"].sum(), 1)


# ===========================================================================
# Integration smoke test
# ===========================================================================

class TestPipelineIntegration(unittest.TestCase):
    """
    End-to-end smoke test using an in-memory CSV.
    Validates that the pipeline produces the 4 expected output files.
    """

    def setUp(self):
        import tempfile, csv, io
        from pathlib import Path
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "output"

        rows = [
            # Valid record
            {
                "record_id": "REC001", "source": "web", "source_type": "detail",
                "bulletin_number": "123456-07", "title_raw": "<b>Ley &amp; Norma</b>",
                "summary_raw": "  Resumen  \n del proyecto  ",
                "published_at_raw": "2024-01-15", "event_date_raw": "",
                "status_raw": "Vigente", "initiative_raw": "Parlamentaria",
                "authors_raw": '["Juan Pérez", "María López"]',
                "url_raw": "https://Example.COM/doc/1?utm_source=google",
                "document_url_raw": "", "html_snippet": "",
                "content_hash_hint": "aabbcc",
            },
            # Duplicate of REC001 (same URL)
            {
                "record_id": "REC002", "source": "web", "source_type": "misc",
                "bulletin_number": "123456-07", "title_raw": "Ley y Norma",
                "summary_raw": "", "published_at_raw": "2024-01-10",
                "event_date_raw": "", "status_raw": "", "initiative_raw": "",
                "authors_raw": "", "url_raw": "https://example.com/doc/1",
                "document_url_raw": "", "html_snippet": "", "content_hash_hint": "",
            },
            # Invalid: no title
            {
                "record_id": "REC003", "source": "web", "source_type": "api",
                "bulletin_number": "", "title_raw": "   ",
                "summary_raw": "some summary", "published_at_raw": "",
                "event_date_raw": "", "status_raw": "", "initiative_raw": "",
                "authors_raw": "", "url_raw": "https://x.com/something",
                "document_url_raw": "", "html_snippet": "", "content_hash_hint": "",
            },
            # Invalid: title but no identifiers
            {
                "record_id": "REC004", "source": "web", "source_type": "api",
                "bulletin_number": "", "title_raw": "A title",
                "summary_raw": "", "published_at_raw": "",
                "event_date_raw": "", "status_raw": "", "initiative_raw": "",
                "authors_raw": "", "url_raw": "",
                "document_url_raw": "", "html_snippet": "", "content_hash_hint": "",
            },
        ]

        csv_path = self.tmp / "legislative_records.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        self.csv_path = csv_path

    def test_pipeline_runs_and_produces_outputs(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from part1 import run_pipeline

        run_pipeline(self.csv_path, self.out)

        self.assertTrue((self.out / "normalized_records.csv").exists())
        self.assertTrue((self.out / "rejected_records.csv").exists())
        self.assertTrue((self.out / "duplicate_clusters.csv").exists())
        self.assertTrue((self.out / "quality_report.json").exists())

        norm = pd.read_csv(self.out / "normalized_records.csv", dtype=str)
        rejected = pd.read_csv(self.out / "rejected_records.csv", dtype=str)

        # REC001 kept, REC002 is duplicate → 1 canonical
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm.iloc[0]["kept_record_id"], "REC001")

        # REC003 and REC004 rejected
        self.assertEqual(len(rejected), 2)
        reasons = set(rejected["rejection_reason"].tolist())
        self.assertIn("missing_title", reasons)
        self.assertIn("missing_all_identifiers", reasons)

        import json
        report = json.loads((self.out / "quality_report.json").read_text())
        self.assertEqual(report["input_rows"], 4)
        self.assertEqual(report["rejected_rows"], 2)
        self.assertEqual(report["duplicates_removed"], 1)
        self.assertEqual(report["normalized_rows"], 1)

    def test_pipeline_deterministic(self):
        """Running twice yields identical normalized_records.csv."""
        from part1 import run_pipeline

        out1 = self.out / "run1"
        out2 = self.out / "run2"
        run_pipeline(self.csv_path, out1)
        run_pipeline(self.csv_path, out2)

        df1 = pd.read_csv(out1 / "normalized_records.csv", dtype=str)
        df2 = pd.read_csv(out2 / "normalized_records.csv", dtype=str)
        pd.testing.assert_frame_equal(df1, df2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
