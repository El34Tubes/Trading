# Wolfy EOD P4 review-only blocker clearance (2026-06-15)

Context: Mike ops run found `t_1d40733f` blocked only on `review-required` after a worker handoff. The card was assigned to `default`, but the blocker was purely verification/review, which Mike is allowed to clear under the Wolfy ops playbook.

Safe clearance pattern used:

1. Inspect the card:
   ```bash
   hermes kanban --board wolfy show t_1d40733f
   ```
2. Rerun the exact non-destructive verification cited by the handoff plus a broader cheap local suite:
   ```bash
   cd /root/.hermes/wolfy
   python3 -m pytest test_eod_signals.py -q
   python3 -m pytest -q
   git -C /root/.hermes diff --check -- wolfy/eod_signals.py wolfy/test_eod_signals.py
   ```
   Observed results: `5 passed`, then `93 passed`, and `diff --check` clean.
3. Comment with real output; do not summarize without command evidence:
   ```bash
   hermes kanban --board wolfy comment t_1d40733f "Mike review cleared..."
   ```
4. Complete with the ID only; do not append a free-form summary to `complete`:
   ```bash
   hermes kanban --board wolfy complete t_1d40733f
   ```
5. Re-list and dispatch so newly-ready children actually start:
   ```bash
   hermes kanban --board wolfy list | grep -E 't_1d40733f|t_6c6c9a2d|blocked|ready|running'
   hermes kanban --board wolfy dispatch
   ```
   Result: child `t_6c6c9a2d` promoted/spawned under `clerky` and entered `running`.

Pitfalls:
- Treat `review-required` blockers differently from implementation blockers: if all cited tests/smokes pass and no destructive action is required, Mike can clear them even when the task is assigned to another profile.
- Always dispatch after clearing parent blockers; otherwise downstream ready work can sit idle until the next dispatcher tick.
- Do not claim market/trading conclusions from the test suite. This pattern only verifies code/ops gates and Kanban state.
