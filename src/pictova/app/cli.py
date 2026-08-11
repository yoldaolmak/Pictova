"""Canonical CLI entrypoint for VIL."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from typing import Any, Dict

from src.pictova.app.health import run_health_check
from src.pictova.app.jobs import run_attach_job
from src.pictova.app.api import plan_attach, process_attach
from src.pictova.app.server import serve
from src.pictova.providers.wordpress import fetch_post_context, guard_post_media, reset_post_media, resolve_post_site


@contextlib.contextmanager
def _stdout_reserved_for_json():
    """Keep stdout clean so the printed result stays parseable JSON.

    Image processing and the legacy orchestrator report progress with plain
    print(), which lands on stdout and interleaves with the result document —
    `pictova attach ... | jq` failed on its own output. Progress belongs on
    stderr; stdout carries the machine-readable contract alone.
    """
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        yield real_stdout
    finally:
        sys.stdout = real_stdout


def _print_json(payload: Dict[str, Any], stream: Any = None) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream or sys.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pictova")
    sub = parser.add_subparsers(dest="command", required=True)

    attach = sub.add_parser("attach")
    attach.add_argument("--site", default="auto")
    attach.add_argument("--post", type=int, required=True)
    attach.add_argument("--count", type=int, default=4)
    attach.add_argument("--name")
    attach.add_argument(
        "--source",
        default="semantic",
        choices=["semantic", "auto", "vil", "local", "unsplash", "deposit", "wikimedia"],
    )
    attach.add_argument("--query")
    attach.add_argument("--location-query")
    attach.add_argument("--content-filter")
    attach.add_argument("--lang", default="tr")
    attach.add_argument("--people-first", action="store_true")
    attach.add_argument("--engine", default="native", choices=["legacy", "native"])
    attach.add_argument("--heading", help="Force all images after this heading text")
    attach.add_argument("--heading-level", type=int, default=0, help="Heading level (2 or 3)")

    review = sub.add_parser("review")
    review.add_argument("--site", default="auto")
    review.add_argument("--post", type=int, required=True)

    guard = sub.add_parser("guard")
    guard.add_argument("--site", default="auto")
    guard.add_argument("--post", type=int, required=True)
    guard_mode = guard.add_mutually_exclusive_group()
    guard_mode.add_argument("--repair", action="store_true")
    guard_mode.add_argument("--reposition", action="store_true", help="Reinsert managed media at manifest headings")
    guard_mode.add_argument("--adopt", action="store_true")
    guard_mode.add_argument("--reset", action="store_true", help="Remove only Pictova-managed media blocks")
    guard.add_argument("--media-id", dest="media_ids", action="append", type=int)

    plan = sub.add_parser("plan")
    plan.add_argument("--site", default="auto")
    plan.add_argument("--post", type=int, required=True)
    plan.add_argument("--count", type=int, default=4)
    plan.add_argument("--name")
    plan.add_argument(
        "--source",
        default="semantic",
        choices=["semantic", "auto", "vil", "local", "unsplash", "deposit", "wikimedia"],
    )
    plan.add_argument("--query")
    plan.add_argument("--location-query")
    plan.add_argument("--content-filter")
    plan.add_argument("--lang", default="tr")
    plan.add_argument("--people-first", action="store_true")
    plan.add_argument("--engine", default="native", choices=["legacy", "native"])
    plan.add_argument("--heading", help="Force all images after this heading text")
    plan.add_argument("--heading-level", type=int, default=0, help="Heading level (2 or 3)")

    process = sub.add_parser("process")
    process.add_argument("--site", default="auto")
    process.add_argument("--post", type=int, required=True)
    process.add_argument("--count", type=int, default=4)
    process.add_argument("--name")
    process.add_argument(
        "--source",
        default="semantic",
        choices=["semantic", "auto", "vil", "local", "unsplash", "deposit", "wikimedia"],
    )
    process.add_argument("--query")
    process.add_argument("--location-query")
    process.add_argument("--content-filter")
    process.add_argument("--lang", default="tr")
    process.add_argument("--people-first", action="store_true")
    process.add_argument("--engine", default="native", choices=["legacy", "native"])
    process.add_argument("--heading", help="Force all images after this heading text")
    process.add_argument("--heading-level", type=int, default=0, help="Heading level (2 or 3)")

    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8040)

    health_cmd = sub.add_parser("health")
    health_cmd.add_argument(
        "--verify-upload", action="store_true",
        help="Yayın yolunu gerçekten dene: 1x1 PNG yükleyip hemen siler",
    )
    return parser


def _attach_args_to_payload(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "site": args.site,
        "post_id": args.post,
        "count": args.count,
        "name": args.name,
        "source": args.source,
        "query": args.query,
        "location_query": args.location_query,
        "content_filter": args.content_filter,
        "language": args.lang,
        "people_first": args.people_first,
        "engine": getattr(args, "engine", "native"),
        "heading": getattr(args, "heading", None),
        "heading_level": getattr(args, "heading_level", 0) or 0,
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    with _stdout_reserved_for_json() as out:
        return _dispatch(args, parser, out)


def _dispatch(args, parser, out) -> int:

    if args.command == "attach":
        try:
            result = run_attach_job(**_attach_args_to_payload(args))
        except Exception as exc:
            result = {"command": "attach", "status": "failed", "warnings": [str(exc)]}
        _print_json(result, out)
        return 0 if result.get("status") in {"success", "local"} else 1

    if args.command == "review":
        try:
            if args.site == "auto":
                site, post_context = resolve_post_site(args.post, site=args.site)
            else:
                site, post_context = args.site, fetch_post_context(args.post, site=args.site)
            result = {
                "command": "review",
                "status": "success",
                "site": site,
                "post_context": post_context,
            }
        except Exception as exc:
            result = {
                "command": "review",
                "status": "failed",
                "post_context": {},
                "warnings": [str(exc)],
            }
        _print_json(result, out)
        return 0 if result["status"] == "success" else 1

    if args.command == "guard":
        try:
            site, _ = resolve_post_site(args.post, site=args.site)
        except Exception as exc:
            _print_json({"command": "guard", "status": "failed", "warnings": [str(exc)]}, out)
            return 1
        if args.reset:
            reset = reset_post_media(args.post, site=site)
            result = {
                "command": "guard",
                "mode": "reset",
                "status": "success" if reset.get("success") else "failed",
                "site": site,
                "post_id": args.post,
                **reset,
            }
        else:
            result = guard_post_media(
                args.post,
                site=site,
                repair=args.repair,
                reposition=args.reposition,
                adopt=args.adopt,
                media_ids=args.media_ids,
            )
        _print_json(result, out)
        return 0 if result.get("status") == "success" else 1

    if args.command == "plan":
        result = plan_attach(_attach_args_to_payload(args))
        _print_json(result, out)
        return 0 if result.get("status") == "success" else 1

    if args.command == "process":
        result = process_attach(_attach_args_to_payload(args))
        _print_json(result, out)
        return 0 if result.get("status") == "success" else 1

    if args.command == "health":
        result = run_health_check(verify_upload=getattr(args, "verify_upload", False))
        _print_json(result, out)
        return 0 if result.get("status") == "ok" else 1

    if args.command == "serve":
        server = serve(host=args.host, port=args.port)
        try:
            _print_json(
                {
                    "command": "serve",
                    "status": "ok",
                    "host": args.host,
                    "port": args.port,
                }
            )
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
