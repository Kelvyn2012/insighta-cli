"""Insighta Labs+ CLI — full command implementation."""

import csv
import json
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event
from urllib.parse import parse_qs, urlparse

import click
import httpx
from rich.console import Console
from rich.table import Table
from rich import box

# ── Config ────────────────────────────────────────────────────────────────────

CREDENTIALS_PATH = Path.home() / ".insighta" / "credentials.json"
DEFAULT_BASE_URL = os.environ.get("INSIGHTA_API_URL", "https://backendrepositorycoresystem-production.up.railway.app")

console = Console()


# ── Credential helpers ────────────────────────────────────────────────────────

def _load_creds() -> dict:
    if not CREDENTIALS_PATH.exists():
        return {}
    try:
        return json.loads(CREDENTIALS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_creds(data: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2))


def _clear_creds() -> None:
    if CREDENTIALS_PATH.exists():
        CREDENTIALS_PATH.unlink()


# ── HTTP client with auto-refresh ─────────────────────────────────────────────

def _client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=60.0)


def _authed_headers(creds: dict, base_url: str) -> dict:
    """Return auth headers, refreshing the access token if needed."""
    access_token = creds.get("access_token", "")
    refresh_token = creds.get("refresh_token", "")
    expires_at = creds.get("expires_at", 0)

    if time.time() >= expires_at - 10 and refresh_token:
        with _client(base_url) as client:
            resp = client.post("/auth/refresh/", json={"refresh_token": refresh_token})
        if resp.status_code == 200:
            data = resp.json()
            creds["access_token"] = data["access_token"]
            creds["refresh_token"] = data["refresh_token"]
            creds["expires_at"] = time.time() + 170  # 3 min - 10s buffer
            _save_creds(creds)
            access_token = creds["access_token"]
        else:
            console.print("[red]Session expired. Please run `insighta login` again.[/red]")
            sys.exit(1)

    return {
        "Authorization": f"Bearer {access_token}",
        "X-API-Version": "1",
    }


def _require_login(ctx: click.Context) -> tuple[dict, str]:
    creds = _load_creds()
    base_url = ctx.obj.get("base_url", DEFAULT_BASE_URL)
    if not creds.get("access_token"):
        console.print("[red]Not logged in. Run `insighta login` first.[/red]")
        sys.exit(1)
    return creds, base_url


def _api_get(url: str, headers: dict, params: dict = None) -> httpx.Response:
    base_url = url.rsplit("/api/", 1)[0] if "/api/" in url else DEFAULT_BASE_URL
    with httpx.Client(timeout=60.0) as client:
        return client.get(url, headers=headers, params=params or {})


# ── OAuth callback server ─────────────────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    received: dict = {}
    done: Event = Event()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        self.received["code"] = qs.get("code", [None])[0]
        self.received["state"] = qs.get("state", [None])[0]
        self.received["error"] = qs.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Login successful! You can close this tab.</h2></body></html>"
        )
        self.done.set()

    def log_message(self, *args):
        pass  # silence server logs


# ── CLI entry point ───────────────────────────────────────────────────────────

@click.group()
@click.option("--api-url", default=DEFAULT_BASE_URL, envvar="INSIGHTA_API_URL",
              help="Backend base URL")
@click.pass_context
def main(ctx, api_url):
    """Insighta Labs+ command-line interface."""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = api_url.rstrip("/")


# ── login ─────────────────────────────────────────────────────────────────────

@main.command()
@click.pass_context
def login(ctx):
    """Authenticate with GitHub OAuth (opens browser)."""
    base_url = ctx.obj["base_url"]

    from urllib.parse import urlencode, parse_qs, urlparse, urlunparse

    with _client(base_url) as client:
        resp = client.get("/auth/github/", follow_redirects=False)

    if resp.status_code not in (200, 302):
        console.print(f"[red]Failed to start auth: {resp.text}[/red]")
        sys.exit(1)

    local_callback = "http://localhost:9876/auth/github/callback/"

    if resp.status_code == 302:
        redirect_url = resp.headers.get("location", "")
        parsed = urlparse(redirect_url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        state = (qs.get("state") or [""])[0]
        qs["redirect_uri"] = [local_callback]
        new_qs = urlencode({k: v[0] for k, v in qs.items()})
        redirect_url = urlunparse(parsed._replace(query=new_qs))
    else:
        data = resp.json()
        redirect_url = data["redirect_url"]
        state = data["state"]
        parsed = urlparse(redirect_url)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        qs["redirect_uri"] = [local_callback]
        new_qs = urlencode({k: v[0] for k, v in qs.items()})
        redirect_url = urlunparse(parsed._replace(query=new_qs))

    _CallbackHandler.received = {}
    _CallbackHandler.done = Event()

    server = HTTPServer(("localhost", 9876), _CallbackHandler)
    console.print("[cyan]Opening GitHub login in your browser...[/cyan]")
    webbrowser.open(redirect_url)

    server.timeout = 120
    while not _CallbackHandler.done.is_set():
        server.handle_request()

    server.server_close()

    if _CallbackHandler.received.get("error"):
        console.print(f"[red]GitHub denied: {_CallbackHandler.received['error']}[/red]")
        sys.exit(1)

    code = _CallbackHandler.received.get("code")
    recv_state = _CallbackHandler.received.get("state")

    if not code or recv_state != state:
        console.print("[red]Invalid callback — state mismatch.[/red]")
        sys.exit(1)

    with _client(base_url) as client:
        resp = client.get("/auth/github/callback/", params={"code": code, "state": recv_state})

    if resp.status_code != 200:
        console.print(f"[red]Token exchange failed: {resp.json().get('message')}[/red]")
        sys.exit(1)

    token_data = resp.json()
    _save_creds({
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "expires_at": time.time() + token_data.get("expires_in", 170),
        "base_url": base_url,
    })
    console.print("[green]✓ Logged in successfully.[/green]")
    console.print(f"Credentials saved to [bold]{CREDENTIALS_PATH}[/bold]")


# ── logout ────────────────────────────────────────────────────────────────────

@main.command()
@click.pass_context
def logout(ctx):
    """Revoke server-side token and remove local credentials."""
    creds = _load_creds()
    base_url = ctx.obj["base_url"]
    if creds.get("refresh_token"):
        with _client(base_url) as client:
            client.post("/auth/logout/", json={"refresh_token": creds["refresh_token"]})
    _clear_creds()
    console.print("[green]✓ Logged out.[/green]")


# ── profiles group ────────────────────────────────────────────────────────────

@main.group()
def profiles():
    """Manage demographic profiles."""


def _filter_options(fn):
    """Reusable filter/sort/pagination decorators."""
    fn = click.option("--gender", type=click.Choice(["male", "female"]), default=None)(fn)
    fn = click.option("--age-group", type=click.Choice(["child", "teenager", "adult", "senior"]),
                      default=None)(fn)
    fn = click.option("--country", default=None, metavar="CODE",
                      help="ISO country code, e.g. NG")(fn)
    fn = click.option("--min-age", type=int, default=None)(fn)
    fn = click.option("--max-age", type=int, default=None)(fn)
    fn = click.option("--min-gender-prob", type=float, default=None,
                      metavar="0-1")(fn)
    fn = click.option("--min-country-prob", type=float, default=None,
                      metavar="0-1")(fn)
    fn = click.option("--sort-by", type=click.Choice(["age", "created_at", "gender_probability"]),
                      default=None)(fn)
    fn = click.option("--order", type=click.Choice(["asc", "desc"]), default="asc")(fn)
    fn = click.option("--page", type=int, default=1)(fn)
    fn = click.option("--limit", type=int, default=10)(fn)
    return fn


def _build_params(gender, age_group, country, min_age, max_age, min_gender_prob,
                  min_country_prob, sort_by, order, page, limit) -> dict:
    p = {"page": page, "limit": limit}
    if gender:
        p["gender"] = gender
    if age_group:
        p["age_group"] = age_group
    if country:
        p["country_id"] = country
    if min_age is not None:
        p["min_age"] = min_age
    if max_age is not None:
        p["max_age"] = max_age
    if min_gender_prob is not None:
        p["min_gender_probability"] = min_gender_prob
    if min_country_prob is not None:
        p["min_country_probability"] = min_country_prob
    if sort_by:
        p["sort_by"] = sort_by
        p["order"] = order
    return p


def _render_profiles_table(data_list: list, title: str = "Profiles") -> None:
    table = Table(title=title, box=box.ROUNDED, show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Gender")
    table.add_column("Age", justify="right")
    table.add_column("Age Group")
    table.add_column("Country")
    table.add_column("G.Prob", justify="right")
    table.add_column("ID", style="dim")
    for p in data_list:
        table.add_row(
            p["name"],
            p["gender"],
            str(p["age"]),
            p["age_group"],
            f"{p['country_id']} ({p.get('country_name', '')})",
            f"{p['gender_probability']:.2f}",
            str(p["id"])[:8] + "…",
        )
    console.print(table)


# ── profiles list ─────────────────────────────────────────────────────────────

@profiles.command("list")
@_filter_options
@click.pass_context
def profiles_list(ctx, gender, age_group, country, min_age, max_age, min_gender_prob,
                  min_country_prob, sort_by, order, page, limit):
    """List profiles with optional filters."""
    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)
    params = _build_params(gender, age_group, country, min_age, max_age,
                           min_gender_prob, min_country_prob, sort_by, order, page, limit)

    with _client(base_url) as client:
        resp = client.get("/api/profiles/", headers=headers, params=params)

    if resp.status_code != 200:
        console.print(f"[red]{resp.json().get('message', resp.text)}[/red]")
        sys.exit(1)

    body = resp.json()
    _render_profiles_table(body["data"])
    console.print(
        f"Page [bold]{body['page']}[/bold] of [bold]{body['total_pages']}[/bold] "
        f"— [bold]{body['total']}[/bold] total results"
    )


# ── profiles search ───────────────────────────────────────────────────────────

@profiles.command("search")
@click.argument("query")
@click.option("--page", type=int, default=1)
@click.option("--limit", type=int, default=10)
@click.pass_context
def profiles_search(ctx, query, page, limit):
    """Natural language search, e.g. \"young males from nigeria\"."""
    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)

    with _client(base_url) as client:
        resp = client.get("/api/profiles/search/", headers=headers,
                          params={"q": query, "page": page, "limit": limit})

    if resp.status_code == 422:
        console.print(f"[yellow]Unable to interpret query: \"{query}\"[/yellow]")
        sys.exit(1)
    if resp.status_code != 200:
        console.print(f"[red]{resp.json().get('message', resp.text)}[/red]")
        sys.exit(1)

    body = resp.json()
    _render_profiles_table(body["data"], title=f'Search: "{query}"')
    console.print(
        f"Page [bold]{body['page']}[/bold] of [bold]{body['total_pages']}[/bold] "
        f"— [bold]{body['total']}[/bold] results"
    )


# ── profiles get ──────────────────────────────────────────────────────────────

@profiles.command("get")
@click.argument("profile_id")
@click.pass_context
def profiles_get(ctx, profile_id):
    """Get a single profile by UUID."""
    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)

    with _client(base_url) as client:
        resp = client.get(f"/api/profiles/{profile_id}/", headers=headers)

    if resp.status_code == 404:
        console.print("[red]Profile not found.[/red]")
        sys.exit(1)
    if resp.status_code != 200:
        console.print(f"[red]{resp.json().get('message', resp.text)}[/red]")
        sys.exit(1)

    p = resp.json()["data"]
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    for key in ("id", "name", "gender", "gender_probability", "age", "age_group",
                "country_id", "country_name", "country_probability", "created_at"):
        table.add_row(key, str(p.get(key, "")))
    console.print(table)


# ── profiles export ───────────────────────────────────────────────────────────

@profiles.command("export")
@_filter_options
@click.option("--output", "-o", default=None, metavar="FILE",
              help="Write to FILE instead of stdout")
@click.pass_context
def profiles_export(ctx, gender, age_group, country, min_age, max_age, min_gender_prob,
                    min_country_prob, sort_by, order, page, limit, output):
    """Export profiles to CSV."""
    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)
    params = _build_params(gender, age_group, country, min_age, max_age,
                           min_gender_prob, min_country_prob, sort_by, order, page, limit)
    params["format"] = "csv"

    with _client(base_url) as client:
        resp = client.get("/api/profiles/export/", headers=headers, params=params)

    if resp.status_code != 200:
        console.print(f"[red]{resp.text}[/red]")
        sys.exit(1)

    if output:
        Path(output).write_bytes(resp.content)
        console.print(f"[green]✓ Saved to {output}[/green]")
    else:
        sys.stdout.buffer.write(resp.content)


# ── profiles create ───────────────────────────────────────────────────────────

@profiles.command("create")
@click.argument("name")
@click.pass_context
def profiles_create(ctx, name):
    """Create a profile by name via external API aggregation (admin only)."""
    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)

    with _client(base_url) as client:
        resp = client.post("/api/profiles/", headers=headers, json={"name": name})

    if resp.status_code == 403:
        console.print("[red]Admin access required.[/red]")
        sys.exit(1)
    if resp.status_code == 502:
        console.print(f"[red]External API error: {resp.json().get('message')}[/red]")
        sys.exit(1)
    if resp.status_code not in (200, 201):
        console.print(f"[red]{resp.json().get('message', resp.text)}[/red]")
        sys.exit(1)

    p = resp.json()["data"]
    status_word = "already exists" if resp.status_code == 200 else "created"
    console.print(f"[green]✓ Profile {status_word}:[/green]")
    _render_profiles_table([p])


# ── profiles delete ───────────────────────────────────────────────────────────

@profiles.command("delete")
@click.argument("profile_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def profiles_delete(ctx, profile_id, yes):
    """Delete a profile by UUID (admin only)."""
    if not yes:
        click.confirm(f"Delete profile {profile_id}?", abort=True)

    creds, base_url = _require_login(ctx)
    headers = _authed_headers(creds, base_url)

    with _client(base_url) as client:
        resp = client.delete(f"/api/profiles/{profile_id}/", headers=headers)

    if resp.status_code == 204:
        console.print("[green]✓ Deleted.[/green]")
    elif resp.status_code == 403:
        console.print("[red]Admin access required.[/red]")
        sys.exit(1)
    elif resp.status_code == 404:
        console.print("[red]Profile not found.[/red]")
        sys.exit(1)
    else:
        console.print(f"[red]{resp.text}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
