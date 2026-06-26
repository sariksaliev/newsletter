"""CLI entry points."""

import argparse
import asyncio


def main():
    parser = argparse.ArgumentParser(description="TG Outreach Platform CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Start API server + scheduler")
    sub.add_parser("seed", help="Seed default config")
    sub.add_parser("listener", help="Start inbound message listener")
    sub.add_parser("test", help="Run smoke tests (notify, API, dialog)")

    args = parser.parse_args()

    if args.command == "serve":
        from src.main import main as serve_main
        serve_main()
    elif args.command == "seed":
        from scripts.seed import seed
        asyncio.run(seed())
    elif args.command == "listener":
        from src.workers.inbound_listener import run_listener
        asyncio.run(run_listener())
    elif args.command == "test":
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent))
        from scripts.smoke_test import main as test_main
        raise SystemExit(asyncio.run(test_main()))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
