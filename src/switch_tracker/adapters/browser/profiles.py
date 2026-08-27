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
    #: Overrides BrowserAdapter's render pause after scrolling. None keeps the
    #: adapter default. Lower it only where paging is click-verified: there,
    #: _advanced() has already confirmed the results changed, so the full pause
    #: is largely idling.
    render_ms: int | None = None
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
    #: Overrides BrowserAdapter.DEFAULT_TIME_BUDGET_S for this store. None keeps
    #: the default. Raise it only for a catalogue genuinely worth a long walk --
    #: a browser store holds one of four concurrency slots for its whole run.
    #:
    #: MUST stay below CollectService.DEFAULT_BROWSER_DEADLINE_S. Above it, the
    #: service's hard timeout fires first, cancels the coroutine, and every page
    #: already scraped is discarded. A test asserts this for every profile.
    time_budget_s: float | None = None
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
        # 500 rather than the 1200 default. Measured: pages 2+ cost ~9.8s each,
        # of which ~3.6s was fixed waiting. Safe to shorten here specifically
        # because _click_next verifies the page turned before we get here --
        # this pause is for the tail of the grid, not for the page itself.
        render_ms=500,
        # Category and search links sit inside the result cards here, and the
        # classifier cannot reject them -- one titled "Nintendo Switch" plus
        # this store's SWITCH hint is a textbook GAME. Product URLs always
        # carry a numeric id, so its absence is a reliable negative.
        reject_url_parts=("/search/", "/category/"),
        require_digit_in_url=True,
        # FULL CATALOGUE. The live page reports 139 pages of ~44 products, so
        # ~6,100 rows and ~5,200 distinct cartridges. 150 leaves headroom for
        # the catalogue growing between runs.
        #
        # Sorting cannot help choose a better subset -- Play-Asia's sort control
        # writes a URL FRAGMENT (#fc=o:3), which is never sent to the server, so
        # there is no orderable URL to ship. And because paging is click-only
        # with no page parameter, reaching page 100 costs 99 page loads first:
        # depth is strictly sequential. Partial coverage would therefore always
        # be the SAME arbitrary half, every run.
        #
        # Measured cost: 24s for page 1 (networkidle) plus ~8.5s each after,
        # so 139 pages is roughly 20 minutes. That is a deliberate trade, not an
        # oversight -- see time_budget_s below, and prefer running this store on
        # its own from "Collect specific stores" rather than on every collection.
        max_pages=150,
        # 24 + 138 x 8.5 = ~1200s, plus margin. Below the service's 1500s
        # deadline so the adapter stops itself first and returns Partial with
        # everything collected.
        time_budget_s=1320.0,
        # Ordered narrowest-first, and that ordering is load-bearing:
        # from_selectors takes the FIRST card selector that yields rows, so a
        # bare ".item" ahead of these would win on any page where a nav or
        # breadcrumb element carries that class. "div.item" and
        # ".item-list-view .item" are the two that were verified by hand
        # against the live site; bare ".item" stays last as a fallback rather
        # than being deleted, since it costs nothing once it cannot pre-empt.
        # Confirmed against the live page, not guessed. Every previous entry
        # here matched ZERO elements; extraction only worked because it fell
        # through to "[class*='product']", which matches 488 elements of page
        # furniture, carousels and nav. That over-broad selector is also what
        # broke pagination: _click_next verifies a page turn by fingerprinting
        # the first few cards, and with furniture at the top of the list the
        # fingerprint never changed, so a successful click read as a failure.
        #
        # 44 of these exist per page; 36 carry a price. The rest are the
        # non-product tiles the price check in extract.py already drops.
        card=(
            "div.pa-modern-product-item",
            ".product-item",
            ".search-item",
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
        # The real product container, confirmed live. The previous value listed
        # ".product-item, .search-item, div.item" -- the first two match ZERO
        # elements on this site and "div.item" matches exactly one piece of page
        # furniture, so the probe was satisfied instantly by something that is
        # not a product. It never waited for anything, which is worse than
        # waiting too long: extraction could run against a grid that had not
        # rendered, and nothing would say so.
        ready="div.pa-modern-product-item",
        # Confirmed on the live page: a visible, semantically-named button, with
        # "1" / "139" siblings reporting position and total. Strictly better
        # than the numeric-text fallback this replaces -- it cannot be confused
        # with the Slick carousel's "1 2 3 4" buttons, which sit in the same
        # document and which a text-matching clicker would happily press.
        #
        # An earlier version of this list began with a bare ":has-text('>')".
        # Unscoped, that matches every element containing the character --
        # html and body included -- so `.last` resolved to a footer <small>
        # reading "Terms > Privacy", clicked it, and reported success.
        next_page=("button.pa-pagination-next",),
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