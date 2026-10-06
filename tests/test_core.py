from __future__ import annotations

import sqlite3
import unittest

from scraper import db
from scraper.audit import contacts
from scraper.audit.website import (
    detect_builder, is_social_host, latest_copyright_year, normalize_url,
)
from scraper.scoring import classify, lead_score
from scraper.sources import google_places
from scraper.sources.base import Lead, is_likely_whatsapp, normalize_phone
from scraper.sources.csv_import import build_column_map, row_to_lead


def memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def audit(**over):
    base = {
        "has_website": 1, "website_is_social": 0, "http_status": 200, "https": 1,
        "load_ms": 1200, "psi_mobile": None, "mobile_viewport": 1, "has_cta": 1,
        "copyright_year": 2026, "builder": "", "error": "",
    }
    base.update(over)
    return base


class PhoneTests(unittest.TestCase):
    def test_nigerian_formats(self):
        self.assertEqual(normalize_phone("0803 123 4567"), "+2348031234567")
        self.assertEqual(normalize_phone("08031234567"), "+2348031234567")
        self.assertEqual(normalize_phone("2348031234567"), "+2348031234567")
        self.assertEqual(normalize_phone("+234 803 123 4567"), "+2348031234567")
        self.assertEqual(normalize_phone("8031234567"), "+2348031234567")
        self.assertEqual(normalize_phone("0803 123 4567 / 0805 111 2222"), "+2348031234567")

    def test_empty_and_foreign(self):
        self.assertEqual(normalize_phone(None), "")
        self.assertEqual(normalize_phone("n/a"), "")
        self.assertEqual(normalize_phone("+44 20 7946 0958"), "+442079460958")

    def test_whatsapp_guess(self):
        self.assertTrue(is_likely_whatsapp("+2348031234567"))
        self.assertFalse(is_likely_whatsapp("+23412345678"))  # landline-like


class DedupeTests(unittest.TestCase):
    def test_same_phone_merges_across_sources(self):
        conn = memory_db()
        a = Lead("csv", "1", "Acme Realty", city="Lagos", phone="0803 123 4567")
        b = Lead("google_places", "X", "ACME Realty Ltd", city="Lagos",
                 phone="+234 803 123 4567", website="acme.ng", rating=4.5, review_count=40)
        id_a, st_a = db.upsert_lead(conn, a)
        id_b, st_b = db.upsert_lead(conn, b)
        self.assertEqual((st_a, st_b), ("inserted", "merged"))
        self.assertEqual(id_a, id_b)
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (id_a,)).fetchone()
        self.assertEqual(row["website"], "acme.ng")  # empty field filled
        self.assertEqual(row["name"], "Acme Realty")  # existing name kept
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 1)

    def test_same_source_id_overwrites_nonempty(self):
        conn = memory_db()
        db.upsert_lead(conn, Lead("csv", "1", "Foo", phone="08031234567", rating=3.0))
        db.upsert_lead(conn, Lead("csv", "1", "Foo", phone="08031234567", rating=4.2))
        row = conn.execute("SELECT rating FROM leads").fetchone()
        self.assertEqual(row["rating"], 4.2)

    def test_no_phone_dedupes_by_name_and_city(self):
        conn = memory_db()
        db.upsert_lead(conn, Lead("csv", "1", "Bright Kids School", city="Abuja"))
        _id, status = db.upsert_lead(conn, Lead("other", "9", "bright kids  school", city="abuja"))
        self.assertEqual(status, "merged")


class CsvTests(unittest.TestCase):
    def test_apify_style_columns(self):
        cols = ["title", "address", "phone", "website", "totalScore", "reviewsCount", "placeId", "categoryName"]
        mapping = build_column_map(cols)
        row = {"title": "Sunrise Clinic", "address": "1 Allen Ave", "phone": "0803 111 2222",
               "website": "", "totalScore": "4.6", "reviewsCount": "120",
               "placeId": "ChIJ123", "categoryName": "Clinic"}
        lead = row_to_lead(row, mapping, "apify", city="Lagos", country="Nigeria")
        self.assertEqual(lead.name, "Sunrise Clinic")
        self.assertEqual(lead.phone, "+2348031112222")
        self.assertEqual(lead.whatsapp, "+2348031112222")
        self.assertEqual(lead.rating, 4.6)
        self.assertEqual(lead.review_count, 120)
        self.assertEqual(lead.source_id, "ChIJ123")
        self.assertEqual(lead.city, "Lagos")

    def test_outscraper_style_columns(self):
        mapping = build_column_map(["name", "full_address", "phone", "site", "rating", "reviews", "google_id"])
        self.assertEqual(mapping["address"], "full_address")
        self.assertEqual(mapping["website"], "site")
        self.assertEqual(mapping["review_count"], "reviews")

    def test_row_without_name_is_skipped(self):
        mapping = build_column_map(["name", "phone"])
        self.assertIsNone(row_to_lead({"name": " ", "phone": "1"}, mapping, "csv"))

    def test_generated_source_id_is_stable(self):
        mapping = build_column_map(["name", "phone"])
        one = row_to_lead({"name": "A", "phone": "08031234567"}, mapping, "csv")
        two = row_to_lead({"name": "A", "phone": "08031234567"}, mapping, "csv")
        self.assertEqual(one.source_id, two.source_id)


class ScoringTests(unittest.TestCase):
    def test_no_website_is_tier_a(self):
        self.assertEqual(classify(audit(has_website=0))[0], "A")

    def test_social_only_is_tier_a(self):
        self.assertEqual(classify(audit(website_is_social=1))[0], "A")

    def test_unreachable_is_tier_b(self):
        self.assertEqual(classify(audit(http_status=None, error="timeout"))[0], "B")

    def test_bot_block_is_not_called_broken(self):
        tier, _pts, reasons = classify(audit(http_status=403))
        self.assertEqual(tier, "C")
        self.assertIn("verify by hand", reasons[0])

    def test_many_problems_is_tier_b(self):
        tier, pts, _ = classify(audit(https=0, mobile_viewport=0, copyright_year=2018), year=2026)
        self.assertEqual(tier, "B")
        self.assertGreaterEqual(pts, 3)

    def test_one_minor_problem_is_tier_c(self):
        self.assertEqual(classify(audit(has_cta=0))[0], "C")

    def test_clean_site_is_tier_d(self):
        self.assertEqual(classify(audit())[0], "D")

    def test_demand_and_contactability_raise_score(self):
        strong = {"rating": 4.8, "review_count": 300, "whatsapp": "+2348031234567", "phone": "x", "email": ""}
        weak = {"rating": None, "review_count": None, "whatsapp": "", "phone": "", "email": ""}
        self.assertGreater(lead_score(strong, "A", 0, 1.0), lead_score(weak, "A", 0, 1.0))
        self.assertLess(lead_score(weak, "A", 0, 1.0), lead_score(strong, "B", 0, 1.0))


class AuditHelperTests(unittest.TestCase):
    def test_social_hosts(self):
        self.assertTrue(is_social_host("https://www.facebook.com/acme"))
        self.assertTrue(is_social_host("instagram.com/acme"))
        self.assertTrue(is_social_host("https://linktr.ee/acme"))
        self.assertFalse(is_social_host("https://acme.ng"))

    def test_normalize_url(self):
        self.assertEqual(normalize_url("acme.ng"), "https://acme.ng")
        self.assertEqual(normalize_url(" http://acme.ng "), "http://acme.ng")
        self.assertEqual(normalize_url(""), "")

    def test_copyright_and_builder(self):
        self.assertEqual(latest_copyright_year("<footer>© 2016 Acme</footer>"), 2016)
        self.assertEqual(latest_copyright_year("Copyright 2014 - 2019 Acme"), 2019)
        self.assertIsNone(latest_copyright_year("<p>no year</p>"))
        self.assertEqual(detect_builder('<img src="https://static.wixstatic.com/a.png">'), "wix")

    def test_email_extraction_filters_junk(self):
        html = ('<a href="mailto:info@acme.ng?subject=Hi">mail</a> '
                '<p>sales@acme.ng and logo@2x.png and x@sentry.io</p>')
        self.assertEqual(contacts.extract_emails(html), ["info@acme.ng", "sales@acme.ng"])

    def test_socials_and_whatsapp(self):
        html = ('<a href="https://www.facebook.com/acmeng">f</a>'
                '<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>'
                '<a href="https://wa.me/2348031234567?text=hi">wa</a>')
        self.assertEqual(contacts.extract_socials(html)["facebook"], "https://www.facebook.com/acmeng")
        self.assertEqual(contacts.extract_whatsapp(html), "2348031234567")


class PlacesTests(unittest.TestCase):
    def test_query_building(self):
        qs = google_places.build_queries(["estate agent"], "Lagos", ["Ikeja", "Lekki"])
        self.assertEqual(qs, ["estate agent in Ikeja, Lagos", "estate agent in Lekki, Lagos"])
        self.assertEqual(google_places.build_queries(["x"], "Abuja", None), ["x in Abuja"])

    def test_estimate_is_upper_bound(self):
        self.assertEqual(google_places.estimate_requests(10), 30)

    def test_requires_key(self):
        with self.assertRaises(google_places.PlacesError):
            google_places.GooglePlaces("", memory_db(), 10, 10)

    def test_cap_blocks_before_any_request(self):
        conn = memory_db()
        gp = google_places.GooglePlaces("key", conn, max_requests=0, max_requests_per_day=10)
        with self.assertRaises(google_places.SpendCapReached):
            gp._post({"textQuery": "x"})
        self.assertEqual(db.usage_today(conn, google_places.PROVIDER), 0)

    def test_daily_cap_uses_ledger(self):
        conn = memory_db()
        db.record_usage(conn, google_places.PROVIDER, google_places.SKU, 5)
        gp = google_places.GooglePlaces("key", conn, max_requests=10, max_requests_per_day=5)
        with self.assertRaises(google_places.SpendCapReached):
            gp._post({"textQuery": "x"})

    def test_closed_places_are_dropped(self):
        place = {"id": "1", "displayName": {"text": "Gone Ltd"}, "businessStatus": "CLOSED_PERMANENTLY"}
        self.assertIsNone(google_places.GooglePlaces._to_lead(place, "n", "Lagos", "Nigeria"))
        ok = {"id": "2", "displayName": {"text": "Open Ltd"}, "nationalPhoneNumber": "0803 123 4567",
              "rating": 4.1, "userRatingCount": 9, "location": {"latitude": 6.5, "longitude": 3.3}}
        lead = google_places.GooglePlaces._to_lead(ok, "n", "Lagos", "Nigeria")
        self.assertEqual((lead.name, lead.phone, lead.lat), ("Open Ltd", "+2348031234567", 6.5))


if __name__ == "__main__":
    unittest.main()
