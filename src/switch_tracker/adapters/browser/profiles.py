from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from switch_tracker.adapters.browser import overrides as profile_overrides
from switch_tracker.core.models import Platform, Region

SELECTOR_FIELDS = ("card", "title", "price", "link")

#: Playwright's own accepted values, mirrored so a typo in a profile is a type
#: error at check time rather than an exception on a live scrape.
WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


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
    #: (name, value) pairs set on ``cookie_domain`` before the first navigation.
    #:
    #: This is a CORRECTNESS mechanism, not a convenience. A store that prices
    #: per session decides its currency from these, so ``StoreConfig.currency``
    #: is only true if the session is pinned to match it. Getting this wrong
    #: does not fail -- it records another currency's numbers as rupees.
    #:
    #: Lives on the profile rather than in BrowserProvider so one store's
    #: session needs cannot leak into every other store's context.
    cookies: tuple[tuple[str, str], ...] = ()
    cookie_domain: str = ""

    # --- Page mechanics. Every default below reproduces what BrowserAdapter did
    # when these were hardcoded, so a profile that sets none of them behaves
    # exactly as it did before they existed. That is the regression contract,
    # and test_browser_logic asserts it for every store but the one that opts in.

    #: Playwright's goto() readiness condition. "networkidle" is for storefronts
    #: whose results arrive by XHR after the document is parsed; on those,
    #: "domcontentloaded" returns before a single product exists. It is slower
    #: and can fail to settle on a page that polls, so it is opt-in per store
    #: rather than raised globally -- and BrowserAdapter falls back once when it
    #: times out, because losing a page beats losing the store's whole budget.
    wait_until: WaitUntil = "domcontentloaded"
    #: 1 == one proportional scrollTo, which is what every store did before.
    #: >1 switches to that many viewport-sized scrollBy steps: a lazily-loaded
    #: grid extends the document as it fills, so a single proportional jump
    #: lands mid-page and stops triggering further loads.
    scroll_passes: int = 1
    #: Pause between those steps. Unused at scroll_passes == 1.
    scroll_settle_ms: int = 0
    #: Substrings that mark an href as NOT a product -- category and search
    #: links that sit inside product cards on some storefronts. Without this the
    #: classifier keeps them: a nav link titled "Nintendo Switch" plus a SWITCH
    #: platform_hint classifies as GAME.
    #:
    #: Deliberately substring matching and not a regex. The filter must fail
    #: OPEN: an unmatched URL is kept, so a wrong rule leaves junk in the
    #: database, which is recoverable. A mis-anchored regex fails CLOSED and
    #: silently deletes an entire store's listings, which is not.
    reject_url_parts: tuple[str, ...] = ()
    #: Product URLs on some stores always carry a numeric id. Where that holds,
    #: its absence is a reliable "this is not a product" signal.
    require_digit_in_url: bool = False
    #: Hard cap on pages walked PER SEARCH URL. None means only the adapter's
    #: global safety bound applies.
    #:
    #: A guard, not a tuning knob: a store that pages deeply can exhaust the
    #: collection deadline, and the service discards a timed-out store's rows
    #: entirely. Capping keeps a known-large catalogue inside the budget so its
    #: results are persisted rather than thrown away.
    max_pages: int | None = None


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
        # Play-Asia prices per session. Without these it quotes its default
        # currency, and the collector would write those numbers into
        # price_point.native_price under native_currency='INR' -- a wrong price
        # that is indistinguishable from a real one forever after. This is what
        # makes StoreConfig.currency='INR' true rather than merely asserted.
        cookies=(("currency", "INR"), ("country", "IN")),
        cookie_domain=".play-asia.com",
        # The only store that sets any of these. Each value is what the
        # hand-verified sweep in scripts/scrape_check_playasia.py used and the
        # collector did not -- which is why the two disagreed on the same site.
        #
        # networkidle: results arrive by XHR, so domcontentloaded returns before
        # any product exists. Opt-in per store because it is slower and can fail
        # to settle; BrowserAdapter._goto falls back once when it does.
        wait_until="networkidle",
        # Two viewport-sized steps rather than one proportional jump: the grid
        # grows as it hydrates, so a single 60%-of-scrollHeight jump lands
        # mid-document and stops pulling more in.
        scroll_passes=2,
        scroll_settle_ms=600,
        # Category and search links sit inside the result cards here, and the
        # classifier cannot reject them -- one titled "Nintendo Switch" plus
        # this store's SWITCH hint is a textbook GAME. Product URLs always
        # carry a numeric id, so its absence is a reliable negative.
        reject_url_parts=("/search/", "/category/"),
        require_digit_in_url=True,
        # The verified sweep capped at 5 per URL. 15 buys real depth while
        # keeping 2 URLs x 15 pages inside the time budget even when pages are
        # slow -- and the budget itself is the backstop if they are slower.
        max_pages=15,
        # Ordered narrowest-first, and that ordering is load-bearing:
        # from_selectors takes the FIRST card selector that yields rows, so a
        # bare ".item" ahead of these would win on any page where a nav or
        # breadcrumb element carries that class. "div.item" and
        # ".item-list-view .item" are the two that were verified by hand
        # against the live site; bare ".item" stays last as a fallback rather
        # than being deleted, since it costs nothing once it cannot pre-empt.
        card=(
            ".product-item",
            ".search-item",
            "div.item",
            ".item-list-view .item",
            ".item",
            "[class*='product']",
        ),
        title=(".item-name a", ".product-name a", "a.title", "h3 a", ".title", "a[href*='/en/']"),
        price=(".price-value", ".item-price .amount", ".product-price", ".price"),
        # ".product-item a" comes from the hand-verified sweep. It sits before
        # the generic href fallback and after the specific ones, so it can only
        # fire where the precise selectors already missed.
        link=(
            ".item-name a",
            ".product-name a",
            "a.title",
            "h3 a",
            ".product-item a",
            "a[href*='/en/']",
        ),
        out_of_stock=(".out-of-stock", ".sold-out", ":has-text('Sold out')", ":has-text('Out of stock')"),
        default_region=Region.ASIA_EN,
        platform_hint=Platform.SWITCH,
        # ".item" deliberately NOT in the readiness probe. A nav element with
        # that class satisfies it instantly, so the wait returns before a single
        # product has rendered and extraction runs against an empty grid.
        # Waiting on the product containers is the whole point of the probe.
        ready=".product-item, .search-item, div.item",
        # EMPTY ON PURPOSE, and this is load-bearing.
        #
        # Its search URLs carry no "{p}", so BrowserAdapter still takes the
        # click path -- but with no CSS selectors to try, _click_next goes
        # straight to the numeric page-number mechanism, which is the ONLY
        # mechanism the hand-verified sweep ever used.
        #
        # The previous list started with a bare ":has-text('>')" that matched
        # html and body, so `.last` clicked a footer <small>. Replacing it with
        # tag-scoped guesses would still mean production tries six controls the
        # verified run never touched, any one of which could navigate somewhere
        # the sweep never went. Trying nothing is what makes the two identical.
        next_page=(),
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
        # A WooCommerce storefront whose Store API is not exposed, so it is
        # scraped through the theme's standard woocommerce-loop-* class names
        # rather than through /wp-json. Those names are theme-level and stable.
        card=("div.product-small.product", "div.product"),
        title=(".woocommerce-loop-product__title a", ".woocommerce-loop-product__title"),
        # ins wraps the DISCOUNTED price when one exists; plain .amount is the
        # regular price. Sale price first, or a discounted row reports its
        # struck-through original.
        price=("span.price ins .amount", "span.price .amount"),
        link=("a.woocommerce-LoopProduct-link", "a.woocommerce-loop-product__link"),
        out_of_stock=(":has-text('Out of stock')", ".outofstock"),
        platform_hint=Platform.SWITCH,
        ready="div.product-small.product",
        # /page/{p}/ works here, but the theme also renders a real next link;
        # keeping it lets paging survive the URL scheme changing.
        next_page=("a.next.page-number", "a.next", "ul.page-numbers a.next"),
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