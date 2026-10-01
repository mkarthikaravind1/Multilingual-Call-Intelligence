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
