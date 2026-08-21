"""Detecting what each store actually speaks, and correcting the config.

Probe asks one question per store: what backend is this? Its answers go to
stores.local.json, never to the shipped list -- a tool must not rewrite the
source file it also imports.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from switch_tracker import paths
from switch_tracker.config import overrides
from switch_tracker.core.http import PoliteClient
from switch_tracker.core.models import AdapterKind, Platform, StoreConfig
from switch_tracker.services.probe import Finding, ProbeService

SHOPIFY_PATH = "/products.json"
WOO_V1 = "/wp-json/wc/store/v1/products"
WOO_LEGACY = "/wp-json/wc/store/products"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


@pytest.fixture
def service() -> ProbeService:
    return ProbeService(PoliteClient(min_gap_s=0.0, timeout_s=5.0, backoff_base_s=0.01))


def store_at(base: str, **kw) -> StoreConfig:
    cfg = StoreConfig(
        id="target",
        name="Target",
        base_url=base,
        kind=AdapterKind.SHOPIFY,
        currency="INR",
        tier=2,
        enabled=True,
        platform_hint=Platform.SWITCH,
        collections=("already-scoped",),
    )
    return replace(cfg, **kw)


def ok_json(body: str) -> tuple[int, str, dict[str, str]]:
    return (200, body, {"content-type": "application/json"})


class TestDetection:
    async def test_recognises_shopify(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, ok_json('{"products":[]}'))
        result = await service.detect(store_at(base))
        assert result is Finding.SHOPIFY

    async def test_recognises_woocommerce(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, ok_json('[{"prices":{"price":"100"}}]'))
        assert await service.detect(store_at(base)) is Finding.WOOCOMMERCE

    async def test_recognises_woocommerce_on_the_legacy_path(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, (404, "no", {}))
        recorder.plan(WOO_LEGACY, ok_json('[{"prices":{"price":"100"}}]'))
        assert await service.detect(store_at(base)) is Finding.WOOCOMMERCE

    async def test_distinguishes_a_locked_shopify_from_an_unknown_site(
        self, service, server, data_dir
    ) -> None:
        """Both need a browser adapter, but only one is worth re-probing later.

        A merchant can switch /products.json back on; a site that was never
        Shopify will not become Shopify.
        """
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, (404, "no", {}))
        recorder.plan(WOO_LEGACY, (404, "no", {}))
        recorder.plan("/", (200, "<html>cdn.shopify.com</html>", {}))
        assert await service.detect(store_at(base)) is Finding.SHOPIFY_LOCKED

    async def test_reports_an_unrecognised_site(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, (404, "no", {}))
        recorder.plan(WOO_LEGACY, (404, "no", {}))
        recorder.plan("/", (200, "<html>a plain shop</html>", {}))
        assert await service.detect(store_at(base)) is Finding.UNKNOWN_HTML

    async def test_reports_an_unreachable_store(self, service, data_dir) -> None:
        assert await service.detect(store_at("http://127.0.0.1:9")) is Finding.UNREACHABLE

    async def test_skips_stores_that_need_a_browser(self, service, data_dir) -> None:
        """There is no API for probe to detect on these."""
        result = await service.detect(store_at("http://127.0.0.1:9", kind=AdapterKind.BROWSER))
        assert result is None


class TestApplyingCorrections:
    async def test_writes_a_corrected_kind(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, ok_json('[{"prices":{"price":"1"}}]'))
        await service.run([store_at(base, id="designinfo")])
        assert overrides.read()["designinfo"]["kind"] == "WOOCOMMERCE"

    async def test_never_writes_a_kind_that_has_no_adapter(self, service, server, data_dir) -> None:
        """The bug that converted working stores into skipped ones.

        The original concluded JSON_API from the mere presence of ld+json on a
        homepage -- which nearly every shop publishes -- and there was no
        JSON_API adapter, so collect silently skipped those stores.
        """
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, (404, "no", {}))
        recorder.plan(WOO_V1, (404, "no", {}))
        recorder.plan(WOO_LEGACY, (404, "no", {}))
        recorder.plan("/", (200, '<html><script type="application/ld+json">{}</script></html>', {}))

        await service.run([store_at(base, id="mystery")])

        written = overrides.read().get("mystery", {})
        assert "kind" not in written
        assert written.get("enabled") is False

    async def test_disables_an_unreachable_store_with_a_readable_reason(
        self, service, data_dir
    ) -> None:
        await service.run([store_at("http://127.0.0.1:9", id="dead")])
        written = overrides.read()["dead"]
        assert written["enabled"] is False
        assert "unreachable" in written["note"].lower()

    async def test_leaves_a_correct_store_alone(self, service, server, data_dir) -> None:
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, ok_json('{"products":[]}'))
        await service.run([store_at(base, id="pssales", kind=AdapterKind.SHOPIFY)])
        assert "pssales" not in overrides.read()

    async def test_does_not_re_disable_an_already_disabled_store(
        self, service, data_dir
    ) -> None:
        """Otherwise every run rewrites the same correction forever."""
        await service.run([store_at("http://127.0.0.1:9", id="parked", enabled=False)])
        assert "parked" not in overrides.read()


class TestCategoryDiscovery:
    async def test_lists_categories_for_an_unscoped_store(self, service, server, data_dir) -> None:
        """Scoping a mixed-catalogue store should be a copy-paste, not an API trip."""
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, ok_json('{"products":[]}'))
        recorder.plan(
            "/collections.json",
            ok_json(json.dumps({"collections": [{"title": "Nintendo Switch", "handle": "nsw"}]})),
        )
        report = await service.run([store_at(base, collections=())])
        assert "nsw" in report.lines_for("target")

    async def test_surfaces_relevant_categories_first(self, service, server, data_dir) -> None:
        """A store can have 100+ categories with the one that matters buried
        alphabetically past any sane display cap."""
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, ok_json('{"products":[]}'))
        many = [{"title": f"Category {i}", "handle": f"c{i}"} for i in range(60)]
        many.append({"title": "Zebra Nintendo Switch Games", "handle": "switch-games"})
        recorder.plan("/collections.json", ok_json(json.dumps({"collections": many})))

        report = await service.run([store_at(base, collections=())])

        line = report.lines_for("target")
        # It sorts last of 61, and the display caps at 20 -- but it is the one
        # category anyone actually needs, so it survives the cap and leads.
        assert "switch-games" in line
        assert line.index("switch-games") < line.index("c0")
        assert "+41 more" in line

    async def test_skips_discovery_for_an_already_scoped_store(
        self, service, server, data_dir
    ) -> None:
        """A one-time aid, not a per-run cost."""
        base, recorder = server
        recorder.plan(SHOPIFY_PATH, ok_json('{"products":[]}'))
        await service.run([store_at(base, collections=("nintendo-switch",))])
        assert not any("collections.json" in hit for hit in recorder.hits)
