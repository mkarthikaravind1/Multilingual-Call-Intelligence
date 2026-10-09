"""Sign-in throttling and the bcrypt password-length limit."""

import pytest
from fastapi.testclient import TestClient

from app.ai.complaint.provider import ComplaintDetectionProvider
from app.ai.question.provider import QuestionSuggestionProvider
from app.ai.sentiment.provider import SentimentAnalysisProvider, SentimentLabel, SentimentResult
from app.api.app_factory import create_app
from app.api.wiring import build_api_services
from app.core.config import Settings
from app.domain.user import UserRole
from app.security.password import MAX_PASSWORD_BYTES, hash_password
from app.services.live_state_store import InMemoryLiveStateStore, RedisLiveStateStore
from app.services.login_throttle import LoginLimits, LoginThrottle
from app.services.user_management_service import UserManagementError

EMAIL = "agent@dealer.com"
PASSWORD = "correct-horse-battery"


# ---- The counter ----


def test_in_memory_counter_counts_and_expires():
    now = [0.0]
    store = InMemoryLiveStateStore(clock=lambda: now[0])

    assert [store.increment("k", 60) for _ in range(3)] == [1, 2, 3]
    now[0] = 59.0
    assert store.increment("k", 60) == 4  # the window runs from the first failure
    now[0] = 61.0
    assert store.increment("k", 60) == 1


class CountingRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expiry: dict[str, int] = {}

    def eval(self, script, numkeys, key, ttl):
        assert "incr" in script
        self.values[key] = self.values.get(key, 0) + 1
        if self.values[key] == 1:
            self.expiry[key] = int(ttl)
        return self.values[key]


def test_redis_counter_is_one_atomic_script_and_expires_from_the_first():
    redis = CountingRedis()
    store = RedisLiveStateStore(redis, key_prefix="t")  # type: ignore[arg-type]

    assert [store.increment("k", 900) for _ in range(2)] == [1, 2]
    assert redis.expiry == {"t:k": 900}


# ---- The throttle ----


def _throttle() -> LoginThrottle:
    return LoginThrottle(
        InMemoryLiveStateStore(),
        LoginLimits(max_failures_per_email=3, max_failures_per_address=5, window_seconds=60),
    )


def test_an_email_is_locked_after_its_failures_and_cleared_by_a_success():
    throttle = _throttle()
    for _ in range(2):
        throttle.failed(EMAIL, "1.1.1.1")
    assert not throttle.locked(EMAIL, "1.1.1.1")

    throttle.succeeded(EMAIL)
    for _ in range(3):
        throttle.failed(" Agent@Dealer.com ", "1.1.1.1")  # same account

    assert throttle.locked(EMAIL, "2.2.2.2")
    assert not throttle.locked("other@dealer.com", "2.2.2.2")


def test_an_address_guessing_many_accounts_is_locked():
    throttle = _throttle()
    for n in range(5):
        throttle.failed(f"user{n}@dealer.com", "1.1.1.1")

    assert throttle.locked("someone@dealer.com", "1.1.1.1")
    assert not throttle.locked("someone@dealer.com", "2.2.2.2")


def test_an_unreachable_store_does_not_lock_everyone_out():
    class Broken(InMemoryLiveStateStore):
        def get_json(self, key):
            raise ConnectionError("redis down")

    assert not LoginThrottle(Broken()).locked(EMAIL, "1.1.1.1")


def test_the_store_never_holds_the_email():
    store = InMemoryLiveStateStore()
    LoginThrottle(store).failed(EMAIL, None)

    assert all("agent" not in key for key in store._values)


# ---- The sign-in endpoint ----


class _Complaints(ComplaintDetectionProvider):
    def detect(self, conversation, learning_context=()):
        return []


class _Sentiment(SentimentAnalysisProvider):
    def analyze(self, conversation, learning_context=()):
        return SentimentResult(SentimentLabel.NEUTRAL, 0.5, "Calm.")


class _Questions(QuestionSuggestionProvider):
    def generate(self, context):
        return None


@pytest.fixture
def client():
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, login_max_failures_per_email=3, login_failure_window_seconds=600
    )
    services = build_api_services(_Complaints(), _Sentiment(), _Questions(), settings)
    services.auth.register(EMAIL, PASSWORD, UserRole.ICR)
    return TestClient(create_app(services))


def _login(client, password):
    return client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})


def test_sign_in_is_refused_after_too_many_failures_even_with_the_right_password(client):
    for _ in range(3):
        assert _login(client, "wrong-password").status_code == 401

    response = _login(client, PASSWORD)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "600"
    assert "Try again in 10 minutes" in response.json()["detail"]


def test_a_successful_sign_in_clears_earlier_failures(client):
    for _ in range(2):
        _login(client, "wrong-password")
    assert _login(client, PASSWORD).status_code == 200

    for _ in range(2):
        _login(client, "wrong-password")
    assert _login(client, PASSWORD).status_code == 200


# ---- bcrypt's 72-byte limit ----


def test_a_password_over_72_bytes_cannot_be_set():
    with pytest.raises(ValueError, match="at most 72 bytes"):
        hash_password("a" * (MAX_PASSWORD_BYTES + 1))
    # 25 Tamil letters are 75 bytes.
    with pytest.raises(ValueError):
        hash_password("க" * 25)
    assert hash_password("a" * MAX_PASSWORD_BYTES)


def test_admins_get_a_clear_message_for_a_too_long_password(client):
    users = client.app.state.services.user_management_service

    with pytest.raises(UserManagementError, match="at most 72 bytes"):
        users.create_user("new@dealer.com", "x" * 80, UserRole.ICR)


# ---- Sessions: a password reset ends them; refreshing has an end ----


def _token(client, password=PASSWORD):
    response = _login(client, password)
    assert response.status_code == 200
    return response.json()["access_token"]


def _me(client, token):
    # Any endpoint that needs a signed-in user.
    return client.get("/api/v1/calls", headers={"Authorization": f"Bearer {token}"})


def test_a_password_reset_signs_the_user_out_everywhere(client):
    import time as clock

    services = client.app.state.services
    old = _token(client)
    assert _me(client, old).status_code == 200

    user = services.user_repository.get_by_email(EMAIL)
    clock.sleep(1.1)  # tokens carry whole seconds
    services.user_management_service.reset_password(user.user_id, "a-new-password-1", user)

    assert _me(client, old).status_code == 401
    assert client.post(
        "/api/v1/auth/refresh", headers={"Authorization": f"Bearer {old}"}
    ).status_code == 401
    assert _me(client, _token(client, "a-new-password-1")).status_code == 200


def test_refreshing_keeps_the_sign_in_time_and_stops_after_the_maximum(client):
    import time as clock

    import jwt as pyjwt

    from app.core.config import get_settings
    from app.security.jwt import create_access_token

    user = client.app.state.services.user_repository.get_by_email(EMAIL)
    signed_in = int(clock.time()) - 3600
    fresh = client.post(
        "/api/v1/auth/refresh",
        headers={"Authorization": f"Bearer {create_access_token(user, auth_time=signed_in)}"},
    )
    assert fresh.status_code == 200
    claims = pyjwt.decode(
        fresh.json()["access_token"], get_settings().auth_secret_key, algorithms=["HS256"]
    )
    assert claims["auth_time"] == signed_in

    too_old = create_access_token(user, auth_time=int(clock.time()) - 13 * 3600)
    expired = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {too_old}"})
    assert expired.status_code == 401
    assert "sign in again" in expired.json()["detail"]


# ---- Timing does not reveal which emails have accounts ----


def test_an_unknown_email_takes_as_long_as_a_wrong_password():
    import statistics
    import time as clock

    from app.services.auth_service import AuthService, InvalidCredentialsError
    from app.domain.user_repository import InMemoryUserRepository

    auth = AuthService(InMemoryUserRepository())
    auth.register(EMAIL, PASSWORD, UserRole.ICR)

    def seconds(email):
        times = []
        for _ in range(3):
            started = clock.perf_counter()
            with pytest.raises(InvalidCredentialsError):
                auth.authenticate(email, "wrong-password")
            times.append(clock.perf_counter() - started)
        return statistics.median(times)

    seconds("nobody@dealer.com")  # the dummy hash is made once
    known, unknown = seconds(EMAIL), seconds("nobody@dealer.com")

    assert unknown > known * 0.5  # both check a bcrypt hash (before: ~0 s)
