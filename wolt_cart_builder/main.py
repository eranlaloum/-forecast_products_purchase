"""
CLI entry point for the Wolt Market cart builder.

Usage examples:
  python -m wolt_cart_builder --list shopping_list.txt
  python -m wolt_cart_builder --list shopping_list.txt --config config.json
  python -m wolt_cart_builder --list shopping_list.txt --dry-run
  python -m wolt_cart_builder --list shopping_list.txt --store-url "https://wolt.com/he/isr/tel-aviv/market/wolt-market-tel-aviv"
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import Config
from .cart_builder import CartBuilder
from .shopping_list_parser import parse_shopping_list_file, parse_shopping_list
from .summary import print_summary, save_summary


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wolt_cart_builder",
        description="Build a Wolt Market cart from a grocery shopping list.",
    )
    p.add_argument(
        "--list", "-l",
        required=True,
        metavar="FILE",
        help="Path to the shopping list text file (Hebrew or English).",
    )
    p.add_argument(
        "--config", "-c",
        metavar="FILE",
        help="Path to a JSON config file (see config_example.json).",
    )
    p.add_argument(
        "--store-url",
        help="Wolt Market store URL (overrides config).",
    )
    p.add_argument(
        "--output-dir",
        default="wolt_output",
        help="Directory to save the cart summary Markdown file (default: wolt_output/).",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no visible window).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and select products but do NOT add them to cart.",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging.",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    # Load config
    if args.config:
        config = Config.from_file(args.config)
    else:
        config = Config()

    # Apply CLI overrides
    if args.store_url:
        config.store_url = args.store_url
    if args.headless:
        config.headless = True
    if args.dry_run:
        config.dry_run = True
    config.output_dir = Path(args.output_dir)

    # Parse shopping list
    shopping_list = parse_shopping_list_file(args.list)
    if not shopping_list:
        print("ERROR: Shopping list is empty.", file=sys.stderr)
        return 1

    print(f"\n🛒 Wolt Cart Builder starting…")
    print(f"   Store  : {config.store_url}")
    print(f"   Items  : {len(shopping_list)}")
    print(f"   Dry run: {config.dry_run}")
    print()

    builder = CartBuilder(config)
    summary = await builder.build_cart(shopping_list)

    print_summary(summary)

    summary_path = save_summary(summary, config.output_dir)
    print(f"📄 Summary saved to: {summary_path}")

    return 0 if not summary.missing_items else 1


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=level,
    )

    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
