# app/webui/server.py
"""
Web-based configuration UI for Dumb Smart Display.

Run directly for development:
    FLASK_DEBUG=1 python -m app.webui.server

Or via the dev script:
    ./scripts/dev_webui.sh

The production systemd unit (dumb-smart-display-webui.service) runs this same entry-point.
"""
from __future__ import annotations

import functools
import hashlib
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.webui.schema import (
    AFTER_HOURS_SCHEMA,
    HARDWARE_SCHEMA,
    LOCATION_SCHEMA,
    MODULE_ORDER,
    MODULE_SCHEMAS,
    WEBUI_SCHEMA,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent   # repo root
_CONFIG_PATH = _ROOT / "config" / "config.yml"
_EXAMPLE_PATH = _ROOT / "config" / "config.example.yml"
_DISPLAY_SERVICE = "dumb-smart-display"
_WEBUI_SERVICE   = "dumb-smart-display-webui"
_UPLOADS_DIR = Path(__file__).parent / "static" / "uploads"
_AFTER_HOURS_PHOTO_STEM = "after_hours_photo"

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates")

# The secret key is derived at request time from the configured password so
# that changing the password automatically invalidates all old sessions.
# We set a temporary placeholder here; _get_secret_key() is called per-request.
app.secret_key = os.urandom(24)


# ---------------------------------------------------------------------------
# Config helpers (mirrors app/main.py logic; kept local to avoid heavy imports)
# ---------------------------------------------------------------------------

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _load_example_config() -> Dict[str, Any]:
    if _EXAMPLE_PATH.exists():
        with _EXAMPLE_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _load_user_config() -> Dict[str, Any]:
    if _CONFIG_PATH.exists():
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


def _load_merged_config() -> Dict[str, Any]:
    """Returns the full effective config (example defaults + user overrides)."""
    base = _load_example_config()
    user = _load_user_config()
    return _deep_merge(base, user)


def _write_user_config(cfg: Dict[str, Any]) -> None:
    """Atomically write *cfg* to config/config.yml."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_CONFIG_PATH.parent, prefix=".config_", suffix=".yml.tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
        Path(tmp_path).replace(_CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _restart_service() -> Tuple[bool, str]:
    """Restart the display systemd service. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", _DISPLAY_SERVICE],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            return True, "Display service restarted successfully."
        stderr = result.stderr.strip()
        return False, f"Service restart failed: {stderr or 'unknown error'}"
    except FileNotFoundError:
        return False, "systemctl not found — are you running on a Pi?"
    except subprocess.TimeoutExpired:
        return False, "Service restart timed out."
    except Exception as exc:
        return False, f"Service restart error: {exc}"


# ---------------------------------------------------------------------------
# Git / update helpers
# ---------------------------------------------------------------------------

def _git(*args: str) -> List[str]:
    """Build a git command with safe.directory set to _ROOT.

    Avoids "dubious ownership" errors when the web UI service runs under a
    different effective user than the repo owner (common with sudo/systemd).
    """
    return ["git", "-c", f"safe.directory={_ROOT}", *args]


def _get_current_version() -> str:
    """Return a short human-readable string for the currently checked-out commit."""
    try:
        result = subprocess.run(
            _git("log", "-1", "--format=%h — %s"),
            capture_output=True, text=True, timeout=10, cwd=str(_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _fetch_pending_commits() -> Tuple[bool, List[str], str]:
    """
    Run ``git fetch origin`` then list commits available on origin but not
    yet merged locally.

    Returns ``(fetch_ok, [commit_lines], error_message)``.
    """
    try:
        fetch = subprocess.run(
            _git("fetch", "origin"),
            capture_output=True, text=True, timeout=30, cwd=str(_ROOT),
        )
        if fetch.returncode != 0:
            err = fetch.stderr.strip() or "git fetch failed"
            return False, [], err

        log = subprocess.run(
            _git("log", "HEAD..origin/main", "--oneline"),
            capture_output=True, text=True, timeout=10, cwd=str(_ROOT),
        )
        pending = [ln for ln in log.stdout.strip().splitlines() if ln]
        return True, pending, ""
    except FileNotFoundError:
        return False, [], "git not found on this system"
    except Exception as exc:
        return False, [], str(exc)


def _do_git_pull() -> Tuple[bool, str]:
    """Run ``git pull --ff-only origin main``. Returns ``(success, message)``."""
    try:
        result = subprocess.run(
            _git("pull", "--ff-only", "origin", "main"),
            capture_output=True, text=True, timeout=60, cwd=str(_ROOT),
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "Already up to date."
        return False, result.stderr.strip() or result.stdout.strip() or "git pull failed"
    except FileNotFoundError:
        return False, "git not found on this system"
    except subprocess.TimeoutExpired:
        return False, "git pull timed out"
    except Exception as exc:
        return False, str(exc)


def _get_head_commit() -> str:
    """Return the current HEAD commit short hash, or empty string on failure."""
    try:
        result = subprocess.run(
            _git("rev-parse", "--short", "HEAD"),
            capture_output=True, text=True, timeout=5, cwd=str(_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _get_current_branch() -> str:
    """Return the currently checked-out branch name, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            _git("rev-parse", "--abbrev-ref", "HEAD"),
            capture_output=True, text=True, timeout=5, cwd=str(_ROOT),
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _pip_install() -> Tuple[bool, str]:
    """
    Re-run ``pip install -r requirements.txt`` inside the project venv so that
    any new dependencies added by an update are installed before the services
    restart.
    """
    # Resolve pip from the venv; fall back gracefully if not found.
    pip = _ROOT / ".venv" / "bin" / "pip"
    if not pip.exists():
        pip = _ROOT / ".venv" / "Scripts" / "pip.exe"   # Windows dev environment
    if not pip.exists():
        return False, "pip not found in .venv — skipping dependency install"

    req = _ROOT / "requirements.txt"
    try:
        result = subprocess.run(
            [str(pip), "install", "-q", "-r", str(req)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            return True, "Dependencies installed."
        return False, result.stderr.strip() or "pip install failed"
    except subprocess.TimeoutExpired:
        return False, "pip install timed out"
    except Exception as exc:
        return False, str(exc)


def _schedule_restart(service: str, delay_secs: float = 2.0) -> None:
    """
    Restart *service* after *delay_secs* in a background daemon thread.
    The delay allows the current HTTP response to be flushed to the browser
    before the process is killed.
    """
    def _worker() -> None:
        time.sleep(delay_secs)
        try:
            subprocess.run(
                ["sudo", "systemctl", "restart", service],
                capture_output=True, timeout=15,
            )
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _configured_password() -> str:
    cfg = _load_merged_config()
    return str(cfg.get("webui", {}).get("password", "") or "")


def _get_secret_key(password: str) -> str:
    if not password:
        return "no-auth-placeholder-key"
    return hashlib.sha256(password.encode()).hexdigest()


def _auth_required() -> bool:
    return bool(_configured_password())


def _check_password(candidate: str) -> bool:
    configured = _configured_password()
    if not configured:
        return True
    return candidate == configured


def login_required(f):  # type: ignore[no-untyped-def]
    @functools.wraps(f)
    def decorated(*args, **kwargs):  # type: ignore[no-untyped-def]
        if _auth_required():
            pw = _configured_password()
            app.secret_key = _get_secret_key(pw)
            if not session.get("authenticated"):
                return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Form → nested dict conversion
# ---------------------------------------------------------------------------
# Field keys use "." as a separator for nested paths (e.g. "api.access_token").
# HTML field names use the form  section__key  where "__" separates the
# config section from the field key within that section.
#
# Full form field name format:
#   For location/hardware/webui:  <section>__<dot.path>
#   For modules:                  modules__settings__<name>__<dot.path>
#   For enabled checkboxes:       modules__enabled__<name>

def _set_nested(d: Dict[str, Any], dot_path: str, value: Any) -> None:
    """Set d[k1][k2][...] = value given a dot-separated path string."""
    parts = dot_path.split(".")
    for part in parts[:-1]:
        d = d.setdefault(part, {})
    d[parts[-1]] = value


def _get_nested(d: Dict[str, Any], dot_path: str, default: Any = None) -> Any:
    """Get a value from a nested dict using a dot-separated path."""
    parts = dot_path.split(".")
    for part in parts:
        if not isinstance(d, dict):
            return default
        d = d.get(part, {})  # type: ignore[assignment]
    return d if d != {} else default


def _coerce_field(raw: str, field_type: str) -> Any:
    """Convert a raw form string to the appropriate Python type."""
    if field_type == "number":
        try:
            f = float(raw)
            return int(f) if f == int(f) else f
        except (ValueError, TypeError):
            return raw
    if field_type == "toggle":
        return raw in ("true", "on", "1", "yes")
    return raw


def _parse_form(form: Any) -> Dict[str, Any]:  # noqa: ANN001
    """
    Convert a flat ImmutableMultiDict from the config form into a nested dict
    that mirrors the YAML config structure.
    """
    cfg: Dict[str, Any] = {}

    # ---- Modules enabled list ----
    enabled: List[str] = []
    for name in MODULE_ORDER:
        if form.get(f"modules__enabled__{name}"):
            enabled.append(name)
    cfg.setdefault("modules", {})["enabled"] = enabled

    # ---- Module settings ----
    module_settings: Dict[str, Any] = {}
    for mod_name, schema in MODULE_SCHEMAS.items():
        mod_cfg: Dict[str, Any] = {}
        for field in schema["fields"]:
            key: str = field["key"]
            ftype: str = field["type"]
            form_key = f"modules__settings__{mod_name}__{key}"

            if ftype == "toggle":
                # Checkboxes are only present in form data when checked
                raw = form.get(form_key, "off")
                mod_cfg_target = mod_cfg
                # Use _set_nested to handle dot-paths
                _set_nested(mod_cfg_target, key, raw in ("on", "true", "1", "yes"))
            elif ftype == "events_list":
                # events are submitted as:
                #   events__0__name, events__0__date, events__1__name, ...
                events: List[Dict[str, str]] = []
                idx = 0
                while True:
                    ev_name = form.get(f"{form_key}__{idx}__name")
                    ev_date = form.get(f"{form_key}__{idx}__date")
                    if ev_name is None and ev_date is None:
                        break
                    if ev_name or ev_date:
                        events.append({"name": ev_name or "", "date": ev_date or ""})
                    idx += 1
                _set_nested(mod_cfg, key, events)
            else:
                raw = form.get(form_key)
                if raw is not None:
                    _set_nested(mod_cfg, key, _coerce_field(raw, ftype))

        if mod_cfg:
            module_settings[mod_name] = mod_cfg

    cfg["modules"]["settings"] = module_settings

    # ---- Location ----
    loc: Dict[str, Any] = {}
    for field in LOCATION_SCHEMA["fields"]:
        key = field["key"]
        raw = form.get(f"location__{key}")
        if raw is not None:
            _set_nested(loc, key, _coerce_field(raw, field["type"]))
    if loc:
        cfg["location"] = loc

    # ---- Hardware ----
    hw: Dict[str, Any] = {}
    for field in HARDWARE_SCHEMA["fields"]:
        key = field["key"]
        ftype = field["type"]
        raw = form.get(f"hardware__{key}")
        if ftype == "toggle":
            _set_nested(hw, key, form.get(f"hardware__{key}", "off") in ("on", "true", "1", "yes"))
        elif raw is not None:
            _set_nested(hw, key, _coerce_field(raw, ftype))

    # ---- After Hours (nested under hardware.after_hours) ----
    ah: Dict[str, Any] = {}
    for field in AFTER_HOURS_SCHEMA["fields"]:
        key = field["key"]
        ftype = field["type"]
        form_key = f"hardware__after_hours__{key}"
        if ftype == "toggle":
            _set_nested(ah, key, form.get(form_key, "off") in ("on", "true", "1", "yes"))
        else:
            raw = form.get(form_key)
            if raw is not None:
                _set_nested(ah, key, _coerce_field(raw, ftype))
    if ah:
        hw.setdefault("after_hours", {}).update(ah)

    if hw:
        cfg["hardware"] = hw

    # ---- Web UI ----
    webui: Dict[str, Any] = {}
    for field in WEBUI_SCHEMA["fields"]:
        key = field["key"]
        ftype = field["type"]
        raw = form.get(f"webui__{key}")
        if raw is not None:
            _set_nested(webui, key, _coerce_field(raw, ftype))
    if webui:
        cfg["webui"] = webui

    return cfg


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _get_after_hours_photo() -> str:
    """Return the filename of the uploaded after hours photo, or '' if none exists."""
    cfg = _load_merged_config()
    filename = cfg.get("hardware", {}).get("after_hours", {}).get("photo", "")
    if filename and (_UPLOADS_DIR / filename).exists():
        return filename
    return ""


@app.route("/")
def index():  # type: ignore[no-untyped-def]
    return redirect(url_for("config_page"))


@app.route("/login", methods=["GET", "POST"])
def login():  # type: ignore[no-untyped-def]
    if not _auth_required():
        return redirect(url_for("config_page"))

    error: Optional[str] = None
    if request.method == "POST":
        candidate = request.form.get("password", "")
        pw = _configured_password()
        app.secret_key = _get_secret_key(pw)
        if _check_password(candidate):
            session["authenticated"] = True
            return redirect(url_for("config_page"))
        error = "Incorrect password."

    return render_template("login.html", error=error, auth_required=_auth_required())


@app.route("/logout")
def logout():  # type: ignore[no-untyped-def]
    session.clear()
    return redirect(url_for("login"))


@app.route("/config", methods=["GET"])
@login_required
def config_page():  # type: ignore[no-untyped-def]
    cfg = _load_merged_config()

    enabled_set = set(cfg.get("modules", {}).get("enabled") or [])
    mod_settings = cfg.get("modules", {}).get("settings", {})

    return render_template(
        "config.html",
        cfg=cfg,
        enabled_set=enabled_set,
        mod_settings=mod_settings,
        module_schemas=MODULE_SCHEMAS,
        module_order=MODULE_ORDER,
        location_schema=LOCATION_SCHEMA,
        hardware_schema=HARDWARE_SCHEMA,
        after_hours_schema=AFTER_HOURS_SCHEMA,
        webui_schema=WEBUI_SCHEMA,
        get_nested=_get_nested,
        auth_required=_auth_required(),
        current_version=_get_current_version(),
        after_hours_photo=_get_after_hours_photo(),
    )


@app.route("/config", methods=["POST"])
@login_required
def config_save():  # type: ignore[no-untyped-def]
    try:
        new_cfg = _parse_form(request.form)
    except Exception as exc:
        flash(f"Could not parse form data: {exc}", "error")
        return redirect(url_for("config_page"))

    # Merge new values on top of the existing user config so that keys we
    # didn't render (e.g. hardware pin assignments) are preserved.
    existing_user = _load_user_config()
    merged_new = _deep_merge(existing_user, new_cfg)

    try:
        _write_user_config(merged_new)
    except Exception as exc:
        flash(f"Failed to save configuration: {exc}", "error")
        return redirect(url_for("config_page"))

    ok, msg = _restart_service()
    if ok:
        flash(f"Settings saved. {msg}", "success")
    else:
        # Config was written; service restart just failed (common in dev).
        flash(
            f"Settings saved to config.yml. Note: {msg}",
            "warning",
        )

    return redirect(url_for("config_page"))


# ---------------------------------------------------------------------------
# After Hours photo routes
# ---------------------------------------------------------------------------

_ALLOWED_PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@app.route("/after-hours/upload", methods=["POST"])
@login_required
def after_hours_upload():  # type: ignore[no-untyped-def]
    """Accept a multipart photo upload and persist it as the after hours image."""
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file provided"}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_PHOTO_EXTENSIONS:
        return jsonify({"ok": False, "error": f"Unsupported file type: {ext}"}), 400

    _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove any previous after_hours_photo file (different extension)
    for old in _UPLOADS_DIR.glob(f"{_AFTER_HOURS_PHOTO_STEM}.*"):
        try:
            old.unlink()
        except OSError:
            pass

    filename = f"{_AFTER_HOURS_PHOTO_STEM}{ext}"
    dest = _UPLOADS_DIR / filename
    file.save(str(dest))

    # Update config.yml with the new photo filename
    user_cfg = _load_user_config()
    user_cfg.setdefault("hardware", {}).setdefault("after_hours", {})["photo"] = filename
    _write_user_config(user_cfg)

    return jsonify({"ok": True, "filename": filename})


@app.route("/after-hours/delete", methods=["POST"])
@login_required
def after_hours_delete():  # type: ignore[no-untyped-def]
    """Delete the current after hours photo and clear it from config."""
    for old in _UPLOADS_DIR.glob(f"{_AFTER_HOURS_PHOTO_STEM}.*"):
        try:
            old.unlink()
        except OSError:
            pass

    user_cfg = _load_user_config()
    user_cfg.setdefault("hardware", {}).setdefault("after_hours", {})["photo"] = ""
    _write_user_config(user_cfg)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Update helpers
# ---------------------------------------------------------------------------

def _sse(data: str = "", event: str = "") -> str:
    """Format a single Server-Sent Event message."""
    msg = ""
    if event:
        msg += f"event: {event}\n"
    msg += f"data: {data}\n\n"
    return msg


# ---------------------------------------------------------------------------
# Update routes
# ---------------------------------------------------------------------------

@app.route("/update/stream")
@login_required
def update_stream():  # type: ignore[no-untyped-def]
    """
    Server-Sent Events endpoint that runs the full update sequence and streams
    progress to the browser:
      1. git fetch + report pending commits
      2. git pull --ff-only origin main
      3. scripts/install.sh  (run with sudo -n; output is streamed live)
      4. Restart display service
      5. Restart web UI service (scheduled; page auto-reloads)
    """
    def generate():  # type: ignore[no-untyped-def]
        # --- Stage 1: fetch ---
        yield _sse("Checking for updates…")
        yield _sse("1", event="stage")

        fetch_ok, pending, err = _fetch_pending_commits()
        if not fetch_ok:
            yield _sse(f"Error reaching GitHub: {err}")
            yield _sse(event="fail")
            return

        count = len(pending)
        if count:
            yield _sse(f"Found {count} new commit{'s' if count != 1 else ''}.")
            for c in pending[:5]:
                yield _sse(f"  • {c}")
            if count > 5:
                yield _sse(f"  … and {count - 5} more")
        else:
            yield _sse("No new commits found via fetch.")

        # --- Stage 2: pull ---
        yield _sse("Pulling latest code…")
        yield _sse("2", event="stage")

        branch = _get_current_branch()
        yield _sse(f"Current branch: {branch}")
        if branch != "main":
            yield _sse(f"⚠ Warning: not on 'main' branch — switching to main…")
            chk = subprocess.run(
                _git("checkout", "main"),
                capture_output=True, text=True, timeout=10, cwd=str(_ROOT),
            )
            if chk.returncode != 0:
                yield _sse(f"✗ Could not switch to main: {chk.stderr.strip()}")
                yield _sse(event="fail")
                return
            yield _sse("Switched to branch 'main'.")

        head_before = _get_head_commit()
        pull_ok, pull_msg = _do_git_pull()
        yield _sse(pull_msg)
        if not pull_ok:
            yield _sse(event="fail")
            return

        head_after = _get_head_commit()
        actually_pulled = head_before and head_after and head_before != head_after

        # If HEAD didn't advance, nothing was actually applied.
        if not actually_pulled:
            if count == 0:
                # Genuinely up to date — no commits were pending.
                yield _sse(event="uptodate")
            else:
                # Fetch showed pending commits but pull didn't advance HEAD.
                yield _sse(
                    f"✗ git pull reported success but HEAD did not advance "
                    f"(still at {head_after}). "
                    f"The local repository may have diverged from origin/main."
                )
                yield _sse("Run 'git status' on the Pi to investigate.")
                yield _sse(event="fail")
            return

        yield _sse(f"Updated: {head_before} → {head_after}")

        # --- Stage 3: install script ---
        yield _sse("Running install script…")
        yield _sse("3", event="stage")

        install_sh = _ROOT / "scripts" / "install.sh"
        try:
            proc = subprocess.Popen(
                ["sudo", "-n", "bash", str(install_sh)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(_ROOT),
                env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                stripped = line.rstrip("\n")
                if stripped:
                    yield _sse(stripped)
            proc.wait()
            if proc.returncode != 0:
                yield _sse(f"Install script exited with code {proc.returncode}.")
                # Fall back to pip-only install so new Python deps are covered
                yield _sse("Falling back to pip install…")
                pip_ok, pip_msg = _pip_install()
                yield _sse(pip_msg)
        except Exception as exc:
            yield _sse(f"Install script error: {exc}")
            yield _sse("Falling back to pip install…")
            pip_ok, pip_msg = _pip_install()
            yield _sse(pip_msg)

        # --- Stage 4: restart display service ---
        yield _sse("Restarting display service…")
        yield _sse("4", event="stage")

        ok, msg = _restart_service()
        yield _sse(msg)

        # --- Stage 5: restart web UI service ---
        yield _sse("Restarting web UI service…")
        yield _sse("5", event="stage")

        _schedule_restart(_WEBUI_SERVICE, delay_secs=3.0)
        yield _sse("Web UI service restarting — this page will reload automatically.")

        yield _sse(event="success")

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/update/check")
@login_required
def update_check():  # type: ignore[no-untyped-def]
    """Fetch from origin and report how many commits are available, without pulling."""
    fetch_ok, pending, err = _fetch_pending_commits()

    if not fetch_ok:
        flash(f"Could not reach GitHub: {err}", "error")
    elif not pending:
        flash("Already up to date — no updates available.", "success")
    else:
        count = len(pending)
        preview = "".join(f"\n  • {c}" for c in pending[:5])
        overflow = f"\n  … and {count - 5} more" if count > 5 else ""
        flash(
            f"{count} update{'s' if count != 1 else ''} available:{preview}{overflow}",
            "warning",
        )

    return redirect(url_for("config_page"))


@app.route("/update", methods=["POST"])
@login_required
def do_update():  # type: ignore[no-untyped-def]
    """
    Pull the latest code from origin, reinstall any new dependencies, then
    restart both services.  The web UI service restart is delayed slightly so
    the redirect response reaches the browser before the process is killed.
    """
    # 1. Fetch and collect pending commits (for the summary message only).
    fetch_ok, pending, err = _fetch_pending_commits()

    if not fetch_ok:
        flash(f"Update failed — could not reach GitHub: {err}", "error")
        return redirect(url_for("config_page"))

    count = len(pending)

    # 2. Pull regardless of whether the pending list is empty — the fetch may
    #    have missed commits if origin/HEAD was stale, and git pull is safe
    #    when already up to date.
    pull_ok, pull_msg = _do_git_pull()
    if not pull_ok:
        flash(f"git pull failed: {pull_msg}", "error")
        return redirect(url_for("config_page"))

    # If pull reports already up to date and we saw no pending commits, skip
    # the service restart — nothing changed.
    if count == 0 and "already up to date" in pull_msg.lower():
        flash("Already up to date — nothing to pull.", "success")
        return redirect(url_for("config_page"))

    # 3. Reinstall dependencies (handles new packages added by the update).
    _pip_install()   # best-effort; failures don't block the restart

    # 4. Restart the display service immediately.
    _restart_service()

    # 5. Schedule the web UI service restart after a short delay so this HTTP
    #    response (the redirect) can be flushed to the browser first.
    _schedule_restart(_WEBUI_SERVICE, delay_secs=2.0)

    flash(
        f"Updated! Pulled {count} new commit{'s' if count != 1 else ''}. "
        "Both services are restarting — this page will be back in a few seconds. "
        "Refresh if it does not reload automatically.",
        "success",
    )
    return redirect(url_for("config_page"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cfg = _load_merged_config()
    port = int(cfg.get("webui", {}).get("port", 8080))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Bind to all interfaces so the Pi is reachable from any device on the LAN.
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    main()
