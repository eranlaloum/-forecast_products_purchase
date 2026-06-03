"""
Parse product quantity, unit, and promotions from Hebrew/English product text.

Examples handled:
  "חלב תנובה 3% 1 ליטר"      → (1.0,   "liter",  None)
  "יוגורט 150 גרם"            → (150.0, "g",      None)
  "ביצים גדולות 12 יחידות"    → (12.0,  "unit",   None)
  "מים 6×1.5 ליטר"            → (9.0,   "liter",  None)   ← total
  "3 ב-15.90 ₪"               → (3,     "unit",   {"qty": 3, "price": 15.90})
  "2+1 חינם"                  → (3,     "unit",   {"qty_pay": 2, "qty_free": 1})
"""
from __future__ import annotations
import re
from typing import Optional

# ------------------------------------------------------------------
# Hebrew → canonical unit mapping
# ------------------------------------------------------------------
_UNIT_MAP: dict[str, str] = {
    # liters
    r"ליטר": "liter", r"ל'": "liter", r"ל\"": "liter", r"l\b": "liter",
    r"liter": "liter", r"litre": "liter",
    # ml
    r"מ\"ל": "ml", r"מיליליטר": "ml", r"ml\b": "ml",
    # kg
    r"קג": "kg", r"ק\"ג": "kg", r"קילוגרם": "kg", r"kg\b": "kg",
    # grams
    r"גרם": "g", r"ג'": "g", r"ג\"": "g", r"gr\b": "g", r"g\b": "g",
    # units
    r"יחידות": "unit", r"יחידה": "unit", r"יח'": "unit",
    r"יח\"": "unit", r"יח\b": "unit", r"units?\b": "unit",
    r"pack": "unit", r"חבילה": "unit",
}

# Multi-pack pattern: "6×1.5 ליטר" or "6*200 גרם"
_MULTIPACK = re.compile(
    r"(\d+)\s*[×x\*]\s*([\d.]+)\s*(" + "|".join(_UNIT_MAP.keys()) + r")",
    re.IGNORECASE | re.UNICODE,
)

# Single quantity+unit: "1.5 ליטר", "200 גרם"
_SINGLE_QU = re.compile(
    r"([\d.]+)\s*(" + "|".join(_UNIT_MAP.keys()) + r")",
    re.IGNORECASE | re.UNICODE,
)

# Promotion: "3 ב-15.90 ₪" or "3 ב15.90"
_PROMO_N_FOR_PRICE = re.compile(r"(\d+)\s*ב[-–]?\s*([\d.]+)", re.UNICODE)

# Promotion: "2+1" or "2+1 חינם"
_PROMO_BUY_GET = re.compile(r"(\d+)\s*\+\s*(\d+)(?:\s*חינם)?", re.UNICODE)

# Percentage discount: "10% הנחה"
_PROMO_PERCENT = re.compile(r"(\d+)%\s*הנחה", re.UNICODE)


def _match_unit(text: str) -> Optional[str]:
    for pattern, canonical in _UNIT_MAP.items():
        if re.search(pattern, text, re.IGNORECASE | re.UNICODE):
            return canonical
    return None


def parse_quantity_unit(product_name: str) -> tuple[float, str]:
    """
    Return (quantity, unit) extracted from a product name.
    Falls back to (1.0, 'unit') if nothing found.
    """
    # Multi-pack first: "6×1.5 ליטר"
    m = _MULTIPACK.search(product_name)
    if m:
        count = float(m.group(1))
        each = float(m.group(2))
        unit = _match_unit(m.group(3)) or "unit"
        return count * each, unit

    # Single quantity+unit: "1.5 ליטר"
    m = _SINGLE_QU.search(product_name)
    if m:
        qty = float(m.group(1))
        unit = _match_unit(m.group(2)) or "unit"
        return qty, unit

    return 1.0, "unit"


def parse_promotion(promotion_text: Optional[str]) -> Optional[dict]:
    """
    Parse a promotion string and return a dict describing it, or None.

    Returned keys (depending on promo type):
      n_for_price: {"type": "n_for_price", "n": int, "price": float}
      buy_get:     {"type": "buy_get", "pay": int, "free": int}
      percent:     {"type": "percent", "discount": int}
    """
    if not promotion_text:
        return None

    m = _PROMO_N_FOR_PRICE.search(promotion_text)
    if m:
        return {"type": "n_for_price", "n": int(m.group(1)), "price": float(m.group(2))}

    m = _PROMO_BUY_GET.search(promotion_text)
    if m:
        return {"type": "buy_get", "pay": int(m.group(1)), "free": int(m.group(2))}

    m = _PROMO_PERCENT.search(promotion_text)
    if m:
        return {"type": "percent", "discount": int(m.group(1))}

    return None


def effective_unit_price(price: float, qty: float, unit: str, promo: Optional[dict]) -> float:
    """
    Compute the effective price per base unit given an optional promotion.

    Base unit is always the product's own unit (liter, g, kg, unit …).
    """
    if promo:
        if promo["type"] == "n_for_price":
            # 3 items for 15 NIS → each item costs price/qty → 15/3 per product-unit
            return promo["price"] / promo["n"] / max(qty, 0.001)
        if promo["type"] == "buy_get":
            # pay for `pay`, get `pay+free` total → effective price per unit
            total_units = (promo["pay"] + promo["free"]) * qty
            cost = promo["pay"] * price
            return cost / max(total_units, 0.001)
        if promo["type"] == "percent":
            discounted = price * (1 - promo["discount"] / 100)
            return discounted / max(qty, 0.001)

    return price / max(qty, 0.001)


def optimal_quantity_for_promotion(
    requested: int, promo: Optional[dict]
) -> int:
    """
    Given how many units the user wants, return the optimal quantity to add
    so promotions are fully utilized (and never wasted).

    Rule: if a larger bundle has a lower effective unit price, take the bundle
    even if it exceeds the requested quantity.
    """
    if not promo:
        return requested

    if promo["type"] == "n_for_price":
        n = promo["n"]
        # Round up to nearest multiple of n
        return max(n, ((requested + n - 1) // n) * n)

    if promo["type"] == "buy_get":
        group = promo["pay"] + promo["free"]
        # Round up to nearest full group
        return max(group, ((requested + group - 1) // group) * group)

    return requested
