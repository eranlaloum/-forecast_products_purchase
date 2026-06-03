"""Data models for Wolt cart builder."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class CartStatus(str, Enum):
    ADDED = "added"
    NOT_FOUND = "not_found"
    NEEDS_REVIEW = "needs_review"
    PROMOTION_APPLIED = "promotion_applied"


@dataclass
class ShoppingItem:
    """An item from the user's shopping list."""
    name: str
    requested_quantity: int = 1
    original_text: str = ""


@dataclass
class WoltProduct:
    """A product found on Wolt Market."""
    name: str
    price: float
    quantity_in_package: float  # e.g. 1.5 (liters), 6 (units), 200 (grams)
    unit: str                   # "unit", "kg", "liter", "g", "ml"
    original_price: Optional[float] = None
    promotion_text: Optional[str] = None
    promotion_quantity: Optional[int] = None   # e.g. 3 in "3 for 15 NIS"
    promotion_price: Optional[float] = None    # e.g. 15 in "3 for 15 NIS"
    brand: Optional[str] = None
    image_url: Optional[str] = None

    @property
    def effective_unit_price(self) -> float:
        """Price per base unit, accounting for promotions."""
        if self.promotion_quantity and self.promotion_price:
            # e.g. "3 for 15" → 5 per item
            return self.promotion_price / self.promotion_quantity
        return self.price / max(self.quantity_in_package, 0.001)

    @property
    def display_unit(self) -> str:
        unit_map = {
            "unit": "יח'",
            "kg": "ק\"ג",
            "liter": "ליטר",
            "g": "ג'",
            "ml": "מ\"ל",
        }
        return unit_map.get(self.unit, self.unit)


@dataclass
class CartEntry:
    """Result of processing one shopping list item."""
    shopping_item: ShoppingItem
    status: CartStatus
    selected_product: Optional[WoltProduct] = None
    quantity_added: int = 0
    notes: str = ""
    alternatives: list[WoltProduct] = field(default_factory=list)

    @property
    def promotion_used(self) -> Optional[str]:
        if self.selected_product and self.selected_product.promotion_text:
            return self.selected_product.promotion_text
        return None


@dataclass
class CartSummary:
    """Final summary of the cart building operation."""
    entries: list[CartEntry] = field(default_factory=list)
    total_estimated_cost: float = 0.0

    @property
    def added_items(self) -> list[CartEntry]:
        return [e for e in self.entries if e.status in (CartStatus.ADDED, CartStatus.PROMOTION_APPLIED)]

    @property
    def missing_items(self) -> list[CartEntry]:
        return [e for e in self.entries if e.status == CartStatus.NOT_FOUND]

    @property
    def review_items(self) -> list[CartEntry]:
        return [e for e in self.entries if e.status == CartStatus.NEEDS_REVIEW]
