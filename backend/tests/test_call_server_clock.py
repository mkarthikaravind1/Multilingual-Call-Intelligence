"""Call times set by the server's clock: the web app no longer sends the
PC's, which can be minutes off (and a phone call starts on the server's)."""

import json
import time

import pytest

from tests.test_call_customer import CRM, build_client


@pytest.fixture
def client(tmp_path):
    crm = tmp_path / "crm.json"
    crm.write_text(json.dumps(CRM), encoding="utf-8")
    return build_client(crm)[0]


def test_a_call_started_without_a_time_starts_now(client):
    before = time.time()

    body = client.post("/api/v1/calls", json={"call_id": "m-1", "start_time": None}).json()

    assert before <= body["start_time"] <= time.time()


def test_a_call_completed_without_a_time_ends_now(client):
    client.post("/api/v1/calls", json={"call_id": "m-1", "start_time": None})
    before = time.time()

    response = client.post("/api/v1/calls/m-1/complete", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert before <= body["end_time"] <= time.time()
    assert body["end_time"] >= body["start_time"]


def test_a_call_that_started_on_the_server_clock_ends_whatever_the_pc_clock_says(client):
    # As for a phone call: started by the server, ended from a browser. The
    # browser sends nothing, so its clock (here: it would be an hour slow)
    # plays no part.
    client.post("/api/v1/calls", json={"call_id": "m-1", "start_time": None})
    an_hour_slow = time.time() - 3600
    assert client.post("/api/v1/calls/m-1/complete", json={"end_time": an_hour_slow}).status_code != 200

    assert client.post("/api/v1/calls/m-1/complete", json={}).status_code == 200


def test_explicit_times_are_still_taken_as_given(client):
    assert client.post("/api/v1/calls", json={"call_id": "m-1"}).json()["start_time"] == 0.0
    client.post("/api/v1/calls", json={"call_id": "m-2", "start_time": 100.0})

    body = client.post("/api/v1/calls/m-2/complete", json={"end_time": 130.0}).json()

    assert (body["start_time"], body["end_time"]) == (100.0, 130.0)
