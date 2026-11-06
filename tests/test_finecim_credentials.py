"""Tests for src.finecim.credentials (tmp files only; the real home and repo .env are never read)."""

from pathlib import Path

import pytest
from src.finecim import credentials as cred_mod
from src.finecim.credentials import Credentials, CredentialsError, load_credentials, parse_env_file


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """No env vars, repo .env and home pointed into tmp_path."""
    for var in ("FINECIM_USERNAME", "FINECIM_PASSWORD", "FINECIM_ENV_FILE"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cred_mod, "REPO_ENV_FILE", repo / ".env")
    return {"home": home, "repo": repo, "tmp": tmp_path}


def _write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def test_env_vars_win(isolated, monkeypatch):
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=filer\nFINECIM_PASSWORD=filepw\n")
    monkeypatch.setenv("FINECIM_USERNAME", "envuser")
    monkeypatch.setenv("FINECIM_PASSWORD", "envpw")
    creds = load_credentials()
    assert creds == Credentials("envuser", "envpw", "env")


def test_partial_env_falls_through_to_files(isolated, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", "envuser")
    path = _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=u\nFINECIM_PASSWORD=p\n")
    creds = load_credentials()
    assert (creds.username, creds.password, creds.source) == ("u", "p", str(path))


def test_explicit_file_beats_repo_and_home(isolated):
    _write(isolated["repo"] / ".env", "FINECIM_USERNAME=repo\nFINECIM_PASSWORD=repopw\n")
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=home\nFINECIM_PASSWORD=homepw\n")
    explicit = _write(isolated["tmp"] / "x.env", "FINECIM_USERNAME=expl\nFINECIM_PASSWORD=explpw\n")
    creds = load_credentials(explicit)
    assert (creds.username, creds.source) == ("expl", str(explicit))


def test_env_file_var(isolated, monkeypatch):
    explicit = _write(isolated["tmp"] / "y.env", "FINECIM_USERNAME=viaenv\nFINECIM_PASSWORD=pw\n")
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=home\nFINECIM_PASSWORD=homepw\n")
    monkeypatch.setenv("FINECIM_ENV_FILE", str(explicit))
    assert load_credentials().username == "viaenv"


def test_repo_env_beats_home(isolated):
    repo_env = _write(isolated["repo"] / ".env", "OTHER=1\nFINECIM_USERNAME=repo\nFINECIM_PASSWORD=repopw\n")
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=home\nFINECIM_PASSWORD=homepw\n")
    creds = load_credentials()
    assert (creds.username, creds.source) == ("repo", str(repo_env))


def test_repo_env_without_keys_falls_through_to_home(isolated):
    _write(isolated["repo"] / ".env", "SOMETHING_ELSE=1\n")
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=home\nFINECIM_PASSWORD=homepw\n")
    assert load_credentials().username == "home"


def test_missing_explicit_file_falls_through(isolated):
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=home\nFINECIM_PASSWORD=homepw\n")
    assert load_credentials(isolated["tmp"] / "nope.env").username == "home"


def test_error_lists_places_and_hides_values(isolated, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", "lonely-user")
    _write(isolated["repo"] / ".env", "FINECIM_PASSWORD=sekret-value\n")
    missing = isolated["tmp"] / "missing.env"
    with pytest.raises(CredentialsError) as excinfo:
        load_credentials(missing)
    message = str(excinfo.value)
    assert isinstance(excinfo.value, RuntimeError)
    assert "FINECIM_USERNAME" in message and "environment" in message
    assert str(missing) in message
    assert str(isolated["repo"] / ".env") in message
    assert str(isolated["home"] / ".finecim.env") in message
    assert "sekret-value" not in message
    assert "lonely-user" not in message


def test_parse_env_file_syntax(tmp_path):
    path = _write(
        tmp_path / "a.env",
        "﻿# comment line\n"
        "\n"
        "FINECIM_USERNAME = \"jan.novak@example.cz\"\n"
        "export FINECIM_PASSWORD='p#ss = w0rd'\n"
        "PLAIN=abc#def\n"
        "INLINE=value # trailing comment\n"
        "QUOTED_COMMENT=\"x y\"  # note\n"
        "EMPTY=\n"
        "not a pair\n"
        "UNICODE=Přihlásit\n",
    )
    values = parse_env_file(path)
    assert values["FINECIM_USERNAME"] == "jan.novak@example.cz"
    assert values["FINECIM_PASSWORD"] == "p#ss = w0rd"
    assert values["PLAIN"] == "abc#def"
    assert values["INLINE"] == "value"
    assert values["QUOTED_COMMENT"] == "x y"
    assert values["EMPTY"] == ""
    assert values["UNICODE"] == "Přihlásit"
    assert "not a pair" not in values and len(values) == 7


def test_bom_file_is_read(isolated):
    _write(isolated["home"] / ".finecim.env", "FINECIM_USERNAME=bom\nFINECIM_PASSWORD=pw\n", encoding="utf-8-sig")
    assert load_credentials().username == "bom"


def test_repr_masks_password():
    creds = Credentials("user", "hunter2", "env")
    assert "hunter2" not in repr(creds)
    assert "hunter2" not in str(creds)
    assert "***" in repr(creds) and "user" in repr(creds)
    assert creds.password == "hunter2"
