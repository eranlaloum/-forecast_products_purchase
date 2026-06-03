"""
Generate and display the cart summary.

Output formats:
  - Rich table printed to the terminal
  - Markdown file saved to disk
"""
from __future__ import annotations
import datetime
from pathlib import Path
from .models import CartSummary, CartEntry, CartStatus, WoltProduct
from .unit_parser import parse_promotion, effective_unit_price


def _eup_str(product: WoltProduct) -> str:
    promo = parse_promotion(product.promotion_text)
    eup = effective_unit_price(
        product.price, product.quantity_in_package, product.unit, promo
    )
    return f"{eup:.2f}₪ / {product.display_unit}"


def _price_str(product: WoltProduct) -> str:
    if product.original_price and product.original_price != product.price:
        return f"~~{product.original_price:.2f}₪~~ → **{product.price:.2f}₪**"
    return f"{product.price:.2f}₪"


def build_markdown(summary: CartSummary) -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []

    lines.append(f"# 🛒 Wolt Market Cart Summary")
    lines.append(f"*Generated: {ts}*")
    lines.append("")

    # ── Added items ──────────────────────────────────────────────────────
    lines.append("## ✅ Items Added to Cart")
    lines.append("")
    if not summary.added_items:
        lines.append("_No items were added._")
    else:
        header = "| Requested | Product | Qty req. | Qty added | Brand | Price | Effective unit price | Promotion |"
        lines.append(header)
        lines.append("|---|---|---|---|---|---|---|---|")
        for entry in summary.added_items:
            p = entry.selected_product
            brand = p.brand or "—"
            promo = p.promotion_text or "—"
            row = (
                f"| {entry.shopping_item.name} "
                f"| {p.name} "
                f"| {entry.shopping_item.requested_quantity} "
                f"| {entry.quantity_added} "
                f"| {brand} "
                f"| {_price_str(p)} "
                f"| {_eup_str(p)} "
                f"| {promo} |"
            )
            lines.append(row)
            if entry.notes:
                lines.append(f"> ℹ️ {entry.notes}")

    lines.append("")

    # ── Needs review ─────────────────────────────────────────────────────
    if summary.review_items:
        lines.append("## ⚠️ Items That Require Manual Review")
        lines.append("")
        for entry in summary.review_items:
            lines.append(f"### {entry.shopping_item.name}")
            if entry.selected_product:
                p = entry.selected_product
                lines.append(f"- **Selected:** {p.name} ({_price_str(p)})")
                lines.append(f"- **Effective unit price:** {_eup_str(p)}")
            if entry.notes:
                lines.append(f"- **Note:** {entry.notes}")
            if entry.alternatives:
                alt = entry.alternatives[0]
                lines.append(f"- **Alternative:** {alt.name} ({_price_str(alt)}, eup: {_eup_str(alt)})")
            lines.append("")

    # ── Not found ────────────────────────────────────────────────────────
    if summary.missing_items:
        lines.append("## ❌ Items Not Found")
        lines.append("")
        for entry in summary.missing_items:
            lines.append(f"- **{entry.shopping_item.name}** (qty: {entry.shopping_item.requested_quantity})")
            if entry.notes:
                lines.append(f"  _{entry.notes}_")
        lines.append("")

    # ── Cost estimate ────────────────────────────────────────────────────
    lines.append("---")
    lines.append(f"**Estimated cart total:** {summary.total_estimated_cost:.2f}₪")
    lines.append("")
    lines.append(
        "> **IMPORTANT:** The cart is ready for your review. "
        "No order has been placed. Please review the cart in Wolt and place the order manually."
    )

    return "\n".join(lines)


def print_summary(summary: CartSummary) -> None:
    """Print a compact summary to stdout."""
    added = summary.added_items
    missing = summary.missing_items
    review = summary.review_items

    print("\n" + "=" * 60)
    print("  WOLT MARKET CART — READY FOR REVIEW")
    print("=" * 60)
    print(f"  ✅ Items added:        {len(added)}")
    print(f"  ⚠️  Needs review:       {len(review)}")
    print(f"  ❌ Not found:          {len(missing)}")
    print(f"  💰 Estimated total:    {summary.total_estimated_cost:.2f}₪")
    print("-" * 60)

    if added:
        print("\nADDED:")
        for e in added:
            p = e.selected_product
            promo = f"  [{p.promotion_text}]" if p.promotion_text else ""
            print(
                f"  {e.shopping_item.name:30s}  →  {p.name[:35]:35s}  "
                f"qty: {e.shopping_item.requested_quantity}→{e.quantity_added}  "
                f"{p.price:.2f}₪ (eup: {_eup_str(p)}){promo}"
            )

    if review:
        print("\nNEEDS REVIEW:")
        for e in review:
            p = e.selected_product
            name = p.name if p else "—"
            print(f"  {e.shopping_item.name:30s}  →  {name[:35]:35s}  {e.notes}")

    if missing:
        print("\nNOT FOUND:")
        for e in missing:
            print(f"  {e.shopping_item.name}")

    print("\n" + "=" * 60)
    print("  ACTION REQUIRED: Open Wolt, review your cart, and")
    print("  place the order manually. No order has been placed.")
    print("=" * 60 + "\n")


def save_summary(summary: CartSummary, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"cart_summary_{ts}.md"
    path.write_text(build_markdown(summary), encoding="utf-8")
    return path
