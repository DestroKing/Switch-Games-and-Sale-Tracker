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

    app = create_app()
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_launcher] = lambda: launcher

    with TestClient(app) as test_client:
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

    def test_serves_htmx_from_disk_not_a_cdn(self, client: TestClient) -> None:
        """An offline exe pointing at a CDN loses all interactivity, silently."""
        body = client.get("/").text
        assert "/static/htmx.min.js" in body
        assert "cdn." not in body and "unpkg" not in body
        assert client.get("/static/htmx.min.js").status_code == 200


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

    def test_history_is_available_even_though_no_page_calls_it_yet(self, client: TestClient) -> None:
        assert client.get("/api/history?id=1").json() == []


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

    def test_leads_with_check_stores_before_anything_has_been_probed(
        self, client: TestClient
    ) -> None:
        body = client.get("/").text
        assert '<button class="primary" data-action="probe">' in body

    def test_leads_with_collect_once_the_stores_have_been_checked(
        self, client: TestClient
    ) -> None:
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

