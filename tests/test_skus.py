"""Port-critical: SKU derivation is what makes price HISTORY accumulate.

listing has UNIQUE(store_id, sku). A stable SKU means the second run appends a
price_point to the same listing; an unstable one mints a brand-new listing
every run, so every series has length 1 and 'movers' is permanently empty --
with no error anywhere. This is the quietest way the project can fail.
"""

from __future__ import annotations

import pytest

from switch_tracker.core.skus import sku_from_url


class TestAmazon:
    def test_extracts_the_asin(self) -> None:
        """The ASIN is Amazon's stable product id; the rest of the URL is not."""
        assert sku_from_url("https://www.amazon.in/dp/B0CQNVQD9N") == "B0CQNVQD9N"

    def test_extracts_the_asin_from_a_titled_url(self) -> None:
        url = "https://www.amazon.in/Mario-Kart-World-Nintendo-Switch/dp/B0CQNVQD9N/"
        assert sku_from_url(url) == "B0CQNVQD9N"

    def test_ignores_tracking_parameters(self) -> None:
        url = "https://www.amazon.in/dp/B0CQNVQD9N?ref_=sr_1_3&qid=1787339967"
        assert sku_from_url(url) == "B0CQNVQD9N"


class TestFlipkart:
    def test_extracts_the_pid_parameter(self) -> None:
        url = "https://www.flipkart.com/mario-kart-world/p/itmabc123?pid=XYZ123ABC"
        assert sku_from_url(url) == "XYZ123ABC"


class TestFallback:
    def test_uses_the_last_path_segment(self) -> None:
        assert sku_from_url("https://nistore.in/product/mario-kart-world") == "mario-kart-world"

    def test_ignores_a_trailing_slash(self) -> None:
        assert sku_from_url("https://nistore.in/product/mario-kart-world/") == "mario-kart-world"

    def test_truncates_an_absurdly_long_segment(self) -> None:
        long_slug = "a" * 300
        assert sku_from_url(f"https://example.in/product/{long_slug}") == "a" * 120


class TestPrecedence:
    def test_asin_wins_when_both_an_asin_and_a_pid_are_present(self) -> None:
        url = "https://www.amazon.in/dp/B0CQNVQD9N?pid=SHOULD_NOT_WIN"
        assert sku_from_url(url) == "B0CQNVQD9N"


class TestStability:
    """The property the whole price history rests on."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.amazon.in/dp/B0CQNVQD9N",
            "https://www.flipkart.com/x/p/itm1?pid=XYZ123ABC",
            "https://nistore.in/product/mario-kart-world",
        ],
    )
    def test_the_same_url_always_yields_the_same_sku(self, url: str) -> None:
        assert sku_from_url(url) == sku_from_url(url)

    def test_query_parameters_do_not_change_the_sku(self) -> None:
        """Session ids and tracking params churn between runs.

        If they leaked into the SKU, every run would create a new listing and
        the price series would never grow past one point.
        """
        bare = sku_from_url("https://nistore.in/product/mario-kart-world")
        tracked = sku_from_url("https://nistore.in/product/mario-kart-world?utm_source=x&sid=99")
        assert bare == tracked

    def test_never_returns_empty(self) -> None:
        """An empty SKU would collide with every other empty SKU at the unique index."""
        assert sku_from_url("https://example.in/") != ""
