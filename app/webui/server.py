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
import hmac
import math
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

from app.webui.geocoding import LookupBusy, LookupUnavailable, search_places
from app.webui.schema import (
    AFTER_HOURS_SCHEMA,
    EMPTY_MODULE_HELP,
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
_UPDATE_LOCK = threading.Lock()
_UPDATE_INSTANCE = os.urandom(16).hex()
_INSTALL_STARTED = "[INSTALL] Dumb Smart Display installer started."

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, template_folder="templates")

# Keep the signing key stable for this process. Authentication is separately
# bound to the current credential generation, checked on every protected route.
app.secret_key = os.urandom(24)
_auth_state_lock = threading.RLock()
_auth_password: Optional[str] = None
_auth_generation = ""


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
        with _auth_state_lock:
            Path(tmp_path).replace(_CONFIG_PATH)
            # Observe every saved password transition, including disabling and
            # re-enabling protection with the same password between requests.
            _authentication_state()
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
    """Return the full HEAD commit hash, or empty string on failure."""
    try:
        result = subprocess.run(
            _git("rev-parse", "HEAD"),
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
        command = [str(pip), "install", "-q", "-r", str(req)]
        if getattr(os, "geteuid", lambda: -1)() == 0:
            command = ["sudo", "-n", "-H", "-u", _application_user(), "--", *command]
        result = subprocess.run(
            command,
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
    """Flush the response before restarting; retain errors for the status poll."""
    def _worker() -> None:
        time.sleep(delay_secs)
        try:
            result = subprocess.run(
                ["sudo", "-n", "systemctl", "restart", service],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or "Service restart failed")
        except Exception as exc:
            state = _read_update_state()
            state.update(phase="failed", error=f"Web UI restart failed: {exc}")
            _write_update_state(state)

    threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _configured_password() -> str:
    cfg = _load_merged_config()
    return str(cfg.get("webui", {}).get("password", "") or "")


def _authentication_state() -> Tuple[str, str]:
    """Read credentials and rotate the opaque generation when they change."""
    global _auth_password, _auth_generation
    with _auth_state_lock:
        password = _configured_password()
        if password != _auth_password:
            _auth_password = password
            _auth_generation = os.urandom(32).hex()
        return password, _auth_generation


def _auth_required() -> bool:
    return bool(_authentication_state()[0])


def _check_password(candidate: str, configured: str) -> bool:
    return hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))


def login_required(f):  # type: ignore[no-untyped-def]
    @functools.wraps(f)
    def decorated(*args, **kwargs):  # type: ignore[no-untyped-def]
        password, generation = _authentication_state()
        if password:
            saved_generation = session.get("auth_generation")
            if (session.get("authenticated") is not True
                    or not isinstance(saved_generation, str)
                    or not hmac.compare_digest(saved_generation, generation)):
                session.clear()
                return redirect(url_for("login"))
        else:
            session.pop("authenticated", None)
            session.pop("auth_generation", None)
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


def _coerce_field(raw: str, field_type: str, field: Optional[Dict[str, Any]] = None) -> Any:
    """Convert a submitted value, rejecting unsafe numeric configuration."""
    if field_type == "number":
        field = field or {}
        label = field.get("label", "Value")
        try:
            f = float(raw)
        except (ValueError, TypeError):
            raise ValueError(f"{label}: enter a number; this field cannot be blank.") from None
        if not math.isfinite(f):
            raise ValueError(f"{label}: enter a finite number.")
        if field.get("step") != "any" and not f.is_integer():
            raise ValueError(f"{label}: enter a whole number.")
        if "min" in field and f < field["min"]:
            raise ValueError(f"{label}: must be at least {field['min']}.")
        if "max" in field and f > field["max"]:
            raise ValueError(f"{label}: must be at most {field['max']}.")
        return int(f) if f.is_integer() else f
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
                    _set_nested(mod_cfg, key, _coerce_field(raw, ftype, field))

        if mod_cfg:
            module_settings[mod_name] = mod_cfg

    cfg["modules"]["settings"] = module_settings

    # ---- Location ----
    loc: Dict[str, Any] = {}
    for field in LOCATION_SCHEMA["fields"]:
        key = field["key"]
        raw = form.get(f"location__{key}")
        if raw is not None:
            _set_nested(loc, key, _coerce_field(raw, field["type"], field))
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
            _set_nested(hw, key, _coerce_field(raw, ftype, field))

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
                _set_nested(ah, key, _coerce_field(raw, ftype, field))
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
            _set_nested(webui, key, _coerce_field(raw, ftype, field))
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
    password, generation = _authentication_state()
    if not password:
        return redirect(url_for("config_page"))

    error: Optional[str] = None
    if request.method == "POST":
        candidate = request.form.get("password", "")
        if _check_password(candidate, password):
            session.clear()
            session["authenticated"] = True
            session["auth_generation"] = generation
            return redirect(url_for("config_page"))
        error = "Incorrect password."

    return render_template("login.html", error=error, auth_required=_auth_required())


@app.route("/logout")
def logout():  # type: ignore[no-untyped-def]
    session.clear()
    return redirect(url_for("login"))


@app.route("/location/search", methods=["POST"])
@login_required
def location_search():
    payload = request.get_json(silent=True)
    query = payload.get('query') if isinstance(payload, dict) else None
    if not isinstance(query, str):
        return jsonify(error='Enter a city and state or a street address.'), 400
    try:
        return jsonify(results=search_places(query))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except LookupBusy as exc:
        return jsonify(error=str(exc)), 429, {'Retry-After': '1'}
    except LookupUnavailable as exc:
        return jsonify(error=str(exc)), 502


@app.route("/config", methods=["GET"])
@login_required
def config_page():  # type: ignore[no-untyped-def]
    _confirm_pending_update(notify=True)
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

    # Preserve the custom module order set on the Modules page.
    # _parse_form rebuilds enabled from MODULE_ORDER iteration; we fix that here
    # so toggling modules on the Settings page never resets the drag order.
    existing_enabled = _deep_merge(_load_example_config(), existing_user).get("modules", {}).get("enabled") or []
    new_enabled_set  = set(new_cfg.get("modules", {}).get("enabled") or [])
    # Custom modules have no form controls, so their enabled state is unchanged.
    preserved = [n for n in existing_enabled if n not in MODULE_ORDER or n in new_enabled_set]
    for n in MODULE_ORDER:
        if n in new_enabled_set and n not in preserved:
            preserved.append(n)
    new_cfg.setdefault("modules", {})["enabled"] = preserved

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
# Module order routes
# ---------------------------------------------------------------------------

@app.route("/modules")
@login_required
def modules_page():  # type: ignore[no-untyped-def]
    cfg = _load_merged_config()
    enabled_list = [n for n in (cfg.get("modules", {}).get("enabled") or [])
                    if n in set(MODULE_ORDER)]
    enabled_set  = set(enabled_list)
    disabled     = [n for n in MODULE_ORDER if n not in enabled_set]
    full_order   = enabled_list + disabled   # enabled first (in order), then disabled
    return render_template(
        "modules.html",
        full_order=full_order,
        enabled_set=enabled_set,
        mod_settings=cfg.get("modules", {}).get("settings", {}),
        empty_module_help=EMPTY_MODULE_HELP,
        module_schemas=MODULE_SCHEMAS,
        auth_required=_auth_required(),
    )


@app.route("/modules", methods=["POST"])
@login_required
def modules_save():  # type: ignore[no-untyped-def]
    ordered     = request.form.getlist("module_order")   # names in drag order
    enabled_set = {n for n in MODULE_ORDER if request.form.get(f"module_enabled__{n}")}
    # Build new enabled list: ordered names that are enabled
    new_enabled = list(dict.fromkeys(n for n in ordered if n in enabled_set))
    # Safety: add any enabled modules missing from the dragged list
    for n in MODULE_ORDER:
        if n in enabled_set and n not in new_enabled:
            new_enabled.append(n)
    user_cfg = _load_user_config()
    existing_enabled = _deep_merge(_load_example_config(), user_cfg).get("modules", {}).get("enabled") or []
    # The order form only contains built-in modules. Keep custom modules in
    # their existing slots while applying the requested order to built-ins.
    remaining = iter(new_enabled)
    preserved = []
    for name in existing_enabled:
        if name not in MODULE_ORDER:
            preserved.append(name)
        else:
            replacement = next(remaining, None)
            if replacement is not None:
                preserved.append(replacement)
    preserved.extend(remaining)
    new_enabled = preserved
    user_cfg.setdefault("modules", {})["enabled"] = new_enabled
    settings = user_cfg["modules"].setdefault("settings", {})
    for name in EMPTY_MODULE_HELP:
        settings.setdefault(name, {})["hide_when_empty"] = bool(
            request.form.get(f"module_hide_when_empty__{name}")
        )
    _write_user_config(user_cfg)
    ok, msg = _restart_service()
    flash(
        "Module settings saved. Display service restarting." if ok else f"Saved. Note: {msg}",
        "success" if ok else "warning",
    )
    return redirect(url_for("modules_page"))


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
    """Format multiline output as a single Server-Sent Event."""
    prefix = f"event: {event}\n" if event else ""
    return prefix + "".join(f"data: {line}\n" for line in data.split("\n")) + "\n"


def _update_state_path() -> Path:
    return _CONFIG_PATH.parent / ".update-state.yml"


def _read_update_state() -> Dict[str, Any]:
    path = _update_state_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        state = yaml.safe_load(handle)
    if not isinstance(state, dict):
        raise ValueError("Invalid pending update state; inspect config/.update-state.yml")
    return state


def _write_update_state(state: Dict[str, Any]) -> None:
    path = _update_state_path()
    owner = None
    if getattr(os, "geteuid", lambda: -1)() == 0:
        import pwd

        account = pwd.getpwnam(_application_user())
        owner = (account.pw_uid, account.pw_gid)
    parent_existed = path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if owner and not parent_existed:
        os.chown(path.parent, *owner)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".update-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if owner:
                os.fchown(handle.fileno(), *owner)
            yaml.safe_dump(state, handle)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _display_service_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", _DISPLAY_SERVICE],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _application_user() -> str:
    """Keep the deployed account, including when repairing an old root update."""
    import pwd  # Only the Linux installer needs this; the web UI runs on PCs too.

    result = subprocess.run(
        ["systemctl", "show", "--property=User", "--value", _WEBUI_SERVICE],
        capture_output=True, text=True, timeout=5,
    )
    user = result.stdout.strip() if result.returncode == 0 else ""
    if not user:
        user = pwd.getpwuid(os.geteuid()).pw_name
    if user == "root":
        # Older updater versions silently rewrote the units as root. The checkout
        # owner remains the original app account in that case.
        user = pwd.getpwuid(_ROOT.stat().st_uid).pw_name
    account = pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)
    if account.pw_uid == 0:
        raise RuntimeError("Cannot determine a non-root app user; run install.sh with APP_USER set.")
    return account.pw_name


def _system_install_changed(base: str, head: str) -> bool:
    result = subprocess.run(
        _git("diff", "--quiet", base, head, "--", "scripts/install.sh", "systemd"),
        capture_output=True, timeout=10, cwd=str(_ROOT),
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not check whether system installation changed.")
    return result.returncode == 1


def _run_install(base: str, head: str):
    """Yield log lines, then return success; never hide an installer failure."""
    def python_only():
        receipt = _CONFIG_PATH.parent / ".system-install-revision"
        installed_revision = receipt.read_text(encoding="utf-8").strip() if receipt.exists() else ""
        if _system_install_changed(base, head) and installed_revision != head:
            yield "This update changes system installation. Run ./scripts/install.sh over SSH, then retry."
            return False
        yield "System installer permission unavailable; system files are unchanged or already installed. Installing Python dependencies only."
        ok, message = _pip_install()
        yield message
        return ok

    install_args = ["bash", str(_ROOT / "scripts" / "install.sh"), "--update",
                    "--app-user", _application_user()]
    try:
        allowed = subprocess.run(
            ["sudo", "-n", "-l", *install_args], capture_output=True, text=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        allowed = False
    if not allowed:
        return (yield from python_only())

    proc = subprocess.Popen(
        ["sudo", "-n", *install_args], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, cwd=str(_ROOT),
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"},
    )
    started = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.rstrip("\n") == _INSTALL_STARTED:
                started = True
                continue
            if line.rstrip("\n"):
                yield line.rstrip("\n")
        proc.wait()
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
    if proc.returncode:
        if not started:
            # sudo -l may allow listing password-required commands. A marker
            # emitted by the script distinguishes a denied launch from a real
            # installation failure, which must never use the pip fallback.
            return (yield from python_only())
        yield f"Install script exited with code {proc.returncode}. Services were not restarted. Retry after correcting the error."
        return False
    return True


def _run_update():
    """Shared update transaction for the streaming and no-JavaScript routes."""
    if not _UPDATE_LOCK.acquire(blocking=False):
        yield "fail", "An update is already running."
        return
    state: Dict[str, Any] = {}
    try:
        _confirm_pending_update()
        previous = _read_update_state()
        if previous.get("phase") == "restarting" and previous.get("instance") == _UPDATE_INSTANCE:
            yield "fail", "The web UI restart has already been requested. Wait for it to finish."
            return
        yield "stage", "1"
        yield "", "Checking for updates…"
        fetch_ok, pending, error = _fetch_pending_commits()
        if not fetch_ok:
            yield "fail", f"Could not check for updates: {error}"
            return
        yield "", f"Found {len(pending)} pending commits."
        yield "stage", "2"
        before = _get_head_commit()
        if not before:
            yield "fail", "Could not identify the current commit."
            return
        state = {"base": previous.get("base", before), "head": before, "phase": "install"}
        # Save before moving HEAD, so a failed or interrupted installation can
        # be retried even when git subsequently reports 'already up to date'.
        _write_update_state(state)
        if _get_current_branch() != "main":
            checkout = subprocess.run(
                _git("checkout", "main"), capture_output=True, text=True,
                timeout=10, cwd=str(_ROOT),
            )
            if checkout.returncode:
                yield "fail", checkout.stderr.strip() or "Could not switch to main."
                return
        pulled, message = _do_git_pull()
        yield "", message
        if not pulled:
            yield "fail", "Update stopped before installation."
            return
        head = _get_head_commit()
        if not head:
            yield "fail", "Could not identify the updated commit."
            return
        if before == head and not previous:
            if pending:
                yield "fail", "Pending commits remain, but HEAD did not advance. Inspect git status."
            else:
                _update_state_path().unlink(missing_ok=True)
                yield "uptodate", "Already up to date."
            return
        state["head"] = head
        _write_update_state(state)
        yield "stage", "3"
        yield "", "Installing update dependencies…"
        installer = _run_install(state["base"], head)
        while True:
            try:
                yield "", next(installer)
            except StopIteration as finished:
                installed = finished.value
                break
        if not installed:
            yield "fail", "Installation failed. The update remains pending and can be retried."
            return
        yield "stage", "4"
        ok, message = _restart_service()
        yield "", message
        if not ok or not _display_service_active():
            yield "fail", "Display service did not restart successfully. The update remains pending."
            return
        yield "stage", "5"
        state.update(phase="restarting", instance=_UPDATE_INSTANCE)
        _write_update_state(state)
        _schedule_restart(_WEBUI_SERVICE, delay_secs=3.0)
        yield "restarting", _UPDATE_INSTANCE
    except Exception as exc:
        yield "fail", f"Update failed: {exc}. Retry after correcting the error."
    finally:
        _UPDATE_LOCK.release()


@app.route("/update/stream")
@login_required
def update_stream():
    return Response(
        (_sse(data, event) for event, data in _run_update()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/update/status")
@login_required
def update_status():
    """Confirm the new web process and display are available after restart."""
    return jsonify(_confirm_pending_update())


def _confirm_pending_update(notify: bool = False) -> Dict[str, str]:
    """Also called after login, since a restart invalidates old session cookies."""
    try:
        state = _read_update_state()
    except (OSError, ValueError, yaml.YAMLError):
        error = "Could not read pending update state; inspect config/.update-state.yml."
        if notify:
            flash(error, "warning")
        return {"instance": _UPDATE_INSTANCE, "phase": "failed", "error": error}
    phase = state.get("phase", "complete")
    if phase == "restarting" and state.get("instance") != _UPDATE_INSTANCE:
        if state.get("head") == _get_head_commit() and _display_service_active():
            _update_state_path().unlink(missing_ok=True)
            phase = "complete"
            if notify:
                flash("Update complete. The display and control panel are available.", "success")
        else:
            phase = "failed"
            state.update(phase=phase, error="Display health check failed. Retry the pending update.")
            _write_update_state(state)
            if notify:
                flash(state["error"], "error")
    return {"instance": _UPDATE_INSTANCE, "phase": phase,
            "error": state.get("error", "")}


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
def do_update():
    """Run the same validated update stages when JavaScript is unavailable."""
    for event, message in _run_update():
        if event == "fail":
            flash(message, "error")
        elif event == "uptodate":
            flash(message, "success")
        elif event == "restarting":
            flash("Dependencies installed and display restarted. Web UI restart requested; refresh shortly.", "warning")
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
