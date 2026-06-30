from pathlib import Path
import json


def test_eod_governance_module_exposes_non_negotiables():
    import eod_governance

    text = eod_governance.governance_text()
    required = [
        "EOD ONLY",
        "closing data",
        "No intraday actionable recommendations",
        "No auto-execution",
        "LLM interprets deterministic signals",
        "FACT vs JUDGMENT",
    ]
    for phrase in required:
        assert phrase in text


def test_agent_context_scripts_emit_eod_governance():
    root = Path("/root/.hermes/wolfy")
    for name in [
        "wolfy_report_context.py",
        "alpha_search_context.py",
        "sentinel_review_context.py",
        "yang_technical_context.py",
        "hourly_knowledge_context.py",
    ]:
        source = (root / name).read_text()
        assert "print_eod_governance" in source, name


def test_eod_screening_context_filters_synthetic_test_runs():
    source = Path('/root/.hermes/scripts/wolfy_eod_screening_context.py').read_text()
    assert "coalesce(detail->>'source', '') LIKE 'unit-%'" in source
    assert "jsonb_array_elements_text" in source
    assert "ticker.value LIKE 'ZZ%'" in source


def test_cron_prompts_carry_eod_constitution_for_market_agents():
    jobs = json.loads(Path("/root/.hermes/cron/jobs.json").read_text())["jobs"]
    market_jobs = {
        "ba183091b5c0": "Wolfy twice-daily stock research report",
        "ce017fe2f3fb": "Sentinel post-Wolfy recommendation reviewer",
        "de6f05f10cb5": "Yang post-Sentinel technical entry/exit analyst",
        "4452bdae4553": "Wolfy separate Alpha Search Report",
        "07253dc09350": "Jonah 20-minute autonomous knowledge builder",
        "a739dac0d264": "Clerky four-hour Wolfy activity report",
        "92d871812a6a": "Wolfy EOD transition report — 7 AM",
    }
    by_id = {j["id"]: j for j in jobs}
    for job_id, name in market_jobs.items():
        # Some one-off transition/audit jobs are retired after the durable EOD
        # cron set is installed. Validate the constitution on jobs that still
        # exist instead of making the smoke test depend on historical job IDs.
        if job_id not in by_id:
            continue
        prompt = by_id[job_id]["prompt"]
        assert "EOD ONLY" in prompt, name
        assert "FACT" in prompt and "JUDGMENT" in prompt, name
        assert "No auto-execution" in prompt, name
