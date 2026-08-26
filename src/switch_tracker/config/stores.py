"""The shipped store list.

``kind`` for the API-based stores is a HYPOTHESIS. Running "Check stores"
(probe) corrects it into stores.local.json rather than editing this file --
a tool must never rewrite the source it also imports.

BROWSER stores need a profile in adapters/browser/profiles.py and are skipped
by probe entirely; there is no API for it to detect.
"""

from __future__ import annotations

from switch_tracker.core.models import AdapterKind, Platform, StoreConfig

STORES: tuple[StoreConfig, ...] = (
    # ---- Tier 2: dedicated retailers. The real catalogue lives here. ----
    StoreConfig(
        id="nistore",
        name="NI Gaming Store",
        base_url="https://nistore.in",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-switch-games", "nintendo-switch-pre-owned-games", "nintendo-switch-2"),
        note=(
            "Verified: three pages of Switch/Switch 2 cartridges. Also carries consoles, "
            "accessories and collectibles, so scoped to its actual games categories rather "
            "than relying on classification alone."
        ),
    ),
    StoreConfig(
        id="gameloot",
        name="GameLoot",
        base_url="https://gameloot.in",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-switch",),
        note=(
            "General electronics/gift-card retailer, scoped to its Nintendo Switch category; "
            "accessories and consoles have separate categories this deliberately excludes."
        ),
    ),
    StoreConfig(
        id="nekavo",
        name="NEKAVO",
        base_url="https://nekavo.com",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-switch-games", "nintendo-switch-2"),
        note=(
            "Primarily a Funko Pop/anime collectibles store, scoped to its two Switch games "
            "categories; excludes nintendo-accessories and nintendo-merchandise."
        ),
    ),
    StoreConfig(
        id="emartgames",
        name="Emart Games",
        base_url="https://emartgames.in",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-switch-games-cds-online-india", "nintendo-switch-2-games"),
        note="Multi-console store (also PS3/PS4/PS5), scoped to its two Switch categories.",
    ),
    StoreConfig(
        id="hgworld",
        name="HG World",
        base_url="https://hgworld.in",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-games",),
        note=(
            "Probe's category listing missed this at first: the store has 100+ categories and "
            "the fetch was not paginated deep enough to reach it."
        ),
    ),
    StoreConfig(
        id="zozila",
        name="Zozila",
        base_url="https://zozila.com",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=False,
        platform_hint=Platform.SWITCH,
        note=(
            "Disabled: probe's category listing shows a digital gift-card/voucher marketplace, "
            "not a cartridge retailer. None of its ~100 categories matched Switch/Nintendo."
        ),
    ),
    StoreConfig(
        id="designinfo",
        name="DesignInfo",
        base_url="https://www.designinfo.in",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        # Not a games-only category, but still worth scoping to: this is a 570+
        # category camera/audio/electronics store, so even an imprecise
        # Nintendo-only category cuts the fetch down enormously and leaves the
        # classifier a far safer job -- separating games from consoles within
        # an already-Nintendo-scoped set, rather than fishing them out of an
        # entire unrelated catalogue.
        collections=("nintendo-gaming-consoles",),
        # NO platform_hint on purpose. Even within this category it is not
        # guaranteed everything is Switch, so requiring an explicit console
        # mention is the safe default for an unscoped multi-brand site.
        note=(
            "Real kind is WooCommerce, not Shopify -- probe corrects this into "
            "stores.local.json. Scoped to its one Nintendo category; no games-only split exists."
        ),
    ),
    # ---- Tier 1: browser automation. No public product API. ----
    StoreConfig(
        id="amazon_in",
        name="Amazon.in",
        base_url="https://www.amazon.in",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # A real browse-node category listing, not a keyword search: covers
        # both Switch and Switch 2 in one URL and is more complete than the
        # old free-text "nintendo switch games" search.
        search_urls=(
            "https://www.amazon.in/s?i=videogames&rh=n%3A976460031%2Cn%3A13995115031%2C"
            "n%3A13995151031&dc&qid=1787339967&rnid=13995115031&ref=sr_nr_n_1&page={p}",
        ),
        note="Real bot detection. Cards keyed on data-component-type, stabler than class names.",
    ),
    StoreConfig(
        id="flipkart",
        name="Flipkart",
        base_url="https://www.flipkart.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=(
            "https://www.flipkart.com/gaming/games/physical-game/pr?sid=4rr%2Cfa6%2C32v"
            "&marketplace=FLIPKART&p%5B%5D=facets.platform%255B%255D%3DSwitch"
            "&p%5B%5D=facets.platform%255B%255D%3DSwitch%2B2&page={p}",
        ),
        note="Obfuscated, rotating class names. The adapter prefers __INITIAL_STATE__ over CSS.",
    ),
    StoreConfig(
        id="gamestheshop",
        name="Games The Shop",
        base_url="https://www.gamestheshop.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=(
            "https://www.gamestheshop.com/search?condition=Physical&platforms=Nintendo+Switch"
            "&categories=Game+Software&page={p}",
            "https://www.gamestheshop.com/search?condition=Physical&platforms=Nintendo+Switch+2"
            "&categories=Game+Software&page={p}",
        ),
        note="Custom Next.js storefront with no public product API, so it is scraped.",
    ),
    StoreConfig(
        id="gamenation",
        name="GameNation",
        base_url="https://gamenation.in",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=("https://gamenation.in/PlayStation/?platform=nintendoSwitch%2CnintendoSwitch2&page={p}",),
        note=(
            "The /PlayStation/ path is misleading -- it is the general catalogue filtered by a "
            "platform query param. Pagination is click-based; the page param does nothing."
        ),
    ),
    StoreConfig(
        id="mcubegames",
        name="Mcube Games",
        base_url="https://www.mcubegames.in",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=("https://www.mcubegames.in/shop?platforms=60&platforms=93&page={p}",),
        note="Filtered by numeric platform ids (60/93 = Switch/Switch 2). Click-based pagination.",
    ),
    StoreConfig(
        id="e2zstore",
        name="e2zSTORE",
        base_url="https://e2zstore.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=("https://e2zstore.com/category/nintendo-games/page/{p}/",),
        note=(
            "Uses /category/ structure matching working test script."
        ),
    ),
    StoreConfig(
        id="playasia",
        name="Play-Asia",
        base_url="https://www.play-asia.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        search_urls=(
            "https://www.play-asia.com/en/search/nintendo+switch+games",
            "https://www.play-asia.com/en/search/nintendo+switch+2+games",
        ),
        note=(
            "Pagination is click-based via DOM interaction rather than URL params. "
            "INR reference currency injected via session cookies."
        ),
    ),
)
