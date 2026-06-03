"""
Main orchestration: iterate the shopping list, search Wolt, select best
products, add to cart, and collect results.

SAFETY: Never places an order. Stops after cart is built.
"""
from __future__ import annotations
import asyncio
import logging
from pathlib import Path

from .config import Config
from .models import ShoppingItem, WoltProduct, CartEntry, CartStatus, CartSummary
from .product_selector import select_best_product
from .unit_parser import parse_promotion, effective_unit_price
from .wolt_browser import WoltBrowser

logger = logging.getLogger(__name__)


class CartBuilder:
    """Orchestrates the end-to-end cart building process."""

    def __init__(self, config: Config):
        self.config = config
        self._browser = WoltBrowser(config)

    async def build_cart(self, items: list[ShoppingItem]) -> CartSummary:
        """
        Process every item in the shopping list and return a CartSummary.
        After this method returns, the cart is ready for manual checkout.
        """
        summary = CartSummary()

        await self._browser.start()
        try:
            await self._browser.navigate_to_store()

            for item in items:
                entry = await self._process_item(item)
                summary.entries.append(entry)
                # Brief pause between items to avoid rate-limiting
                await asyncio.sleep(1.2)

            # Calculate total estimated cost
            for entry in summary.added_items:
                if entry.selected_product:
                    p = entry.selected_product
                    promo = parse_promotion(p.promotion_text)
                    if promo and promo["type"] == "n_for_price" and p.promotion_quantity:
                        groups = entry.quantity_added // p.promotion_quantity
                        remainder = entry.quantity_added % p.promotion_quantity
                        summary.total_estimated_cost += (
                            groups * p.promotion_price
                            + remainder * p.price
                        )
                    else:
                        summary.total_estimated_cost += p.price * entry.quantity_added

        finally:
            await self._browser.close()

        return summary

    async def _process_item(self, item: ShoppingItem) -> CartEntry:
        logger.info("Processing: '%s' (qty=%d)", item.name, item.requested_quantity)

        try:
            candidates = await self._browser.search_products(item.name)
        except Exception as e:
            logger.error("Search failed for '%s': %s", item.name, e)
            return CartEntry(
                shopping_item=item,
                status=CartStatus.NOT_FOUND,
                notes=f"Search error: {e}",
            )

        best, qty_to_add, flagged = select_best_product(
            candidates, item, self.config.min_relevance_score
        )

        if best is None:
            logger.info("No relevant product found for '%s'", item.name)
            return CartEntry(
                shopping_item=item,
                status=CartStatus.NOT_FOUND,
                notes="No matching product found in search results.",
            )

        # Determine status
        if flagged:
            status = CartStatus.NEEDS_REVIEW
            notes = (
                f"Selected best option. Alternative: '{flagged[0].name}' "
                f"({flagged[0].price:.2f}₪). Please verify."
            )
        elif best.promotion_text:
            status = CartStatus.PROMOTION_APPLIED
            notes = f"Promotion applied: {best.promotion_text}"
        else:
            status = CartStatus.ADDED
            notes = ""

        if qty_to_add > item.requested_quantity:
            promo = parse_promotion(best.promotion_text)
            notes += (
                f" Quantity increased {item.requested_quantity}→{qty_to_add} "
                f"to benefit from promotion."
            )

        # Add to cart (or dry-run log)
        added = await self._browser.add_to_cart(
            product_name=best.name,
            quantity=qty_to_add,
            dry_run=self.config.dry_run,
        )

        if not added:
            # Couldn't click the add button; flag for manual review
            return CartEntry(
                shopping_item=item,
                status=CartStatus.NEEDS_REVIEW,
                selected_product=best,
                quantity_added=0,
                notes="Could not add to cart automatically. Please add manually.",
                alternatives=flagged,
            )

        return CartEntry(
            shopping_item=item,
            status=status,
            selected_product=best,
            quantity_added=qty_to_add,
            notes=notes.strip(),
            alternatives=flagged,
        )
