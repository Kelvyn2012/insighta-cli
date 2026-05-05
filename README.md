# insighta-cli

Command-line interface for the [Insighta Labs+](https://github.com/Kelvyn2012/Backend_Repository_Core_System) Intelligence Query Engine.

## Install

```bash
pip install insighta-cli
```

Or install from source:

```bash
git clone https://github.com/Kelvyn2012/insighta-cli
cd insighta-cli
pip install .
```

Requires Python 3.11+.

## Configuration

Credentials are stored at `~/.insighta/credentials.json`. The CLI auto-refreshes the access token before it expires using the stored refresh token — no manual token management needed.

The default backend is the production deployment. To use a different one:

```bash
export INSIGHTA_API_URL=http://localhost:8000
# or per-command:
insighta --api-url http://localhost:8000 profiles list
```

## Authentication

```bash
# Open GitHub OAuth in browser, then paste the returned tokens
insighta login

# Revoke the server-side refresh token and delete ~/.insighta/credentials.json
insighta logout
```

`insighta login` opens the GitHub authorization page in your browser. After you authorize, your browser displays a JSON response containing `access_token` and `refresh_token`. Paste them into the prompts. Credentials are saved to `~/.insighta/credentials.json`.

## Commands

### `insighta profiles list`

```bash
insighta profiles list                                       # first page, default limit 10
insighta profiles list --gender female --age-group adult
insighta profiles list --country NG --min-age 20 --max-age 40
insighta profiles list --sort-by age --order desc --limit 25 --page 2
insighta profiles list --min-gender-prob 0.9 --min-country-prob 0.5
```

Options: `--gender`, `--age-group`, `--country` (ISO code), `--min-age`, `--max-age`, `--min-gender-prob`, `--min-country-prob`, `--sort-by`, `--order`, `--page`, `--limit`

### `insighta profiles search`

Natural language search — rule-based, no AI.

```bash
insighta profiles search "young males from nigeria"
insighta profiles search "senior women from kenya"
insighta profiles search "adults aged 30 to 50"
insighta profiles search "teenagers from ghana"
```

Supports `--page` and `--limit`.

### `insighta profiles get`

```bash
insighta profiles get <uuid>
```

### `insighta profiles export`

Exports filtered profiles to CSV. Accepts the same filter flags as `list`.

```bash
insighta profiles export                         # prints CSV to stdout
insighta profiles export --output profiles.csv   # writes to file
insighta profiles export --gender female --country KE --output kenya-females.csv
```

### `insighta profiles upload` *(admin only)*

Bulk-inserts profiles from a local CSV file. The file is streamed — large files (up to 150 MB / ~500 000 rows) are handled without loading the whole file into memory. Bad rows are skipped and reported; a single bad row never aborts the upload.

```bash
insighta profiles upload profiles.csv
insighta profiles upload /path/to/large_dataset.csv
```

Required CSV columns: `name`, `gender`, `age`, `country_id`
Optional columns: `gender_probability`, `country_probability`, `sample_size`, `country_name`

Example output:

```
✓ Upload complete
 Total rows   50000
 Inserted     48231
 Skipped       1769
Skip reasons:
  duplicate_name: 1203
  invalid_age: 312
  missing_fields: 254
```

### `insighta profiles create` *(admin only)*

Creates a single profile by name using the Genderize + Agify + Nationalize APIs. Idempotent — returns existing data if the name already exists.

```bash
insighta profiles create amara
insighta profiles create kwame
```

### `insighta profiles delete` *(admin only)*

```bash
insighta profiles delete <uuid>
insighta profiles delete --yes <uuid>   # skip confirmation prompt
```

## Token handling

- Access tokens expire in **3 minutes**. The CLI checks expiry before every request and silently refreshes using the stored refresh token if needed.
- Refresh tokens are **single-use** — the server revokes each one on use and issues a new pair.
- `insighta logout` revokes the refresh token server-side so it cannot be reused even if the credentials file is recovered.

## Role enforcement

| Command | Required role |
|---|---|
| `list`, `search`, `get`, `export` | analyst or admin |
| `create`, `delete`, `upload` | admin only |

The CLI surfaces 403 responses as `Admin access required.`

## Development

```bash
pip install -r requirements-dev.txt
pip install -e .
pytest --cov=insighta_cli tests/
flake8 insighta_cli tests/
```

## CI

GitHub Actions runs lint + tests on Python 3.11 and 3.12 on every push and PR to `main`.
