"""Command-line interface: ``biothings-pulse <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import get_settings


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    reload_kwargs = {}
    if args.reload:
        # Watch only the package source. At runtime the app git-clones plugin
        # repos (full of .py files) and writes a SQLite DB into the cache dir;
        # watching the whole cwd would see those and reload endlessly.
        from pathlib import Path

        reload_kwargs = {
            "reload": True,
            "reload_dirs": [str(Path(__file__).resolve().parent)],
            "reload_excludes": ["*.db", "*.sqlite*"],
        }
    uvicorn.run(
        "biothings_pulse.main:app",
        host=args.host or settings.host,
        port=args.port or settings.port,
        **reload_kwargs,
    )
    return 0


def _build_service():
    from .service import PulseService

    return PulseService(get_settings())


def _cmd_sync(args: argparse.Namespace) -> int:
    svc = _build_service()
    count = svc.sync_and_discover()
    print(f"Discovered {count} plugins across configured repos.")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    svc = _build_service()
    svc.sync_and_discover()
    for ref in svc.list_catalog():
        print(f"{ref.plugin_type:9s} {ref.key}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    svc = _build_service()
    svc.sync_and_discover()
    state = svc.check_source(args.repo, args.plugin)
    if state is None:
        print(f"Unknown source: {args.repo}/{args.plugin}", file=sys.stderr)
        return 1
    print(json.dumps(state.model_dump(mode="json"), indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(prog="biothings-pulse")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the API server")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_sync = sub.add_parser("sync", help="Sync repos and rebuild the catalog")
    p_sync.set_defaults(func=_cmd_sync)

    p_list = sub.add_parser("list", help="List discovered plugins")
    p_list.set_defaults(func=_cmd_list)

    p_check = sub.add_parser("check", help="Check a single source")
    p_check.add_argument("repo")
    p_check.add_argument("plugin")
    p_check.set_defaults(func=_cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
