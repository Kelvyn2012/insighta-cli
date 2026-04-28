"""Tests for Insighta CLI commands using Click's test runner and httpx mocking."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from insighta_cli import __version__
from insighta_cli.cli import main, CREDENTIALS_PATH


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_creds(tmp_path: Path) -> dict:
    creds = {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": time.time() + 300,
        "base_url": "http://testserver",
    }
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text(json.dumps(creds))
    return creds


def _mock_response(status_code: int, body: dict | bytes = None, *, content_type="application/json"):
    resp = MagicMock()
    resp.status_code = status_code
    if isinstance(body, bytes):
        resp.content = body
        resp.text = body.decode()
    else:
        resp.json.return_value = body or {}
        resp.text = json.dumps(body or {})
    return resp


# ── Version ───────────────────────────────────────────────────────────────────

def test_version():
    assert __version__ == "0.1.0"


def test_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "login" in result.output
    assert "logout" in result.output
    assert "profiles" in result.output


# ── logout ────────────────────────────────────────────────────────────────────

def test_logout_clears_credentials(tmp_path):
    creds = _make_creds(tmp_path)

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _mock_response(200, {"status": "success"})
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["logout"])

    assert result.exit_code == 0
    assert "Logged out" in result.output
    assert not (tmp_path / "credentials.json").exists()


# ── profiles list ─────────────────────────────────────────────────────────────

def test_profiles_list_success(tmp_path):
    _make_creds(tmp_path)
    api_response = {
        "status": "success",
        "page": 1, "limit": 10, "total": 1, "total_pages": 1,
        "links": {"self": "http://...", "next": None, "prev": None},
        "data": [{
            "id": "aaaaaaaa-0000-7000-8000-000000000001",
            "name": "amara", "gender": "female", "gender_probability": 0.99,
            "age": 28, "age_group": "adult", "country_id": "GH",
            "country_name": "Ghana", "country_probability": 0.42,
            "created_at": "2025-01-01T00:00:00Z",
        }],
    }

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, api_response)
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "list"])

    assert result.exit_code == 0
    assert "amara" in result.output


def test_profiles_list_not_logged_in(tmp_path):
    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"):
        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "list"])

    assert result.exit_code == 1
    assert "login" in result.output.lower()


# ── profiles search ───────────────────────────────────────────────────────────

def test_profiles_search_success(tmp_path):
    _make_creds(tmp_path)
    api_response = {
        "status": "success",
        "page": 1, "limit": 10, "total": 1, "total_pages": 1,
        "links": {"self": "http://...", "next": None, "prev": None},
        "data": [{
            "id": "bbbbbbbb-0000-7000-8000-000000000001",
            "name": "kwame", "gender": "male", "gender_probability": 0.95,
            "age": 17, "age_group": "teenager", "country_id": "GH",
            "country_name": "Ghana", "country_probability": 0.60,
            "created_at": "2025-01-01T00:00:00Z",
        }],
    }

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, api_response)
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "search", "young males from ghana"])

    assert result.exit_code == 0
    assert "kwame" in result.output


def test_profiles_search_unrecognised(tmp_path):
    _make_creds(tmp_path)

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(
            422, {"status": "error", "message": "Unable to interpret query"}
        )
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "search", "xyzgibberish"])

    assert result.exit_code == 1
    assert "Unable to interpret" in result.output


# ── profiles get ──────────────────────────────────────────────────────────────

def test_profiles_get_success(tmp_path):
    _make_creds(tmp_path)
    profile = {
        "id": "cccccccc-0000-7000-8000-000000000001",
        "name": "nneka", "gender": "female", "gender_probability": 0.92,
        "age": 70, "age_group": "senior", "country_id": "NG",
        "country_name": "Nigeria", "country_probability": 0.55,
        "created_at": "2025-01-01T00:00:00Z",
    }

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(200, {"status": "success", "data": profile})
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "get", profile["id"]])

    assert result.exit_code == 0
    assert "nneka" in result.output


def test_profiles_get_not_found(tmp_path):
    _make_creds(tmp_path)

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(
            404, {"status": "error", "message": "Profile not found"}
        )
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "get", "00000000-0000-0000-0000-000000000000"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# ── profiles create ───────────────────────────────────────────────────────────

def test_profiles_create_success(tmp_path):
    _make_creds(tmp_path)
    profile = {
        "id": "dddddddd-0000-7000-8000-000000000001",
        "name": "jane", "gender": "female", "gender_probability": 0.99,
        "age": 28, "age_group": "adult", "country_id": "GH",
        "country_name": "Ghana", "country_probability": 0.42,
        "created_at": "2025-01-01T00:00:00Z",
    }

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _mock_response(201, {"status": "success", "data": profile})
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "create", "jane"])

    assert result.exit_code == 0
    assert "jane" in result.output


def test_profiles_create_forbidden(tmp_path):
    _make_creds(tmp_path)

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _mock_response(
            403, {"status": "error", "message": "Admin access required."}
        )
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(main, ["profiles", "create", "test"])

    assert result.exit_code == 1
    assert "Admin" in result.output


# ── profiles delete ───────────────────────────────────────────────────────────

def test_profiles_delete_success(tmp_path):
    _make_creds(tmp_path)

    with patch("insighta_cli.cli.CREDENTIALS_PATH", tmp_path / "credentials.json"), \
         patch("insighta_cli.cli._client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = _mock_response(204)
        mock_client_cls.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            main, ["profiles", "delete", "--yes", "dddddddd-0000-0000-0000-000000000001"]
        )

    assert result.exit_code == 0
    assert "Deleted" in result.output
