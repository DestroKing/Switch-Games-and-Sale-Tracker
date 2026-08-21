"""Per-store extraction profiles for sites with no public product API.

Every selector field is a TUPLE of candidates, tried in order.  Sites revert,
A/B-test and roll back, so a candidate that stops working sits alongside its
replacement rather than being deleted.

Profiles marked "confirmed" were read out of a real diagnostics dump of the
live page, not guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from switch_tracker.adapters.browser import overrides as profile_overrides
from switch_tracker.core.models import Platform, Region

SELECTOR_FIELDS = ("card", "title", "price", "link")


@dataclass(frozen=True, slots=True)
class StoreProfile:
    card: tuple[str, ...]
    title: tuple[str, ...]
    price: tuple[str, ...]
    link: tuple[str, ...]
    default_region: Region = Region.IN
    platform_hint: Platform | None = None
    out_of_stock: tuple[str, ...] = ()
    #: Cookie banners and interstitials to click away before scraping.
    dismiss: tuple[str, ...] = ()
    #: Wait for this before scraping; usually the results container.
    ready: str | None = None
    #: When set, paging CLICKS this instead of substituting {p} into a URL.
    #: Some storefronts render page 2+ entirely client-side with no
    #: navigation, so a page query parameter silently returns page 1 forever.
    next_page: tuple[str, ...] = ()


PROFILES: dict[str, StoreProfile] = {
    "amazon_in": StoreProfile(
        # data-component-type is Amazon's own hook and markedly more stable
        # than their generated class names.
        card=(
            "div[data-component-type='s-search-result']",
            "div.s-result-item[data-asin]:not([data-asin=''])",
        ),
        title=("h2 a span", "h2 span", "[data-cy='title-recipe'] span"),
        price=("span.a-price span.a-offscreen", "span.a-price-whole", ".a-color-price"),
        link=("h2 a", "a.a-link-normal.s-no-outline", "a[href*='/dp/']"),
        out_of_stock=(":has-text('Currently unavailable')", ".a-color-price:has-text('unavailable')"),
        platform_hint=Platform.SWITCH,
        ready="div.s-main-slot",
        dismiss=("input[data-action-type='DISMISS']", "button:has-text('Continue shopping')"),
    ),
    "flipkart": StoreProfile(
        # Flipkart's classes are generated and rotate. Anchor on structure and
        # href shape instead; the /p/ path segment has been stable for years.
        card=("div[data-id]", "div._1sdMkc", "a[href*='/p/']:has(img)"),
        title=("a[title]", "div.KzDlHZ", "a.wjcEIp", "div._4rR01T"),
        price=("div.Nx9bqj", "div._30jeq3", "div._4b5DiR"),
        link=("a[href*='/p/']",),
        out_of_stock=(":has-text('Sold Out')", ":has-text('Coming Soon')"),
        platform_hint=Platform.SWITCH,
        ready="div[data-id], a[href*='/p/']",
        dismiss=("button._2KpZ6l._2doB4z", "span._30XB9F", "button:has-text('X')"),
    ),
    "playasia": StoreProfile(
        card=("div.product-item", "li.product", "[class*='product-tile']"),
        title=(".product-title", ".title", "h3"),
        price=(".price", ".product-price"),
        link=("a",),
        out_of_stock=(".out-of-stock", ".sold-out"),
        default_region=Region.UNKNOWN,
    ),
    "gamestheshop": StoreProfile(
        # Confirmed from a real dump: this site has stable "ak-" class names.
        card=("div.ak-card",),
        title=("a.ak-card-title", ".ak-card-title"),
        price=("span.ak-card-priceVal", ".ak-card-price"),
        link=("a.ak-card-title", "a[href^='/product/']"),
        out_of_stock=(":has-text('Out of Stock')", ":has-text('Sold Out')"),
        platform_hint=Platform.SWITCH,
        ready="div.ak-card",
    ),
    "gamenation": StoreProfile(
        # Confirmed from a real dump. Next.js with CSS-module class names that
        # carry a per-build hash, so matched by substring rather than exactly.
        # The original guess used lowercase "/products/"; the real links are
        # "/Products/" with a capital P, and CSS attribute matching is
        # case-sensitive by default -- which is why this silently matched
        # nothing while the page rendered real listings the whole time.
        card=("a[class*='productCard' i]", "a[href*='/Products/' i]"),
        title=("h3[class*='productTitle' i]", "h3"),
        # Current and struck-through old price are separate, similarly-named
        # spans. Pick the current one.
        price=("span[class*='currentPrice' i]", "span[class*='price' i]"),
        link=("a[class*='productCard' i]", "a[href*='/Products/' i]"),
        out_of_stock=(":has-text('Out of Stock')", ":has-text('Sold Out')"),
        platform_hint=Platform.SWITCH,
        ready="a[class*='productCard' i]",
        # Confirmed: the page query parameter does nothing at all -- pages
        # 1/2/3 came back byte-for-byte identical. The real control is a
        # client-side button, and unlike mcubegames it is aria-labelled.
        next_page=("button[aria-label='Next page']",),
    ),
    "mcubegames": StoreProfile(
        # Confirmed from a real dump. Tailwind utility classes only, no
        # semantic per-component names, and the product link wraps the image
        # and the title in two separate <a> tags rather than one card.
        # "/product/" singular is the real path; the guess used the plural.
        card=("div.bg-card", "a[href^='/product/']"),
        title=("p.line-clamp-2", "p"),
        price=("span.font-semibold", "span"),
        link=("a[href^='/product/']",),
        out_of_stock=(":has-text('Out of Stock')", ":has-text('Sold Out')"),
        platform_hint=Platform.SWITCH,
        ready="div.bg-card, a[href^='/product/']",
        # Confirmed: pages 1/2/3 identical, producing a 14-item result from a
        # 42-page catalogue. The next control has no text and no aria-label,
        # just a chevron icon, so it is targeted by that icon's class.
        next_page=("button:has(svg.lucide-chevron-right)",),
    ),
    "e2zstore": StoreProfile(
        # Still a guess: every diagnostics dump so far shows only a Cloudflare
        # bot-check page, so there is no real markup to read yet. Starts from
        # WooCommerce's default theme markup, including the "current price
        # wins over struck-through old price" pattern -- `ins` wraps the sale
        # price, `del` the crossed-out one.
        card=("li.product", "div.product", "[data-product-id]"),
        title=("h2.woocommerce-loop-product__title", ".product-title", "h2 a", "h3 a"),
        price=("span.price ins .amount", "span.price .amount", ".price"),
        link=("a.woocommerce-LoopProduct-link", "a"),
        out_of_stock=(".out-of-stock", ":has-text('Out of stock')"),
        platform_hint=Platform.SWITCH,
        ready="li.product, div.product",
    ),
}


def effective_profile(store_id: str) -> StoreProfile | None:
    """The built-in profile with any clicked-in corrections PREPENDED.

    Prepending rather than replacing is deliberate: a correction found through
    the picker should be tried first, but must not require the person making
    it to also re-supply a whole working profile.
    """
    base = PROFILES.get(store_id)
    if base is None:
        return None

    found = profile_overrides.read().get(store_id)
    if not found:
        return base

    def merged(field: str, existing: tuple[str, ...]) -> tuple[str, ...]:
        extra = found.get(field)
        if not extra:
            return existing
        return tuple(extra) + tuple(c for c in existing if c not in extra)

    return replace(
        base,
        card=merged("card", base.card),
        title=merged("title", base.title),
        price=merged("price", base.price),
        link=merged("link", base.link),
    )
