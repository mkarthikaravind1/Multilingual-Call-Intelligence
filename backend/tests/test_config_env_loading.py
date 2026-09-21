from pathlib import Path

from app.core import config
from app.core.config import ENV_FILE, Settings


def test_env_file_is_absolute_project_root_env():
    assert ENV_FILE.is_absolute()
    assert ENV_FILE.name == ".env"
    assert ENV_FILE.parent / "backend" / "app" / "core" / "config.py" == Path(
        config.__file__
    ).resolve()


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