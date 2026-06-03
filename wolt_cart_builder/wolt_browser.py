"""
Playwright-based browser automation for Wolt Market.

Session persistence: after first manual login the browser context is saved to
~/.wolt_session.json so subsequent runs don't require login.

Safety guarantee: this module never navigates to /checkout, /payment, or any
order-completion page. An assertion checks the URL before and after every
add-to-cart action.
"""
from __future__ import annotations
import asyncio
import logging
import re
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Page,
    Browser,
    BrowserContext,
    ElementHandle,
    TimeoutError as PWTimeout,
)

from .config import Config
from .models import WoltProduct
from .unit_parser import parse_quantity_unit, parse_promotion

logger = logging.getLogger(__name__)

# Wolt selector hints (multiple fallbacks per element type)
_SEARCH_SELECTORS = [
    '[data-test-id="search-input"]',
    'input[placeholder*="חיפוש"]',
    'input[placeholder*="ח"]',
    'input[type="search"]',
    '[role="searchbox"]',
    'input[class*="search"]',
]

_PRODUCT_CARD_SELECTORS = [
    '[data-test-id="ItemCard"]',
    '[data-test-id="product-card"]',
    'div[class*="ItemCard"]',
    'article[class*="product"]',
    '[class*="product-card"]',
    'li[class*="item"]',
]

_NAME_SELECTORS = [
    '[data-test-id="ItemCardName"]',
    '[data-test-id="product-name"]',
    'h3', 'h4',
    '[class*="item-name"]',
    '[class*="product-name"]',
    '[class*="ItemName"]',
]

_PRICE_SELECTORS = [
    '[data-test-id="ItemCardPrice"]',
    '[data-test-id="product-price"]',
    '[class*="price"]',
    '[class*="Price"]',
]

_ORIGINAL_PRICE_SELECTORS = [
    '[class*="original-price"]',
    '[class*="OriginalPrice"]',
    's[class*="price"]',
    'del',
    's',
]

_PROMOTION_SELECTORS = [
    '[data-test-id="ItemCardBadge"]',
    '[class*="badge"]',
    '[class*="Badge"]',
    '[class*="promotion"]',
    '[class*="Promotion"]',
    '[class*="deal"]',
    '[class*="tag"]',
]

_ADD_BTN_SELECTORS = [
    '[data-test-id="add-item-button"]',
    '[data-test-id="AddToCartButton"]',
    'button[aria-label*="הוסף"]',
    'button[aria-label*="Add"]',
    '[class*="add-button"]',
    '[class*="AddButton"]',
    'button[class*="plus"]',
]

_CHECKOUT_PATTERNS = re.compile(r"/(checkout|payment|order-confirm|place-order)", re.I)


def _assert_not_checkout(url: str) -> None:
    if _CHECKOUT_PATTERNS.search(url):
        raise RuntimeError(
            f"SAFETY STOP: navigation reached a checkout/payment URL: {url}\n"
            "The automation will not proceed. Please review and place the order manually."
        )


def _parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    text = text.replace("₪", "").replace(",", ".").strip()
    m = re.search(r"[\d.]+", text)
    return float(m.group()) if m else None


class WoltBrowser:
    """Manages a Playwright browser session for Wolt Market."""

    def __init__(self, config: Config):
        self.config = config
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
            args=["--lang=he-IL"],
        )
        ctx_kwargs = dict(
            locale="he-IL",
            timezone_id="Asia/Jerusalem",
            viewport={"width": 1280, "height": 900},
        )
        session = Path(self.config.session_file)
        if session.exists():
            logger.info("Loading saved Wolt session from %s", session)
            ctx_kwargs["storage_state"] = str(session)

        self._context = await self._browser.new_context(**ctx_kwargs)
        self.page = await self._context.new_page()
        logger.info("Browser started.")

    async def close(self) -> None:
        if self._context:
            try:
                session = Path(self.config.session_file)
                session.parent.mkdir(parents=True, exist_ok=True)
                await self._context.storage_state(path=str(session))
                logger.info("Session saved to %s", session)
            except Exception as e:
                logger.warning("Could not save session: %s", e)
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------ #
    # Navigation & login
    # ------------------------------------------------------------------ #

    async def navigate_to_store(self) -> None:
        """Go to the configured Wolt Market store, handle login if needed."""
        store_url = self.config.store_url
        _assert_not_checkout(store_url)

        logger.info("Navigating to %s", store_url)
        await self.page.goto(store_url, wait_until="domcontentloaded", timeout=30_000)
        await self.page.wait_for_timeout(2000)

        # Dismiss cookie/location banners if present
        await self._dismiss_banners()

        # Check if login is required
        if await self._needs_login():
            await self._handle_login()

        _assert_not_checkout(self.page.url)

    async def _dismiss_banners(self) -> None:
        """Try to close common modal dialogs."""
        dismiss_selectors = [
            'button[data-test-id="cookie-consent-accept"]',
            'button[aria-label="סגור"]',
            'button[aria-label="Close"]',
            '[class*="close-button"]',
            '[data-test-id="modal-close-button"]',
        ]
        for sel in dismiss_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await self.page.wait_for_timeout(500)
            except Exception:
                pass

    async def _needs_login(self) -> bool:
        url = self.page.url
        if "login" in url or "signup" in url:
            return True
        # Look for a login button indicating we're not logged in
        try:
            login_btn = await self.page.query_selector('[data-test-id="login-button"]')
            if login_btn and await login_btn.is_visible():
                return True
        except Exception:
            pass
        return False

    async def _handle_login(self) -> None:
        """Pause and let the user log in manually, then continue."""
        print(
            "\n" + "=" * 60 + "\n"
            "  ACTION REQUIRED: Please log in to Wolt in the browser window.\n"
            "  After logging in and reaching the Wolt Market store,\n"
            "  press ENTER here to continue the automation.\n"
            + "=" * 60 + "\n"
        )
        input("Press ENTER after logging in and navigating to the Wolt Market store > ")
        _assert_not_checkout(self.page.url)
        # Save the freshly authenticated session
        session = Path(self.config.session_file)
        session.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(session))
        logger.info("Post-login session saved.")

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    async def search_products(self, query: str) -> list[WoltProduct]:
        """Search Wolt Market for `query` and return parsed products."""
        _assert_not_checkout(self.page.url)

        logger.info("Searching for: %s", query)
        search_input = await self._find_element(_SEARCH_SELECTORS, "search input")
        if not search_input:
            logger.error("Search input not found on page: %s", self.page.url)
            return []

        await search_input.triple_click()
        await search_input.fill(query)
        await self.page.keyboard.press("Enter")
        await self.page.wait_for_timeout(2500)

        products = await self._extract_products()
        logger.info("Found %d products for '%s'", len(products), query)
        return products

    # ------------------------------------------------------------------ #
    # Product extraction
    # ------------------------------------------------------------------ #

    async def _extract_products(self) -> list[WoltProduct]:
        cards = await self._find_all_elements(_PRODUCT_CARD_SELECTORS)
        products: list[WoltProduct] = []
        limit = self.config.max_search_results

        for card in cards[:limit]:
            try:
                p = await self._parse_card(card)
                if p:
                    products.append(p)
            except Exception as e:
                logger.debug("Card parse error: %s", e)

        return products

    async def _parse_card(self, card: ElementHandle) -> Optional[WoltProduct]:
        name = await self._text_from(card, _NAME_SELECTORS)
        price_text = await self._text_from(card, _PRICE_SELECTORS)
        orig_price_text = await self._text_from(card, _ORIGINAL_PRICE_SELECTORS)
        promo_text = await self._text_from(card, _PROMOTION_SELECTORS)

        if not name or not price_text:
            return None

        price = _parse_price(price_text)
        if price is None:
            return None

        orig_price = _parse_price(orig_price_text)
        qty, unit = parse_quantity_unit(name)
        promo = parse_promotion(promo_text)

        product = WoltProduct(
            name=name.strip(),
            price=price,
            original_price=orig_price,
            quantity_in_package=qty,
            unit=unit,
            promotion_text=promo_text,
        )

        # If promotion is "n for price", store on the product for easy price comparison
        if promo and promo["type"] == "n_for_price":
            product.promotion_quantity = promo["n"]
            product.promotion_price = promo["price"]

        return product

    # ------------------------------------------------------------------ #
    # Add to cart
    # ------------------------------------------------------------------ #

    async def add_to_cart(
        self, product_name: str, quantity: int, dry_run: bool = False
    ) -> bool:
        """
        Find the product in current search results and add `quantity` units to cart.
        NEVER navigates to checkout.
        """
        _assert_not_checkout(self.page.url)

        cards = await self._find_all_elements(_PRODUCT_CARD_SELECTORS)
        for card in cards:
            name = await self._text_from(card, _NAME_SELECTORS)
            if not name or product_name.strip() not in name.strip():
                continue

            add_btn = await self._find_element_within(card, _ADD_BTN_SELECTORS)
            if not add_btn:
                logger.warning("Add button not found for '%s'", product_name)
                return False

            if dry_run:
                logger.info("[DRY RUN] Would add %d × '%s' to cart", quantity, product_name)
                return True

            for i in range(quantity):
                _assert_not_checkout(self.page.url)
                await add_btn.click()
                await self.page.wait_for_timeout(600)

                # The button may turn into a quantity selector after first click;
                # re-query each iteration to get the fresh "+" element
                add_btn = await self._find_element_within(card, [
                    '[data-test-id="add-item-button"]',
                    'button[aria-label*="+"]',
                    '[class*="plus"]',
                    '[class*="increment"]',
                ] + _ADD_BTN_SELECTORS)
                if not add_btn and i < quantity - 1:
                    logger.warning("Lost add button after click %d/%d", i + 1, quantity)
                    break

            _assert_not_checkout(self.page.url)
            logger.info("Added %d × '%s' to cart", quantity, product_name)
            return True

        logger.warning("Product card not found in page for '%s'", product_name)
        return False

    # ------------------------------------------------------------------ #
    # Helper utilities
    # ------------------------------------------------------------------ #

    async def _find_element(
        self, selectors: list[str], label: str = "element"
    ) -> Optional[ElementHandle]:
        for sel in selectors:
            try:
                el = await self.page.wait_for_selector(
                    sel, timeout=self.config.element_timeout, state="visible"
                )
                if el:
                    return el
            except PWTimeout:
                continue
            except Exception as e:
                logger.debug("Selector '%s' error: %s", sel, e)
        logger.debug("Could not find %s with any selector", label)
        return None

    async def _find_all_elements(self, selectors: list[str]) -> list[ElementHandle]:
        for sel in selectors:
            try:
                elements = await self.page.query_selector_all(sel)
                if elements:
                    return elements
            except Exception:
                continue
        return []

    async def _find_element_within(
        self, parent: ElementHandle, selectors: list[str]
    ) -> Optional[ElementHandle]:
        for sel in selectors:
            try:
                el = await parent.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    async def _text_from(
        self, parent: ElementHandle, selectors: list[str]
    ) -> Optional[str]:
        for sel in selectors:
            try:
                el = await parent.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return None

    async def take_screenshot(self, path: str) -> None:
        try:
            await self.page.screenshot(path=path, full_page=False)
        except Exception as e:
            logger.debug("Screenshot failed: %s", e)
