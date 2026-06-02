#!/usr/bin/env python3
"""Tests for Wolfy's recommendation logger."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from recommendation_logger import log_recommendation, ensure_recommendations_table


class RecommendationLoggerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "wolfy-test.db"
        ensure_recommendations_table(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch_one(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute("SELECT * FROM recommendations").fetchone()
            return dict(row) if row else None
        finally:
            con.close()

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
            "jonah_refs": ["strategy_rules:Every actionable idea needs invalidation", "knowledge_notes:Minervini risk discipline"],
        }

    def test_complete_actionable_idea_is_inserted_pending_review_only(self):
        result = log_recommendation(self.db_path, self.complete_idea())

        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(result["missing_fields"], [])
        row = self.fetch_one()
        self.assertEqual(row["ticker"], "MSFT")
        self.assertEqual(row["action"], "buy")
        self.assertEqual(row["recommendation_type"], "equity")
        self.assertEqual(row["status"], "pending_review")
        self.assertEqual(row["entry_trigger"], "Buy only on reclaim of prior day's high above 425.")
        self.assertEqual(row["stop"], "Close below 410 invalidates the setup.")
        self.assertEqual(row["target"], "First trim near 455; exit if momentum stalls below target.")
        notes = json.loads(row["notes"])
        self.assertEqual(notes["robinhood_assumption"], "Robinhood-listed U.S. large-cap common stock")
        self.assertEqual(notes["risk_notes"], "Earnings date must be checked before entry; use stop; no averaging down.")
        self.assertEqual(notes["jonah_refs"], ["strategy_rules:Every actionable idea needs invalidation", "knowledge_notes:Minervini risk discipline"])

    def test_incomplete_idea_is_watchlist_only_with_missing_field_notes(self):
        idea = self.complete_idea()
        idea.pop("stop_invalidation")
        idea.pop("risk_reward")
        idea.pop("jonah_refs")

        result = log_recommendation(self.db_path, idea)

        self.assertEqual(result["status"], "watching")
        self.assertEqual(result["classification"], "watchlist_only")
        self.assertEqual(result["missing_fields"], ["stop_invalidation", "risk_reward", "jonah_refs"])
        row = self.fetch_one()
        self.assertEqual(row["status"], "watching")
        notes = json.loads(row["notes"])
        self.assertFalse(notes["actionable"])
        self.assertEqual(notes["missing_fields"], ["stop_invalidation", "risk_reward", "jonah_refs"])

    def test_short_or_foreign_actions_are_forced_watchlist_only(self):
        idea = self.complete_idea()
        idea["action"] = "short"
        idea["ticker"] = "BABA"
        idea["robinhood_assumption"] = "Chinese ADR; foreign government-interference risk"

        result = log_recommendation(self.db_path, idea)

        self.assertEqual(result["status"], "watching")
        self.assertIn("action must be long-only", result["risk_flags"])
        self.assertIn("foreign/manipulation/government-interference risk", result["risk_flags"])
        row = self.fetch_one()
        self.assertEqual(row["status"], "watching")
        notes = json.loads(row["notes"])
        self.assertEqual(notes["risk_flags"], result["risk_flags"])

    def test_missing_ticker_raises_without_inserting_garbage(self):
        idea = self.complete_idea()
        idea["ticker"] = ""

        with self.assertRaises(ValueError):
            log_recommendation(self.db_path, idea)

        self.assertIsNone(self.fetch_one())


if __name__ == "__main__":
    unittest.main()
