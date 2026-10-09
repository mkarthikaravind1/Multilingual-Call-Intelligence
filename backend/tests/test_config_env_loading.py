from pathlib import Path

from app.core import config
from app.core.config import ENV_FILE, Settings


def test_env_file_is_absolute_project_root_env(monkeypatch):
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    env_file = config._env_file()

    assert env_file is not None and env_file.is_absolute()
    assert env_file.name == ".env"
    assert env_file.parent / "backend" / "app" / "core" / "config.py" == Path(
        config.__file__
    ).resolve()


def test_app_env_file_chooses_another_file_or_none(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / "other.env"))
    assert config._env_file() == tmp_path / "other.env"

    monkeypatch.setenv("APP_ENV_FILE", "")
    assert config._env_file() is None


def test_tests_read_no_env_file():
    # tests/conftest.py sets APP_ENV_FILE empty before the app is imported.
    assert ENV_FILE is None
    assert Settings.model_config.get("env_file") is None


def test_env_file_path_does_not_depend_on_cwd(tmp_path, monkeypatch):
    before = ENV_FILE
    monkeypatch.chdir(tmp_path)
    assert config.ENV_FILE == before
    assert Settings.model_config.get("env_file") == before


def test_settings_loads_env_file_regardless_of_cwd(tmp_path, monkeypatch):
    env_file = tmp_path / "root" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("APP_ENV=from_root_env\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.chdir(elsewhere)

    assert Settings(_env_file=env_file).app_env == "from_root_env" # type: ignore