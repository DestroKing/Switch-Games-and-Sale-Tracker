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
    # ---- Tier 2: "legit but less established". Same adapters, smaller shops. ----
    #
    # These seven were added as one batch and every one of them is a
    # CONFIGURATION change only -- no new adapter, no new code path. Each was
    # confirmed to serve the public feed its kind implies before being listed
    # (WooCommerce /wp-json/wc/store/v1/products/categories, Shopify
    # /collections.json), so the slugs below are read off the store's own
    # category list rather than guessed from its navigation menu.
    #
    # `tier` stays what it has always meant here -- which adapter group a store
    # belongs to and when it runs -- and is deliberately NOT repurposed as a
    # trust or reputation score. Those are different questions, and one integer
    # answering both would make the collection order depend on an opinion.
    StoreConfig(
        id="sheenu",
        name="Sheenu Game Center",
        base_url="https://sheenugamecenter.com",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("switch-games", "switch-2-games"),
        note="Scoped to its two Switch games categories; consoles and accessories sit elsewhere.",
    ),
    StoreConfig(
        id="gamebuy",
        name="GameBuy",
        base_url="https://gamebuy.in",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # The PARENT category only, on purpose. WooCommerce returns a product
        # under its parent as well as its child terms, so listing the children
        # beside it fetches the same products two or three times over -- paid
        # for in requests on every run, then thrown away at dedupe.
        collections=("nintendo-switch",),
        note="Parent Nintendo category only; its feed already carries the child categories.",
    ),
    StoreConfig(
        id="hitechgamez",
        name="Hitech Gamez",
        base_url="https://hitechgamez.in",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # Three SIBLING categories with no shared parent to collapse them into,
        # unlike gamebuy above. The pre-owned one is not redundant: it is where
        # this store's used stock lives, and infer_condition reads the category
        # name out of the listing context, so dropping it would lose both the
        # rows and the only signal that says they are second-hand.
        collections=(
            "nintendo-switch-games",
            "buy-nintendo-switch-2-games",
            "preowned-nintendo-switch-games",
        ),
        note="New Switch, Switch 2 and pre-owned are three separate top-level categories here.",
    ),
    StoreConfig(
        id="gamebot",
        name="GameBot",
        base_url="https://gamebot.co.in",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("switch-games", "switch-2"),
        note="Slugs confirmed against its live wc/store/v1 category feed.",
    ),
    StoreConfig(
        id="gamekart",
        name="GameKart",
        base_url="https://gamekart.in",
        kind=AdapterKind.WOOCOMMERCE,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("games-nintendo",),
        note="Parent Nintendo games category only, for the same reason as gamebuy.",
    ),
    StoreConfig(
        id="consolegarage",
        name="Console Garage",
        base_url="https://consolegarage.com",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("switch", "switch-2"),
        note="Multi-console Shopify store, scoped to its two Switch collections.",
    ),
    StoreConfig(
        id="hadiro",
        name="Hadiro",
        base_url="https://www.hadiro.in",
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("nintendo-switch-games", "nintendo-switch-2"),
        note="Slugs confirmed against its live /collections.json.",
    ),
    # ---- Tier 1: browser automation. No public product API. ----
    StoreConfig(
        id="playasia",
        name="Play-Asia",
        base_url="https://www.play-asia.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # ONE search URL, not two. The "nintendo switch 2 games" search was
        # dropped after a live run showed it is almost entirely redundant:
        # 5 pages of each returned 422 rows but only 181 distinct products, and
        # page 1 of THIS url already carries NSW2 titles (Oblivion Remastered,
        # Ocarina of Time, Brigandine Abyss). Play-Asia tags most releases
        # "NSW, NSW2", so both searches return the same catalogue.
        #
        # The second URL therefore spent half the run's page budget re-reading
        # products the first had already found. Removing it converts that
        # budget into depth instead.
        search_urls=("https://www.play-asia.com/en/search/nintendo+switch+games",),
        note=(
            "First in the browser group so it claims a concurrency slot immediately. "
            "Search URLs carry no {p}, so paging is a numeric page-number click; INR "
            "reference currency and country are pinned via session cookies in its profile."
        ),
    ),
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
        id="gameland",
        name="GameLand",
        base_url="https://gameland.co.in",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # The /product-category/games/ path plus a platform FILTER, not the
        # platform landing page. The platform page is a superset: it returns
        # controllers, cases and consoles alongside cartridges, and while the
        # classifier drops those, they still cost pages of the walk and
        # unproductive pages are what ends it early.
        #
        # ?swoof=1 is the WOOF filter plugin's own marker. Without it the
        # pdt_type parameter is inert and the unfiltered category comes back.
        search_urls=(
            "https://gameland.co.in/product-category/games/page/{p}/?pdt_type=switch&swoof=1",
            "https://gameland.co.in/product-category/games/page/{p}/?pdt_type=switch-2&swoof=1",
        ),
        note=(
            "WooCommerce storefront whose Store API is not exposed, so it is scraped. Its "
            "profile reads condition from the whole card: pre-owned is a badge here, not "
            "part of the title."
        ),
    ),
    StoreConfig(
        id="gamepookie",
        name="GamePookie",
        base_url="https://www.gamepookie.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # No {p}, deliberately. This store has no pagination at all -- a
        # "Load more" button at the end of the grid is the only way forward,
        # confirmed live. The parameter WAS here and was inert: it produced a
        # valid-looking URL that returned page 1's products every time, which
        # reads as a working walk right up until the row count is compared
        # against the category's own.
        search_urls=(
            "https://www.gamepookie.com/category/nintendo-switch",
            "https://www.gamepookie.com/category/nintendo-switch-2",
        ),
        note=(
            "Wix storefront: no product API, but stable data-hook attributes. Paged by a "
            "'Load more' button, so pages 2+ are reached by clicking; its categories report "
            "roughly 88 Switch and 36 Switch 2 products."
        ),
    ),
    StoreConfig(
        id="cex_in",
        name="CeX India",
        base_url="https://in.webuy.com",
        kind=AdapterKind.BROWSER,
        currency="INR",
        tier=1,
        enabled=True,
        platform_hint=Platform.SWITCH,
        # 1038 = Switch Software, 1086 = Switch 2 Games. CeX's own numeric
        # category ids, which are stable across its regional sites.
        #
        # BROWSER rather than the /v3/boxes API this store is best known for:
        # that endpoint is behind Cloudflare for product searches, and the
        # public site is a client-rendered Nuxt/Algolia app, so the catalogue
        # only exists after its JavaScript runs.
        search_urls=(
            "https://in.webuy.com/search?categoryIds=1038&categoryName=Switch%20Software&page={p}",
            "https://in.webuy.com/search?categoryIds=1086&categoryName=Switch%202%20Games&page={p}",
        ),
        note=(
            "Pre-owned by business model, asserted in its profile rather than inferred -- CeX "
            "titles do not say so. Its selectors are UNVERIFIED first guesses: run 'Fix a "
            "broken store' against the rendered page before trusting a run."
        ),
    ),
)
