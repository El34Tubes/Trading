#!/usr/bin/env python3
"""CLI bridge for Wolfy/Jonah/Sentinel agent_runs and agent_tasks.

Cron prompts can call this after doing LLM work so Postgres reflects whether a
claimed task was completed or blocked. It intentionally prints simple KEY=VALUE
lines that are easy for agents and humans to copy.
"""
from __future__ import annotations

import argparse
import sys

from wolfy_agent_coordination import (
    DEFAULT_PG_DSN,
    block_task,
    claim_next_task,
    complete_task,
    connect,
    ensure_agent_task,
    finish_agent_run,
    stable_fingerprint,
    start_agent_run,
)


def cmd_run_start(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        run_id = start_agent_run(
            conn,
            agent_name=args.agent,
            role=args.role,
            job_id=args.job_id,
            task_id=args.task_id,
            summary=args.summary,
        )
    print(f"AGENT_RUN_ID={run_id}")
    return 0


def cmd_run_finish(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        finish_agent_run(
            conn,
            args.run_id,
            status=args.status,
            summary=args.summary,
            error_message=args.error_message,
            records_created=args.records_created,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
            estimated_cost=args.estimated_cost,
        )
    print(f"AGENT_RUN_FINISHED={args.run_id}")
    print(f"STATUS={args.status}")
    return 0


def cmd_task_ensure(args: argparse.Namespace) -> int:
    fingerprint = args.source_fingerprint or stable_fingerprint(args.agent, args.task_type, args.title, args.description or "")
    with connect(args.dsn) as conn:
        task = ensure_agent_task(
            conn,
            agent_name=args.agent,
            task_type=args.task_type,
            title=args.title,
            description=args.description,
            source_fingerprint=fingerprint,
            topic_tags=args.topic_tag,
            ticker_symbols=args.ticker,
            priority=args.priority,
        )
    print(f"AGENT_TASK_ID={task.id}")
    print(f"TASK_CREATED={str(task.created).lower()}")
    print(f"TASK_STATUS={task.status}")
    print(f"SOURCE_FINGERPRINT={fingerprint}")
    return 0


def cmd_task_claim(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        claim = claim_next_task(
            conn,
            agent_name=args.agent,
            task_type=args.task_type,
            claim_token=args.claim_token,
            source_fingerprint=args.source_fingerprint,
        )
    if claim is None:
        print("CLAIMED=false")
        return 2 if args.fail_if_none else 0
    print("CLAIMED=true")
    print(f"AGENT_TASK_ID={claim.id}")
    print(f"CLAIM_TOKEN={claim.claim_token}")
    print(f"SOURCE_FINGERPRINT={claim.source_fingerprint or ''}")
    return 0


def cmd_task_complete(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        complete_task(conn, args.task_id, summary=args.summary)
    print(f"AGENT_TASK_COMPLETED={args.task_id}")
    return 0


def cmd_task_block(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        block_task(conn, args.task_id, reason=args.reason)
    print(f"AGENT_TASK_BLOCKED={args.task_id}")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        if args.task_id is not None:
            complete_task(conn, args.task_id, summary=args.summary)
        if args.run_id is not None:
            finish_agent_run(
                conn,
                args.run_id,
                status=args.status,
                summary=args.summary,
                records_created=args.records_created,
                input_tokens=args.input_tokens,
                output_tokens=args.output_tokens,
                estimated_cost=args.estimated_cost,
            )
    if args.task_id is not None:
        print(f"AGENT_TASK_COMPLETED={args.task_id}")
    if args.run_id is not None:
        print(f"AGENT_RUN_FINISHED={args.run_id}")
    print(f"STATUS={args.status}")
    return 0


def cmd_block(args: argparse.Namespace) -> int:
    with connect(args.dsn) as conn:
        if args.task_id is not None:
            block_task(conn, args.task_id, reason=args.reason)
        if args.run_id is not None:
            finish_agent_run(conn, args.run_id, status="blocked", summary=args.reason, error_message=args.reason)
    if args.task_id is not None:
        print(f"AGENT_TASK_BLOCKED={args.task_id}")
    if args.run_id is not None:
        print(f"AGENT_RUN_FINISHED={args.run_id}")
    print("STATUS=blocked")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=DEFAULT_PG_DSN)
    sub = parser.add_subparsers(required=True)

    run_start = sub.add_parser("run-start")
    run_start.add_argument("--agent", required=True)
    run_start.add_argument("--role", required=True)
    run_start.add_argument("--job-id")
    run_start.add_argument("--task-id", type=int)
    run_start.add_argument("--summary")
    run_start.set_defaults(func=cmd_run_start)

    run_finish = sub.add_parser("run-finish")
    run_finish.add_argument("--run-id", required=True, type=int)
    run_finish.add_argument("--status", required=True, choices=["completed", "blocked", "failed", "started"])
    run_finish.add_argument("--summary")
    run_finish.add_argument("--error-message")
    run_finish.add_argument("--records-created", type=int)
    run_finish.add_argument("--input-tokens", type=int)
    run_finish.add_argument("--output-tokens", type=int)
    run_finish.add_argument("--estimated-cost", type=float)
    run_finish.set_defaults(func=cmd_run_finish)

    task_ensure = sub.add_parser("task-ensure")
    task_ensure.add_argument("--agent", required=True)
    task_ensure.add_argument("--task-type", required=True)
    task_ensure.add_argument("--title", required=True)
    task_ensure.add_argument("--description")
    task_ensure.add_argument("--source-fingerprint")
    task_ensure.add_argument("--topic-tag", action="append")
    task_ensure.add_argument("--ticker", action="append")
    task_ensure.add_argument("--priority", type=int, default=50)
    task_ensure.set_defaults(func=cmd_task_ensure)

    task_claim = sub.add_parser("task-claim")
    task_claim.add_argument("--agent", required=True)
    task_claim.add_argument("--task-type")
    task_claim.add_argument("--source-fingerprint")
    task_claim.add_argument("--claim-token")
    task_claim.add_argument("--fail-if-none", action="store_true")
    task_claim.set_defaults(func=cmd_task_claim)

    task_complete = sub.add_parser("task-complete")
    task_complete.add_argument("--task-id", required=True, type=int)
    task_complete.add_argument("--summary")
    task_complete.set_defaults(func=cmd_task_complete)

    task_block = sub.add_parser("task-block")
    task_block.add_argument("--task-id", required=True, type=int)
    task_block.add_argument("--reason", required=True)
    task_block.set_defaults(func=cmd_task_block)

    complete = sub.add_parser("complete")
    complete.add_argument("--run-id", type=int)
    complete.add_argument("--task-id", type=int)
    complete.add_argument("--status", default="completed", choices=["completed", "failed"])
    complete.add_argument("--summary", required=True)
    complete.add_argument("--records-created", type=int)
    complete.add_argument("--input-tokens", type=int)
    complete.add_argument("--output-tokens", type=int)
    complete.add_argument("--estimated-cost", type=float)
    complete.set_defaults(func=cmd_complete)

    block = sub.add_parser("block")
    block.add_argument("--run-id", type=int)
    block.add_argument("--task-id", type=int)
    block.add_argument("--reason", required=True)
    block.set_defaults(func=cmd_block)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
