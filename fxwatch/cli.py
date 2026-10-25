"""Command-line entry point: `python -m fxwatch <command>` (or `fxwatch <command>`)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from fxwatch.config import generate_secret_key, get_settings
from fxwatch.db import upgrade
from fxwatch.logs import configure_logging
from fxwatch.notify.mailer import OutgoingEmail, get_mailer
from fxwatch.sources import SOURCE_INFO
from fxwatch.worker import jobs


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fxwatch", description="FX Watch worker and admin tools")
    sub = parser.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db", help="database management")
    db.add_argument("action", choices=["upgrade"])

    sub.add_parser("run-once", help="fetch, evaluate alerts, send emails, tidy up (for cron)")
    sub.add_parser("serve", help="run the worker forever (Docker/VPS)")

    fetch = sub.add_parser("fetch", help="fetch the latest rates")
    fetch.add_argument("--source", choices=sorted(SOURCE_INFO))

    bf = sub.add_parser("backfill", help="load historical rates")
    bf.add_argument("--days", type=int, default=365)
    bf.add_argument("--source", choices=sorted(SOURCE_INFO))

    sub.add_parser("evaluate", help="evaluate alerts against stored rates")
    sub.add_parser("deliver", help="send queued emails")

    test = sub.add_parser("send-test-email", help="check SMTP settings")
    test.add_argument("to")

    sub.add_parser("check-config", help="validate settings for production")
    sub.add_parser("generate-secret", help="print a random SECRET_KEY")

    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if args.command == "generate-secret":
        print(generate_secret_key())
        return 0
    if args.command == "check-config":
        problems = settings.validate_for_production()
        for p in problems:
            print(f"✗ {p}")
        if not problems:
            print("✓ configuration looks production-ready")
        return 1 if problems else 0
    if args.command == "send-test-email":
        get_mailer(settings).send(
            OutgoingEmail(
                to=args.to,
                subject=f"{settings.app_name} test email",
                text="If you can read this, email delivery is configured correctly.",
            )
        )
        print(f"sent via {settings.mail_backend} backend")
        return 0

    if args.command == "db":
        upgrade(settings.database_url)
        print("database is up to date")
        return 0

    upgrade(settings.database_url)
    if args.command == "run-once":
        report = jobs.run_once(settings, migrate=False)
        _print(asdict(report))
        return 2 if report.all_sources_failed else 0
    if args.command == "serve":
        jobs.serve(settings)
        return 0
    if args.command == "fetch":
        _print([asdict(r) for r in jobs.fetch_all(settings, only=args.source)])
    elif args.command == "backfill":
        _print([asdict(r) for r in jobs.backfill(settings, args.days, only=args.source)])
    elif args.command == "evaluate":
        _print(jobs.evaluate(settings))
    elif args.command == "deliver":
        _print(asdict(jobs.deliver(settings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
