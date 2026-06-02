# Wolfy/Mike triage: include default-profile cron context

Session date: 2026-06-01

## Lesson
Mike runs under the `mike` profile, whose own cron list may legitimately be empty, while Wolfy production jobs live under the `default` profile and some worker jobs run under `clerky`/`yang`. A Mike triage pre-run script that only prints `hermes cron list` can mislead the agent into thinking there are no scheduled jobs.

## Durable fix pattern
For Mike/Wolfy environment triage scripts, include both:

```bash
hermes cron list
hermes --profile default cron list --all
```

Use a larger output cap for the default-profile listing because it carries the production job names, scripts, last-run status, and next-run times.

If a job is profile-scoped, verify the relevant worker profile explicitly as well:

```bash
hermes --profile clerky cron list --all
hermes --profile yang cron list --all
hermes --profile mike cron list --all
```

## What was changed in this session
The Mike triage context script was updated to print:

- `mike cron list` using the active Mike profile
- `default cron list` via `hermes --profile default cron list --all`

The updated wrapper was synchronized to:

- `/root/.hermes/wolfy/mike_environment_triage_context.py`
- `/root/.hermes/scripts/mike_environment_triage_context.py`
- `/root/.hermes/profiles/mike/scripts/mike_environment_triage_context.py`

Verification showed default-profile production jobs were active and healthy; the active Mike profile still correctly had no direct scheduled jobs.
