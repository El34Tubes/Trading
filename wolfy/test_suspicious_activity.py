#!/usr/bin/env python3
"""Tests for Wolfy's suspicious-activity detection layer."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from suspicious_activity import (
    ensure_suspicious_activity_tables,
    evaluate_recommendation_suspicion,
    evaluate_scanner_suspicion,
    persist_suspicious_flags,
)
from recommendation_logger import log_recommendation


class SuspiciousActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "wolfy-test.db"
        ensure_suspicious_activity_tables(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def complete_idea(self):
        return {
            "ticker": "MSFT",
            "action": "buy",
            "instrument_type": "equity",
            "robinhood_assumption": "Robinhood-listed U.S. large-cap common stock",
            "thesis": "AI/cloud compounder with constructive trend and liquid options chain.",
            "setup": "Pullback to rising 20-day moving average after breakout.",
            "entry_trigger": "Buy only on reclaim of prior day's high above 425.",
            "stop_invalidation": "Close below 410 invalidates the setup.",
            "target_exit": "First trim near 455; exit if momentum stalls below target.",
            "risk_reward": "2.5R",
            "confidence": "medium-high",
            "size_guidance": "Paper account: 8% notional, risk <= 0.75% of $5k.",
            "holding_period": "2-6 weeks",
            "risk_notes": "Earnings date must be checked before entry; use stop; no averaging down.",
            "jonah_refs": ["strategy_rules:Every actionable idea needs invalidation"],
        }

    def stored_flags(self, ticker="PUMP"):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute("SELECT * FROM suspicious_activity_flags WHERE ticker=? ORDER BY id", (ticker,))]
        finally:
            con.close()

    def test_scanner_low_float_volume_spike_without_catalyst_forces_veto(self):
        result = evaluate_scanner_suspicion(
            "PUMP",
            {
                "close": 4.25,
                "r5": 86,
                "r20": 155,
                "relative_volume": 18,
                "avg_volume": 350000,
                "float_shares": 8_000_000,
                "market_cap": 48_000_000,
                "catalyst_confirmed": False,
            },
        )

        flag_types = {flag["flag_type"] for flag in result["flags"]}
        self.assertIn("low_float_price_spike", flag_types)
        self.assertIn("abnormal_volume_without_catalyst", flag_types)
        self.assertEqual(result["recommended_action"], "veto")
        self.assertEqual(result["confidence_adjustment"], "veto")
        self.assertLessEqual(result["confidence_multiplier"], 0.25)

        inserted = persist_suspicious_flags(self.db_path, "scanner_result", "42", "PUMP", result)
        self.assertEqual(inserted, len(result["flags"]))
        rows = self.stored_flags()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_table"], "scanner_result")
        self.assertEqual(json.loads(rows[0]["evidence"])["ticker"], "PUMP")

    def test_recommendation_mentions_dilution_reverse_split_influencer_and_offshore_risk(self):
        idea = self.complete_idea()
        idea.update(
            {
                "ticker": "XYZ",
                "thesis": "Viral FinTwit pile-on says this Cayman microcap can squeeze after a reverse split.",
                "risk_notes": "Recent ATM offering and dilution history; offshore VIE structure; paid influencer promotion; bot-like cashtag velocity on $XYZ.",
                "social_context": "Influencer pile-on, bot-like cashtag velocity, paid Discord room promotion.",
                "corporate_actions": "1-for-40 reverse split last quarter; repeated offerings.",
            }
        )

        result = evaluate_recommendation_suspicion(idea)

        flag_types = {flag["flag_type"] for flag in result["flags"]}
        self.assertIn("reverse_split_history", flag_types)
        self.assertIn("dilution_or_offering_history", flag_types)
        self.assertIn("influencer_pile_on", flag_types)
        self.assertIn("bot_like_cashtag_velocity", flag_types)
        self.assertIn("offshore_or_opaque_risk", flag_types)
        self.assertEqual(result["recommended_action"], "veto")

    def test_insider_social_timing_conflict_downgrades_recommendation(self):
        idea = self.complete_idea()
        idea.update(
            {
                "ticker": "TIMR",
                "thesis": "Management Form 4 headline appeared after a sudden social-media pile-on.",
                "risk_notes": "Insider buying came after the cashtag started trending; insiders previously sold into promotion.",
                "social_context": "Paid influencer promotion began Monday; Form 4 insider buy headline circulated Tuesday.",
                "insider_context": "Insider buy timing conflicts with the social campaign and prior insider selling into promotion.",
            }
        )

        result = evaluate_recommendation_suspicion(idea)

        flag_types = {flag["flag_type"] for flag in result["flags"]}
        self.assertIn("insider_social_timing_conflict", flag_types)
        self.assertEqual(result["recommended_action"], "downgrade")
        self.assertEqual(result["confidence_adjustment"], "reduced")

    def test_logger_persists_suspicious_flags_and_downgrades_actionable_ticket(self):
        idea = self.complete_idea()
        idea.update(
            {
                "ticker": "PUMP",
                "confidence": "high",
                "risk_notes": "Low float; no confirmed catalyst; abnormal volume spike; insider selling into promotion.",
                "social_context": "Influencer pile-on and bot-like cashtag velocity around $PUMP.",
                "market_context": {"float_shares": 9_000_000, "relative_volume": 16, "r5": 75, "catalyst_confirmed": False},
            }
        )

        result = log_recommendation(self.db_path, idea)

        self.assertEqual(result["status"], "watching")
        self.assertIn("suspicious activity veto", result["risk_flags"])
        rows = self.stored_flags()
        self.assertGreaterEqual(len(rows), 3)
        row = self.stored_flags()[0]
        self.assertEqual(row["ticker"], "PUMP")
        rec = sqlite3.connect(self.db_path).execute("SELECT notes, confidence FROM recommendations").fetchone()
        notes = json.loads(rec[0])
        self.assertEqual(notes["suspicious_activity"]["recommended_action"], "veto")
        self.assertTrue(notes["suspicious_activity"]["flags"])
        self.assertIn("reduced", rec[1].lower())


if __name__ == "__main__":
    unittest.main()
