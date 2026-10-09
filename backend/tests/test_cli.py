import pytest

from app import cli


def test_reset_data_keeps_users_and_clears_call_data():
    tables = cli.tables_to_reset()

    assert "users" not in tables
    for name in ("conversations", "utterances", "escalations", "learning_evidence", "active_improvements"):
        assert name in tables


def test_reset_data_refuses_in_production(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, app_env="production"))  # type: ignore[call-arg]
    monkeypatch.setattr(cli, "build_engine", lambda settings: pytest.fail("must not touch the database"))

    with pytest.raises(SystemExit, match="production"):
        cli.main(["reset-data", "--yes"])


def test_reset_data_stops_without_confirmation(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    monkeypatch.setattr(cli, "build_engine", lambda settings: pytest.fail("must not touch the database"))

    with pytest.raises(SystemExit, match="Cancelled"):
        cli.main(["reset-data"])


@pytest.mark.parametrize("email", ["sup@example.test", "sup@dealer.local", "not-an-email"])
def test_create_user_refuses_emails_the_login_page_rejects(monkeypatch, email):
    class NoUsers:
        def create_user(self, *args):
            pytest.fail("must not create the user")

    monkeypatch.setattr(cli, "_service", NoUsers)
    monkeypatch.setenv("TEST_PASSWORD", "a-long-test-password")

    with pytest.raises(SystemExit, match="cannot be used to sign in"):
        cli.main(["create-user", "--email", email, "--password-env", "TEST_PASSWORD"])


def test_create_user_accepts_a_normal_email(monkeypatch, capsys):
    created = []

    class Users:
        def create_user(self, email, password, role):
            created.append(email)
            return type("U", (), {"email": email, "role": role, "user_id": "u-1"})()

    monkeypatch.setattr(cli, "_service", Users)
    monkeypatch.setenv("TEST_PASSWORD", "a-long-test-password")

    cli.main(["create-user", "--email", " sup@dealer.com ", "--password-env", "TEST_PASSWORD"])

    assert created == ["sup@dealer.com"]
