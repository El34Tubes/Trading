#!/usr/bin/env python3
"""Tests for Wolfy's insider-buying alpha support layer."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from insider_buying import (
    assess_insider_transactions,
    ensure_insider_tables,
    parse_form4_xml,
    persist_insider_leads,
)


class InsiderBuyingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "wolfy-test.db"
        ensure_insider_tables(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_market_cluster_buy_creates_thesis_support_not_trigger(self):
        transactions = [
            {
                "ticker": "MSFT",
                "cik": "0000789019",
                "accession": "0000789019-26-000001",
                "filing_date": "2026-05-01",
                "transaction_date": "2026-04-29",
                "owner_name": "Jane CEO",
                "owner_title": "Chief Executive Officer",
                "officer_title": "CEO",
                "transaction_code": "P",
                "shares": 8000,
                "price": 425,
                "shares_owned_after": 40000,
                "security_title": "Common Stock",
            },
            {
                "ticker": "MSFT",
                "cik": "0000789019",
                "accession": "0000789019-26-000002",
                "filing_date": "2026-05-02",
                "transaction_date": "2026-04-30",
                "owner_name": "John CFO",
                "owner_title": "Chief Financial Officer",
                "officer_title": "CFO",
                "transaction_code": "P",
                "shares": 6000,
                "price": 420,
                "shares_owned_after": 18000,
                "security_title": "Common Stock",
            },
        ]

        assessment = assess_insider_transactions(
            "MSFT",
            transactions,
            market_context={"market_cap": 3_200_000_000_000, "avg_volume": 20_000_000, "float_shares": 7_400_000_000},
        )

        self.assertTrue(assessment["lead_qualified"])
        self.assertEqual(assessment["recommended_use"], "thesis_support_only")
        self.assertIn("open_market_purchase", assessment["positive_factors"])
        self.assertIn("cluster_buying", assessment["positive_factors"])
        self.assertNotIn("exercise_or_award", assessment["risk_flags"])
        self.assertGreaterEqual(assessment["score"], 70)

        inserted = persist_insider_leads(self.db_path, assessment)
        self.assertEqual(inserted["transactions_inserted"], 2)
        self.assertEqual(inserted["lead_id"], 1)
        row = sqlite3.connect(self.db_path).execute("SELECT status, recommended_use, evidence_json FROM insider_leads").fetchone()
        self.assertEqual(row[0], "qualified")
        self.assertEqual(row[1], "thesis_support_only")
        self.assertEqual(json.loads(row[2])["distinct_buyers"], 2)

    def test_sec_form4_xml_parser_extracts_non_derivative_transaction(self):
        xml = """<?xml version=\"1.0\"?>
        <ownershipDocument>
          <issuer><issuerCik>0000789019</issuerCik><issuerTradingSymbol>MSFT</issuerTradingSymbol></issuer>
          <reportingOwner>
            <reportingOwnerId><rptOwnerName>Jane CEO</rptOwnerName></reportingOwnerId>
            <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>Chief Executive Officer</officerTitle></reportingOwnerRelationship>
          </reportingOwner>
          <nonDerivativeTable>
            <nonDerivativeTransaction>
              <securityTitle><value>Common Stock</value></securityTitle>
              <transactionDate><value>2026-04-29</value></transactionDate>
              <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
              <transactionAmounts>
                <transactionShares><value>8000</value></transactionShares>
                <transactionPricePerShare><value>425.50</value></transactionPricePerShare>
              </transactionAmounts>
              <postTransactionAmounts><sharesOwnedFollowingTransaction><value>40000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
            </nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>
        """

        rows = parse_form4_xml(xml, accession="0000789019-26-000001", source_url="https://www.sec.gov/example")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], "MSFT")
        self.assertEqual(rows[0]["cik"], "0000789019")
        self.assertEqual(rows[0]["owner_name"], "Jane CEO")
        self.assertEqual(rows[0]["transaction_code"], "P")
        self.assertEqual(rows[0]["shares"], 8000)
        self.assertEqual(rows[0]["price"], 425.50)
        self.assertEqual(rows[0]["source_url"], "https://www.sec.gov/example")

    def test_awards_exercises_and_thin_microcap_force_reject(self):
        transactions = [
            {
                "ticker": "PUMP",
                "cik": "0000000001",
                "accession": "0000000001-26-000001",
                "filing_date": "2026-05-01",
                "transaction_date": "2026-04-29",
                "owner_name": "Promo Director",
                "owner_title": "Director",
                "transaction_code": "A",
                "shares": 100000,
                "price": 0,
                "shares_owned_after": 200000,
                "security_title": "Restricted Stock Unit",
            },
            {
                "ticker": "PUMP",
                "cik": "0000000001",
                "accession": "0000000001-26-000002",
                "filing_date": "2026-05-02",
                "transaction_date": "2026-04-30",
                "owner_name": "Option Officer",
                "owner_title": "Officer",
                "transaction_code": "M",
                "shares": 50000,
                "price": 1,
                "shares_owned_after": 50000,
                "security_title": "Derivative Option",
            },
        ]

        assessment = assess_insider_transactions(
            "PUMP",
            transactions,
            market_context={"market_cap": 45_000_000, "avg_volume": 180_000, "float_shares": 8_000_000, "recent_promotion": True},
        )

        self.assertFalse(assessment["lead_qualified"])
        self.assertEqual(assessment["status"], "rejected")
        self.assertIn("no_open_market_buys", assessment["risk_flags"])
        self.assertIn("exercise_or_award", assessment["risk_flags"])
        self.assertIn("thin_or_microcap_manipulation_risk", assessment["risk_flags"])
        self.assertLessEqual(assessment["score"], 20)


if __name__ == "__main__":
    unittest.main()
