# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install for development
pip install -e ".[dev]"
# or
pip install -r requirements.txt -r requirements-dev.txt

# Run all tests
pytest

# Run a single test
pytest tests/test_cli.py::test_profiles_list_success

# Run tests with coverage
pytest --cov=insighta_cli

# Lint
flake8 insighta_cli/ tests/

# Build package
python -m build

# Run the CLI (after install)
insighta --help
```

## Architecture

**Single-module CLI** — all logic lives in [insighta_cli/cli.py](insighta_cli/cli.py). The entry point registered by setuptools is `insighta = "insighta_cli.cli:main"`.

### Key Layers

**Configuration** — `CREDENTIALS_PATH` (`~/.insighta/credentials.json`) and `DEFAULT_BASE_URL` (`https://insighta-backend.onrender.com`) are module-level constants. The base URL is overridable at runtime via `--api-url` flag or `INSIGHTA_API_URL` env var; it flows through Click's context object (`ctx.obj["base_url"]`) to every subcommand.

**Credential management** — `_load_creds()` / `_save_creds()` / `_clear_creds()` read and write a plain JSON file. The file stores `access_token`, `refresh_token`, and `expires_at` (Unix timestamp).

**HTTP client** — `_client(base_url)` returns an `httpx.Client` (15-second timeout) used as a context manager in every command. `_authed_headers(creds, base_url)` checks whether the access token expires within 10 seconds; if so, it calls `/auth/refresh/` and rewrites the credentials file before returning headers. The server issues single-use refresh tokens (each refresh invalidates the previous pair), so the rewrite must happen before returning.

**Auth flow** — `insighta login` starts a one-shot `HTTPServer` on `localhost:9876` to receive the GitHub OAuth redirect. It validates the `state` parameter for CSRF protection, then exchanges the code for tokens via `/auth/github/callback/`. Login times out after 120 seconds.

**Command tree**

```
main (group, sets base_url in ctx)
├── login
├── logout
└── profiles (group)
    ├── list     — GET /api/profiles/
    ├── search   — GET /api/profiles/search/?q=
    ├── get      — GET /api/profiles/{id}/
    ├── export   — GET /api/profiles/export/?format=csv
    ├── create   — POST /api/profiles/   (admin only)
    └── delete   — DELETE /api/profiles/{id}/  (admin only)
```

**Shared filter options** — the `@_filter_options` decorator applies a standard set of query options (`--gender`, `--age-group`, `--country`, `--min-age`, `--max-age`, `--min-gender-prob`, `--min-country-prob`, `--sort-by`, `--order`, `--page`, `--limit`) to `list`, `search`, and `export`. `_build_params()` converts these into a dict, mapping `min_gender_prob` → `min_gender_probability` for the API.

**Output** — `rich.console.Console` and `rich.table.Table` render all terminal output. `_render_profiles_table(data_list, title)` is the shared table renderer for list/search results.

### Testing

Tests use Click's `CliRunner` and `unittest.mock.patch` to mock `_client()` and `CREDENTIALS_PATH`. `_make_creds(tmp_path)` writes a credentials fixture; `_mock_response(status_code, body)` builds a fake `httpx.Response`. All commands are tested against mocked HTTP responses — no real network calls are made in tests.

### Linting

Max line length is 127 (configured in `pyproject.toml` under `[tool.flake8]`). CI runs flake8 with `--select=E9,F63,F7,F82` first (fatal syntax/import errors), then a full run for style warnings.
