"""The dashboard, end to end.

Every capability is a control on this page: collect, check stores, update the
exchange rate, fix a broken store, reset corrections. Each one starts a
separate worker process and returns immediately.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from switch_tracker import paths
from switch_tracker.core import db
from switch_tracker.web import deps
from switch_tracker.web.app import create_app
from switch_tracker.web.runs import PidLock, RunLauncher

PAGE_HOST = "127.0.0.1:4173"
PAGE_ORIGIN = f"http://{PAGE_HOST}"


@pytest.fixture
def spawned() -> list[list[str]]:
    return []


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A schema-backed database with no app around it."""
    connection = db.connect(tmp_path / "plain.db")
    db.ensure_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawned) -> Iterator[TestClient]:
    monkeypatch.setenv("TRACKER_DATA_DIR", str(tmp_path))
    paths.data_dir.cache_clear()
    deps.reset()

    conn = db.connect(tmp_path / "tracker.db")
    db.ensure_schema(conn)

    import os

    def fake_spawn(command: list[str]) -> int:
        spawned.append(command)
        return os.getpid()  # a real spawn returns a LIVE process

    launcher = RunLauncher(conn, PidLock(tmp_path / "run.lock"), spawn=fake_spawn)

    app = create_app(4173)
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_launcher] = lambda: launcher

    # Exactly what the real dashboard page sends: its own Host, and its own
    # Origin on every request. No switch turns the guard off for tests.
    with TestClient(app, base_url=f"http://{PAGE_HOST}", headers={"Origin": PAGE_ORIGIN}) as test_client:
        yield test_client

    deps.reset()
    paths.data_dir.cache_clear()


class TestDashboardPage:
    def test_serves_the_shell(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "Switch cartridge prices" in response.text

    def test_offers_every_capability_as_a_control(self, client: TestClient) -> None:
        """No terminal menu -- everything is driven from this page."""
        body = client.get("/").text
        for action in ("collect", "probe", "fx", "reset-corrections"):
            assert f'data-action="{action}"' in body

    def test_offers_the_broken_store_picker(self, client: TestClient) -> None:
        assert 'id="fixStore"' in client.get("/").text

    def test_serves_its_script_from_disk_not_a_cdn(self, client: TestClient) -> None:
        """An offline exe pointing at a CDN loses all interactivity, silently.

        (Was a check on a vendored htmx.min.js, removed: loaded on every page,
        used by nothing. app.js is now the only script, and the rule is the same.)
        """
        body = client.get("/").text
        assert "/static/app.js" in body
        assert "cdn." not in body and "unpkg" not in body and "://" not in body.split("<body>")[0]
        assert client.get("/static/app.js").status_code == 200


class TestDataEndpoints:
    def test_summary_works_on_an_empty_database(self, client: TestClient) -> None:
        assert client.get("/api/summary").json()["listings"] == 0

    def test_health_reports_no_run_yet(self, client: TestClient) -> None:
        assert client.get("/api/health").json()["run"] is None

    def test_listings_paginates(self, client: TestClient) -> None:
        payload = client.get("/api/listings?limit=10").json()
        assert payload["limit"] == 10
        assert payload["total"] == 0

    def test_rejects_an_out_of_range_limit(self, client: TestClient) -> None:
        assert client.get("/api/listings?limit=9999").status_code == 422

    def test_history_answers_for_a_listing_with_no_points(self, client: TestClient) -> None:
        assert client.get("/api/history?id=1").json() == []

    def test_games_works_on_an_empty_database(self, client: TestClient) -> None:
        assert client.get("/api/games?sort=offers&dir=desc").json()["total"] == 0

    def test_a_game_key_narrows_every_view_to_that_games_offers(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        """What clicking a watched game shows: its offers, at every shop, and nothing else."""
        from switch_tracker.core import matcher

        seed = db.connect(tmp_path / "tracker.db")
        seed.execute("INSERT INTO store VALUES ('a','A','https://a','SHOPIFY','INR',2,1)")
        seed.execute("INSERT INTO store VALUES ('b','B','https://b','SHOPIFY','INR',2,1)")
        titles = [
            (1, "a", "Tales of Vesperia Definitive Edition(tbd)"),
            (2, "b", "NSW™, NSW2™ Tales of Vesperia [Definitive Edition] (Europe)"),
            (3, "b", "Hades - Nintendo Switch"),
        ]
        for lid, store, title in titles:
            seed.execute(
                "INSERT INTO listing (id, store_id, sku, url, raw_title, platform, region,"
                " first_seen, last_seen) VALUES (?, ?, ?, 'https://x', ?, 'SWITCH', 'IN', 't', 't')",
                (lid, store, f"s{lid}", title),
            )
            seed.execute("INSERT OR IGNORE INTO run (id, started_at, finished_at) VALUES (1, 't', 't')")
            seed.execute(
                "INSERT INTO price_point (listing_id, run_id, captured_at, native_currency, native_price,"
                " inr_price, in_stock) VALUES (?, 1, 't', 'INR', 3000, 3000, 1)",
                (lid,),
            )
        matcher.rematch(seed)
        seed.close()

        key = "game=tales+vesperia+definitive&platform=SWITCH"
        assert [r["game"] for r in client.get(f"/api/games?{key}").json()["rows"]] == [
            "tales vesperia definitive"
        ]
        assert client.get(f"/api/listings?{key}").json()["total"] == 2
        stores = {s["id"]: s["n"] for s in client.get(f"/api/facets?{key}").json()["stores"]}
        assert stores == {"a": 1, "b": 1}  # Hades' store-b offer isn't counted

    def test_facets_take_the_listing_filters(self, client: TestClient) -> None:
        r = client.get("/api/facets?q=x&platform=SWITCH2&store=a,b&region=JP&condition=NEW&in_stock=true")
        assert r.status_code == 200
        assert r.json()["stores"] == []


class TestCrossSiteGuard:
    """Any page the user visits can make the browser POST here, and a rebound
    hostname can READ here. Both must be refused before anything runs."""

    @pytest.mark.parametrize(
        "origin",
        [
            "https://evil.example",
            "null",
            "",
            "http://127.0.0.1:9999",  # wrong port
            "https://127.0.0.1:4173",  # wrong scheme
            "http://127.0.0.1:4173.evil.com",  # suffix trick
            "http://127.0.0.1:4173/",  # not an exact origin
            "http://localhost:4173",  # valid host, but not THIS request's host
        ],
    )
    def test_a_foreign_origin_cannot_start_a_run(self, client: TestClient, spawned, origin: str) -> None:
        response = client.post("/actions/collect", headers={"Origin": origin})
        assert response.status_code == 403
        assert spawned == []  # nothing ran
        assert "error" in response.json()

    def test_a_foreign_origin_cannot_touch_the_watchlist(self, client: TestClient) -> None:
        item = {"game": "x", "platform": "SWITCH", "target": 1}
        assert (
            client.put("/api/watchlist", json=item, headers={"Origin": "https://evil.example"}).status_code
            == 403
        )
        assert not paths.watchlist_path().exists()

    def test_a_cross_site_fetch_is_refused_even_with_a_matching_origin(
        self, client: TestClient, spawned
    ) -> None:
        response = client.post("/actions/collect", headers={"Sec-Fetch-Site": "cross-site"})
        assert response.status_code == 403 and spawned == []

    def test_the_page_itself_still_works_on_both_addresses(self, client: TestClient, spawned) -> None:
        assert client.post("/actions/fx").status_code == 200  # 127.0.0.1 + its own Origin
        response = client.post(
            "/actions/probe",
            headers={
                "Host": "localhost:4173",
                "Origin": "http://localhost:4173",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        assert response.status_code != 403

    def test_a_rebound_hostname_cannot_read_the_api(self, client: TestClient) -> None:
        assert client.get("/api/summary", headers={"Host": "evil.example:4173"}).status_code == 403
        assert client.get("/", headers={"Host": "evil.example:4173"}).status_code == 403

    def test_a_plain_navigation_with_no_origin_is_fine(self, client: TestClient) -> None:
        assert client.get("/api/summary", headers={"Origin": ""}).status_code == 200

    def test_a_forged_post_to_an_unknown_path_gets_403_not_404(self, client: TestClient) -> None:
        assert (
            client.post("/actions/nonexistent", headers={"Origin": "https://evil.example"}).status_code == 403
        )

    def test_never_grants_cors(self, client: TestClient) -> None:
        for response in (client.get("/api/summary"), client.options("/api/summary")):
            assert "access-control-allow-origin" not in response.headers

    def test_every_state_changing_route_is_guarded(self, client: TestClient, spawned) -> None:
        """Walks every route, so a route added later is covered by default.

        Via the OpenAPI schema rather than ``app.routes``: this FastAPI nests
        included routers, so a flat walk of ``app.routes`` sees none of them
        and the test would pass while checking nothing.
        """
        changing = [
            (method.upper(), path.replace("{store_id}", "nistore"))
            for path, operations in create_app(4173).openapi()["paths"].items()
            for method in operations
            if method.upper() not in {"GET", "HEAD", "OPTIONS"}
        ]
        assert len(changing) >= 7  # the 5 actions + watchlist PUT and DELETE
        for method, path in changing:
            response = client.request(method, path, headers={"Origin": "https://evil.example"})
            assert response.status_code == 403, (method, path)
        assert spawned == []


class TestGuardRules:
    """The decision itself, including the cases a real HTTP client cannot send."""

    hosts = frozenset({"127.0.0.1:4173", "localhost:4173"})

    def test_a_missing_origin_on_a_post_is_refused(self) -> None:
        from switch_tracker.web.guard import check

        assert check("POST", {"host": "127.0.0.1:4173"}, self.hosts) is not None

    def test_a_missing_or_portless_host_is_refused(self) -> None:
        from switch_tracker.web.guard import check

        assert check("GET", {}, self.hosts) is not None
        assert check("GET", {"host": "127.0.0.1"}, self.hosts) is not None

    def test_on_port_80_the_portless_host_a_browser_sends_is_allowed(self) -> None:
        """Browsers drop the default port, so the page sends Host: 127.0.0.1."""
        from switch_tracker.web.guard import allowed_hosts, check

        hosts = allowed_hosts(80)
        assert check("POST", {"host": "127.0.0.1", "origin": "http://127.0.0.1"}, hosts) is None
        assert check("GET", {"host": "evil.example"}, hosts) is not None
        # ...and only on 80: elsewhere a portless Host is still refused.
        assert check("GET", {"host": "127.0.0.1"}, allowed_hosts(4173)) is not None

    def test_host_and_origin_compare_case_insensitively(self) -> None:
        from switch_tracker.web.guard import check

        headers = {"host": "LOCALHOST:4173", "origin": "http://localhost:4173"}
        assert check("POST", headers, self.hosts) is None


class TestWatchlist:
    def test_add_retarget_and_remove(self, client: TestClient) -> None:
        item = {"game": "metroid prime 4 beyond", "platform": "SWITCH", "target": 4000}
        assert [w["target"] for w in client.put("/api/watchlist", json=item).json()] == [4000]
        retarget = {**item, "target": 3500}
        assert [w["target"] for w in client.put("/api/watchlist", json=retarget).json()] == [3500]
        assert (
            client.delete("/api/watchlist", params={"game": item["game"], "platform": "SWITCH"}).json() == []
        )

    def test_retargeting_keeps_a_new_only_setting(self, client: TestClient) -> None:
        """The target box sends no condition; that must not reset New-only to Any."""
        client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "condition": "NEW"})
        [item] = client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": 3000}).json()
        assert (item["condition"], item["target"]) == ("NEW", 3000)

    def test_the_toggle_keeps_the_target_and_an_explicit_null_clears_it(self, client: TestClient) -> None:
        """The toggle sends no target, so it cannot race a target edit and restore the old price."""
        client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": 3000})
        [kept] = client.put(
            "/api/watchlist", json={"game": "x", "platform": "SWITCH", "condition": "NEW"}
        ).json()
        assert (kept["target"], kept["condition"]) == (3000, "NEW")
        [cleared] = client.put(
            "/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": None}
        ).json()
        assert (cleared["target"], cleared["condition"]) == (None, "NEW")

    def test_a_hand_edited_duplicate_does_not_survive_an_update(self, client: TestClient) -> None:
        paths.watchlist_path().write_text(
            '[{"game": "x", "platform": "SWITCH", "target": 1},'
            ' {"game": "x", "platform": "SWITCH", "target": 2}]',
            encoding="utf-8",
        )
        entries = client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": 9}).json()
        assert [e["target"] for e in entries] == [9]

    def test_an_entry_written_before_conditions_existed_reads_as_any(self, client: TestClient) -> None:
        paths.watchlist_path().write_text(
            '[{"game": "x", "platform": "SWITCH", "target": 1}]', encoding="utf-8"
        )
        assert client.get("/api/watchlist").json()[0]["condition"] == "ANY"

    def test_the_shops_toggle_and_the_other_controls_never_overwrite_each_other(
        self, client: TestClient
    ) -> None:
        client.put(
            "/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": 3000, "condition": "NEW"}
        )
        [item] = client.put(
            "/api/watchlist", json={"game": "x", "platform": "SWITCH", "shops": "INDIA"}
        ).json()
        assert (item["target"], item["condition"], item["shops"]) == (3000, "NEW", "INDIA")
        [item] = client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "target": 2500}).json()
        assert (item["target"], item["shops"]) == (2500, "INDIA")

    def test_an_entry_written_before_the_shops_toggle_reads_as_all(self, client: TestClient) -> None:
        paths.watchlist_path().write_text(
            '[{"game": "x", "platform": "SWITCH", "target": 1}]', encoding="utf-8"
        )
        assert client.get("/api/watchlist").json()[0]["shops"] == "ALL"

    def test_rejects_an_unknown_shops_value(self, client: TestClient) -> None:
        response = client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "shops": "ASIA"})
        assert response.status_code == 422

    def test_rejects_an_unknown_condition(self, client: TestClient) -> None:
        response = client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH", "condition": "USED"})
        assert response.status_code == 422

    def test_is_stored_in_the_data_dir_so_it_survives_a_deleted_database(self, client: TestClient) -> None:
        client.put("/api/watchlist", json={"game": "kirby", "platform": "SWITCH2", "target": None})
        assert "kirby" in paths.watchlist_path().read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "bad",
        [
            {"game": "", "platform": "SWITCH"},
            {"game": "x", "platform": "PS5"},
            {"game": "x", "platform": "SWITCH", "target": -1},
        ],
    )
    def test_rejects_malformed_items(self, client: TestClient, bad: dict) -> None:
        assert client.put("/api/watchlist", json=bad).status_code == 422

    def test_a_hand_edited_non_numeric_target_reads_as_no_target(self, client: TestClient) -> None:
        """The file is hand-editable. A string target must not 500 the whole list."""
        paths.watchlist_path().write_text(
            '[{"game": "x", "platform": "SWITCH", "target": "4000"}, {"game": 7, "platform": "SWITCH"}]',
            encoding="utf-8",
        )
        response = client.get("/api/watchlist")
        assert response.status_code == 200
        assert [(w["game"], w["target"]) for w in response.json()] == [("x", None)]

    def test_valid_json_that_is_not_a_list_is_also_set_aside(self, client: TestClient) -> None:
        paths.watchlist_path().write_text('{"hand": "edited"}', encoding="utf-8")
        client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH"})
        assert "hand" in _set_aside()[0].read_text(encoding="utf-8")

    def test_a_second_bad_edit_never_overwrites_the_first(self, client: TestClient) -> None:
        for text in ("{first", "{second"):
            paths.watchlist_path().write_text(text, encoding="utf-8")
            client.put("/api/watchlist", json={"game": text, "platform": "SWITCH"})
        assert sorted(p.read_text(encoding="utf-8") for p in _set_aside()) == ["{first", "{second"]

    def test_the_list_is_capped(self, client: TestClient) -> None:
        from switch_tracker.web import watchlist

        for i in range(watchlist.MAX_ITEMS):
            watchlist.upsert(f"game {i}", "SWITCH", None)
        response = client.put("/api/watchlist", json={"game": "one too many", "platform": "SWITCH"})
        assert response.status_code == 400 and "limited" in response.json()["error"]
        # Retargeting an EXISTING entry is not an addition, so it still works.
        assert (
            client.put(
                "/api/watchlist", json={"game": "game 0", "platform": "SWITCH", "target": 9}
            ).status_code
            == 200
        )

    def test_concurrent_adds_lose_nothing(self, client: TestClient) -> None:
        """Sync endpoints run on a thread pool: unlocked read-modify-write dropped entries."""
        from concurrent.futures import ThreadPoolExecutor

        from switch_tracker.web import watchlist

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: watchlist.upsert(f"game {i}", "SWITCH", None), range(40)))
        assert len(watchlist.read()) == 40

    def test_a_corrupt_file_is_set_aside_not_overwritten(self, client: TestClient) -> None:
        paths.watchlist_path().write_text("[{hand-edited, broken", encoding="utf-8")
        client.put("/api/watchlist", json={"game": "x", "platform": "SWITCH"})
        assert _set_aside()[0].read_text(encoding="utf-8").startswith("[{hand")


def _set_aside() -> list[Path]:
    """Watchlist files moved aside as unreadable, oldest first."""
    return sorted(paths.watchlist_path().parent.glob("watchlist.local.json.bad-*"))


class TestErrorResponses:
    def test_a_crash_does_not_leak_its_detail_to_the_page(self, tmp_path: Path) -> None:
        """Exception text carries local paths; the page gets a generic message."""
        import asyncio

        from starlette.requests import Request

        from switch_tracker.web.errors import json_error_handler

        secret = r"C:\Users\someone\AppData\Local\switch-tracker\tracker.db"
        request = Request(
            {"type": "http", "method": "GET", "path": "/api/x", "headers": [], "query_string": b""}
        )
        response = asyncio.run(json_error_handler(request, OSError(f"cannot open {secret}")))
        assert response.status_code == 500
        assert secret not in response.body.decode() and "OSError" in response.body.decode()


class TestActions:
    def test_collect_starts_a_worker_and_returns_immediately(self, client, spawned) -> None:
        response = client.post("/actions/collect")
        assert response.status_code == 200
        assert response.json()["run_id"] == 1
        assert "collect" in spawned[0]

    def test_a_second_collect_is_refused_rather_than_queued(self, client) -> None:
        """The web-UI form of the double-Enter trap.

        A refresh, a second tab and a double-click all reach this.
        """
        client.post("/actions/collect")
        second = client.post("/actions/collect")
        assert second.status_code == 409
        assert "already going" in second.json()["error"]

    def test_probe_and_fx_are_the_same_mechanism(self, client, spawned) -> None:
        assert client.post("/actions/probe").status_code == 200
        assert "probe" in spawned[0]

    def test_inspect_opens_a_named_store(self, client, spawned) -> None:
        assert client.post("/actions/inspect/amazon_in").status_code == 200
        assert "inspect" in spawned[0]
        assert "amazon_in" in spawned[0]

    def test_inspect_rejects_an_unknown_store(self, client) -> None:
        assert client.post("/actions/inspect/not_a_store").status_code == 404

    def test_reset_corrections_needs_no_worker(self, client, spawned) -> None:
        assert client.post("/actions/reset-corrections").status_code == 200
        assert spawned == []


class TestProgressStream:
    def test_replays_a_finished_run_and_closes(self, client, spawned) -> None:
        """A tab opened AFTER a run finished must still see what happened."""
        run_id = client.post("/actions/collect").json()["run_id"]

        # Write through the same connection the app is reading from.
        app_conn: sqlite3.Connection = client.app.dependency_overrides[deps.get_conn]()
        from switch_tracker.events.writer import EventWriter

        writer = EventWriter(app_conn, run_id)
        writer.page("nistore", page=1, count=42)
        writer.run_finished()

        with client.stream("GET", f"/api/runs/{run_id}/events?request_from=0") as stream:
            body = "".join(stream.iter_text())

        assert "store_progress" in body
        assert '"count": 42' in body
        assert "run_finished" in body

    def test_resumes_from_a_cursor(self, client) -> None:
        run_id = client.post("/actions/collect").json()["run_id"]
        app_conn = client.app.dependency_overrides[deps.get_conn]()
        from switch_tracker.events.writer import EventWriter

        writer = EventWriter(app_conn, run_id)
        writer.page("a", page=1, count=1)
        writer.page("b", page=2, count=2)
        writer.run_finished()

        with client.stream("GET", f"/api/runs/{run_id}/events?request_from=1") as stream:
            body = "".join(stream.iter_text())

        assert '"store_id": "a"' not in body
        assert '"store_id": "b"' in body


class TestFirstRunGuidance:
    """Collecting before checking stores is the classic first-run mistake.

    The shipped store kinds are hypotheses -- most were wrong when this was
    last run against live sites -- so a collection before probe produces a
    wall of failures that read as broken code rather than uncorrected config.
    """

    def test_tells_a_new_user_to_check_stores_first(self, client: TestClient) -> None:
        assert "Start with" in client.get("/").text

    def test_leads_with_check_stores_before_anything_has_been_probed(self, client: TestClient) -> None:
        body = client.get("/").text
        assert '<button class="primary" data-action="probe">' in body

    def test_leads_with_collect_once_the_stores_have_been_checked(self, client: TestClient) -> None:
        from switch_tracker.config import overrides

        overrides.set_override("nistore", note="corrected by probe")
        body = client.get("/").text
        assert '<button class="primary" data-action="collect">' in body
        assert "Start with" not in body


class TestLaunchCollectDecision:
    """Opening the dashboard bootstraps an empty database -- once.

    It used to collect on EVERY launch, so simply opening the app to read
    yesterday's prices spent several minutes scraping fourteen shops nobody
    had asked it to scrape.
    """

    @staticmethod
    def _decide(**kw: object):  # type: ignore[no-untyped-def]
        from switch_tracker.web.app import launch_collect_decision

        base = {"configured": True, "override": None, "probed": True, "already_collected": False}
        return launch_collect_decision(**{**base, **kw})  # type: ignore[arg-type]

    def test_collects_on_a_probed_but_empty_database(self) -> None:
        assert self._decide().collect is True

    def test_does_not_collect_once_history_exists(self) -> None:
        decision = self._decide(already_collected=True)
        assert decision.collect is False
        assert "Collect prices" in (decision.message or "")

    def test_does_not_collect_before_the_stores_have_been_checked(self) -> None:
        decision = self._decide(probed=False)
        assert decision.collect is False
        assert "Check stores" in (decision.message or "")

    def test_the_probe_gate_is_reported_even_when_history_exists(self) -> None:
        """An unprobed store list is the more actionable of the two messages."""
        decision = self._decide(probed=False, already_collected=True)
        assert decision.collect is False
        assert "Check stores" in (decision.message or "")

    def test_the_setting_suppresses_even_the_bootstrap_run(self) -> None:
        decision = self._decide(configured=False)
        assert decision.collect is False
        assert decision.message is None

    def test_an_explicit_override_beats_the_setting_in_both_directions(self) -> None:
        assert self._decide(configured=False, override=True).collect is True
        assert self._decide(configured=True, override=False).collect is False

    def test_an_explicit_request_still_respects_the_once_only_rule(self) -> None:
        """--no-collect exists; there is no flag meaning "scrape again".

        Overriding the SETTING must not also override the state-derived gate,
        or the flag quietly becomes a way to re-scrape on every launch.
        """
        assert self._decide(override=True, already_collected=True).collect is False


class TestHasEverCollected:
    def test_false_on_a_fresh_database(self, conn: sqlite3.Connection) -> None:
        from switch_tracker.web import queries

        assert queries.has_ever_collected(conn) is False

    def test_a_probe_run_alone_does_not_count_as_collecting(self, conn: sqlite3.Connection) -> None:
        """probe, fx and inspect all create a `run` row but never a run_store row.

        Asking the `run` table instead would tell a user who has only pressed
        "Check stores" that they had already collected, and silently skip the
        bootstrap run they actually needed.
        """
        from switch_tracker.core.db import now_iso
        from switch_tracker.web import queries

        conn.execute("INSERT INTO run (started_at, finished_at) VALUES (?, ?)", (now_iso(), now_iso()))
        assert queries.has_ever_collected(conn) is False

    def test_true_once_a_collection_has_recorded_a_store(self, conn: sqlite3.Connection) -> None:
        from switch_tracker.core.db import now_iso
        from switch_tracker.web import queries

        cursor = conn.execute("INSERT INTO run (started_at) VALUES (?)", (now_iso(),))
        conn.execute(
            "INSERT INTO store (id, name, base_url, kind, currency, tier, enabled) "
            "VALUES ('s1', 'S', 'https://s.test', 'SHOPIFY', 'INR', 2, 1)"
        )
        conn.execute(
            "INSERT INTO run_store (run_id, store_id, status, listings_found, duration_ms) "
            "VALUES (?, 's1', 'ok', 3, 10)",
            (cursor.lastrowid,),
        )
        assert queries.has_ever_collected(conn) is True


class TestSubsetCollection:
    """POST /actions/collect, with and without a selection."""

    def test_no_selection_launches_exactly_the_old_command(
        self, client: TestClient, spawned: list[list[str]]
    ) -> None:
        """The all-stores path must not gain an argv token it did not have."""
        assert client.post("/actions/collect").status_code == 200
        assert "--only" not in spawned[-1], spawned[-1]

    def test_a_selection_is_forwarded_to_the_worker(
        self, client: TestClient, spawned: list[list[str]]
    ) -> None:
        response = client.post("/actions/collect", params={"only": "playasia,e2zstore"})
        assert response.status_code == 200
        command = spawned[-1]
        assert "--only" in command
        assert command[command.index("--only") + 1] == "playasia,e2zstore"

    def test_whitespace_and_empty_entries_are_tolerated(
        self, client: TestClient, spawned: list[list[str]]
    ) -> None:
        response = client.post("/actions/collect", params={"only": " playasia , ,e2zstore "})
        assert response.status_code == 200
        assert spawned[-1][-1] == "playasia,e2zstore"

    def test_an_all_whitespace_selection_means_every_store(
        self, client: TestClient, spawned: list[list[str]]
    ) -> None:
        """Not a 404: it parses to an empty selection, which means "everything"."""
        assert client.post("/actions/collect", params={"only": " , "}).status_code == 200
        assert "--only" not in spawned[-1]

    def test_an_unknown_store_is_rejected_before_a_run_exists(
        self, client: TestClient, conn: sqlite3.Connection, spawned: list[list[str]]
    ) -> None:
        """A typo must not occupy the single active-run slot."""
        before = len(spawned)
        response = client.post("/actions/collect", params={"only": "playasia,ghost"})
        assert response.status_code == 404
        assert "ghost" in response.json()["error"]
        assert len(spawned) == before, "a worker was spawned for an invalid selection"

    def test_a_disabled_store_may_still_be_selected(
        self, client: TestClient, spawned: list[list[str]]
    ) -> None:
        """zozila ships disabled; naming it explicitly is the whole feature."""
        response = client.post("/actions/collect", params={"only": "zozila"})
        assert response.status_code == 200
        assert spawned[-1][-1] == "zozila"

    def test_a_second_run_is_refused_while_one_is_active(self, client: TestClient) -> None:
        assert client.post("/actions/collect", params={"only": "playasia"}).status_code == 200
        second = client.post("/actions/collect", params={"only": "e2zstore"})
        assert second.status_code == 409


class TestAssetCacheBusting:
    """A cached app.js against fresh markup is close to undiagnosable.

    index.html is rendered per request, so a template change is live at once.
    app.js is a static file, so a browser holding yesterday's copy runs the OLD
    script against the NEW page. The observed symptom was checkboxes that
    ticked and a button that never enabled -- no error, nothing in the console,
    and the server-side code entirely correct.
    """

    def test_the_page_versions_its_script_and_stylesheet(self, client: TestClient) -> None:
        from switch_tracker import resources

        body = client.get("/").text
        version = resources.asset_version()
        assert f"/static/app.js?v={version}" in body
        assert f"/static/app.css?v={version}" in body

    def test_the_version_is_not_a_constant(self) -> None:
        """A hard-coded token would defeat the whole mechanism."""
        from switch_tracker import resources

        assert resources.asset_version() not in ("", "0", "1")


class TestListingFilterEncoding:
    """?store=a,b reaches the query as a two-tuple.

    Same comma encoding as /actions/collect?only=a,b, so the app has one way to
    spell "a set of ids" rather than two conventions for the same idea.
    """

    @staticmethod
    def _captured(client: TestClient, monkeypatch, **params):  # type: ignore[no-untyped-def]
        from switch_tracker.web import queries
        from switch_tracker.web.routers import data

        seen = {}

        def spy(conn, query):  # type: ignore[no-untyped-def]
            seen["query"] = query
            return {"total": 0, "rows": [], "offset": 0, "limit": 100}

        monkeypatch.setattr(data.queries, "listings", spy)
        assert client.get("/api/listings", params=params).status_code == 200
        assert isinstance(seen["query"], queries.ListingQuery)
        return seen["query"]

    def test_a_comma_separated_store_becomes_a_tuple(self, client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        q = self._captured(client, monkeypatch, store="amazon_in,playasia")
        assert q.stores == ("amazon_in", "playasia")

    def test_a_single_store_still_works(self, client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Bookmarked single-value URLs must not break."""
        q = self._captured(client, monkeypatch, store="amazon_in")
        assert q.stores == ("amazon_in",)

    def test_regions_work_the_same_way(self, client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        q = self._captured(client, monkeypatch, region="IN,JP")
        assert q.regions == ("IN", "JP")

    def test_absent_and_empty_both_mean_no_filter(self, client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        assert self._captured(client, monkeypatch).stores == ()
        assert self._captured(client, monkeypatch, store="", region=" , ").regions == ()

    def test_platform_and_condition_stay_single_valued(self, client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """Their controls are three-way segments where option one means "all"."""
        q = self._captured(client, monkeypatch, platform="SWITCH2", condition="NEW")
        assert (q.platform, q.condition) == ("SWITCH2", "NEW")
