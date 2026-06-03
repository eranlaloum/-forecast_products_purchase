"""
Select the best product from a list of candidates.

Rules:
  1. Compute effective_unit_price for each candidate (including promotions).
  2. Filter obviously irrelevant results by name similarity.
  3. Return the cheapest by effective unit price.
  4. If a promotion bundle is cheaper per unit, prefer it even if qty > requested.
"""
from __future__ import annotations
import re
import logging
from typing import Optional
from .models import WoltProduct, ShoppingItem
from .unit_parser import parse_promotion, effective_unit_price, optimal_quantity_for_promotion

logger = logging.getLogger(__name__)

# Hebrew stop-words to ignore when comparing names
_STOP = {
    "של", "את", "עם", "על", "לא", "כן", "גם", "רק", "כל", "מה", "יש",
    "אין", "כי", "אם", "זה", "זו", "אבל", "בשביל", "עוד", "ממש",
}


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[א-ת\w]+", text.lower())
    return {t for t in tokens if t not in _STOP and len(t) > 1}


def _similarity(query_tokens: set[str], product_name: str) -> float:
    """Jaccard-like similarity between query tokens and product name tokens."""
    prod_tokens = _tokenize(product_name)
    if not query_tokens or not prod_tokens:
        return 0.0
    intersection = query_tokens & prod_tokens
    union = query_tokens | prod_tokens
    return len(intersection) / len(union)


def select_best_product(
    candidates: list[WoltProduct],
    shopping_item: ShoppingItem,
    min_relevance: float = 0.25,
) -> tuple[Optional[WoltProduct], int, list[WoltProduct]]:
    """
    Choose the best product and quantity to add.

    Returns:
        (best_product, quantity_to_add, flagged_alternatives)
        best_product=None means nothing relevant found.
        flagged_alternatives is non-empty when the choice is uncertain.
    """
    if not candidates:
        return None, 0, []

    query_tokens = _tokenize(shopping_item.name)

    # Score each candidate
    scored: list[tuple[float, float, WoltProduct]] = []
    for product in candidates:
        sim = _similarity(query_tokens, product.name)
        if sim < min_relevance:
            logger.debug("Skipping '%s' (similarity %.2f < %.2f)", product.name, sim, min_relevance)
            continue
        promo = parse_promotion(product.promotion_text)
        eup = effective_unit_price(product.price, product.quantity_in_package, product.unit, promo)
        scored.append((sim, eup, product))

    if not scored:
        return None, 0, []

    # Sort by effective unit price ascending (cheapest first), then similarity desc as tiebreak
    scored.sort(key=lambda x: (x[1], -x[0]))

    best_sim, best_eup, best = scored[0]

    # Flag for review if top two options have similar relevance but very different types
    flagged: list[WoltProduct] = []
    if len(scored) > 1:
        second_sim, second_eup, second = scored[1]
        # If the second option is nearly as cheap and has similar relevance, flag it
        if second_sim >= best_sim * 0.8 and second_eup <= best_eup * 1.2:
            flagged.append(second)

    # Compute how many units to actually add
    promo = parse_promotion(best.promotion_text)
    qty_to_add = optimal_quantity_for_promotion(shopping_item.requested_quantity, promo)

    logger.info(
        "Selected '%s' (sim=%.2f, eup=%.2f, qty=%d%s)",
        best.name, best_sim, best_eup, qty_to_add,
        f", promo={best.promotion_text}" if best.promotion_text else "",
    )

    return best, qty_to_add, flagged
