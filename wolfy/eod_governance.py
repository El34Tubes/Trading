#!/usr/bin/env python3
"""Shared Hermes-EOD governance text for Wolfy context scripts.

This module deliberately contains no secrets, broker integration, or market-data
fetching. It centralizes the non-negotiable prompt boundary adopted from
/root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md so every
agent context advertises the same rules before the LLM reasons.
"""
from __future__ import annotations

EOD_BOOTSTRAP = "/root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md"
EOD_PLAN = "/root/.hermes/wolfy/HERMES_EOD_IMPLEMENTATION_PLAN.md"


def governance_lines() -> list[str]:
    return [
        "Hermes-EOD governance: source=/root/.hermes/cache/documents/doc_26a12d1486bd_hermes_bootstrap.md plan=/root/.hermes/wolfy/HERMES_EOD_IMPLEMENTATION_PLAN.md",
        "EOD ONLY: actionable decisions use closing data only and are for next-session human review/execution.",
        "No intraday actionable recommendations: intraday or scanner observations are diagnostics/leads only until converted into deterministic EOD signals.",
        "No auto-execution: no broker authority, no banking, no money movement; humans place every order.",
        "LLM interprets deterministic signals: numeric edge, features, ranks, triggers, stops, sizing, and risk breakers must trace to deterministic data rows or cited filings; missing data stays missing.",
        "FACT vs JUDGMENT: separate measured/filed facts from analyst inference in every rationale/report.",
        "Approved-strategy gate: capital/paper-trade proposals require an approved strategy row plus deterministic signal/setup support; otherwise label research-only/watchlist/no-trade.",
        "Prefer no setup tonight over forced ideas; risk circuit breakers are absolute and must not be reasoned around.",
    ]


def governance_text() -> str:
    return "\n".join(governance_lines())


def print_eod_governance() -> None:
    print("EOD_GOVERNANCE")
    for line in governance_lines():
        print(line)
