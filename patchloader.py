import os
import sys
import json
import shutil
import time
import zipfile
import traceback
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple

try:
    import tomllib  # Python 3.11+
except Exception:  # pragma: no cover
    tomllib = None  # type: ignore


APPDIR_NAME = "TextCrawler2"


@dataclass
class PatchInfo:
    id: str
    version: str
    api: str
    priority: int
    path: str
    enabled: bool = True
    modules: List[str] = field(default_factory=list)
    replaces: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    requires: Optional[str] = None
    # Resolved cache folder for extracted python/config assets
    cache_py: Optional[str] = None
    cache_cfg: Optional[str] = None


_BOOTSTRAPPED = False
_CONFIG: Dict[str, Any] = {}
_PATCHES: List[PatchInfo] = []
_MOD_DIRS: List[str] = []
_SYS_PATH_MOUNTED: List[str] = []

# Live watcher state
_WATCH_THREAD: Optional[Tuple["threading.Thread", bool]] = None  # (thread, running)
_WATCH_RUNNING = False
_PENDING_REASONS: set = set()
_PENDING_LOCK = None  # initialized lazily to avoid importing threading early
_LAST_CHANGE_MONO: float = 0.0
_LAST_APPLY_OK: Optional[bool] = None
_LAST_APPLY_TIME: Optional[float] = None
_LAST_APPLY_MSG: str = ""
_MIN_APPLY_INTERVAL_S = 2.0
_DEBOUNCE_S = 0.6
_SCAN_INTERVAL_S = 0.8
_SNAP_PREV: Dict[str, Dict[str, Tuple[float, int]]] = {}
_INBOX_STABLE: Dict[str, Tuple[float, int, int]] = {}


def _app_base() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        # Fallback to current working directory
        base = os.path.join(os.getcwd(), APPDIR_NAME)
    else:
        base = os.path.join(appdata, APPDIR_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def _path(*parts: str) -> str:
    p = os.path.join(_app_base(), *parts)
    return p


def _log_path() -> str:
    logs = _path("logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "loader.log")


def _state_path() -> str:
    return _path("patches", "patches_state.json")


def log(msg: str):
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}\n"
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def bootstrap() -> None:
    """Ensure folder structure exists, write example defaults, and load initial config/patch list.

    Safe to call multiple times.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    base = _app_base()
    for sub in ("patches", "mods", "assets", "config", "logs", "cache", "updates_inbox"):
        os.makedirs(_path(sub), exist_ok=True)
    # Example defaults if not present
    _write_default_examples()
    # Scan and mount
    _scan_mount_sources()
    # Build config cascade
    _rebuild_config()
    _BOOTSTRAPPED = True
    log("Bootstrap complete")


def _lazy_lock():
    global _PENDING_LOCK
    if _PENDING_LOCK is None:
        import threading
        _PENDING_LOCK = threading.Lock()
    return _PENDING_LOCK


def _write_default_examples():
    # enemies.json example with current defaults
    defaults = {
        "api": "v1",
        "enemies": {
            # name: overrides
            "Goblin": {"hp": 8, "power": 3, "weight": 4},
            "Archer": {"hp": 6, "power": 2, "weight": 2},
            "Priest": {"hp": 7, "power": 2, "weight": 2},
            "Troll": {"hp": 14, "power": 5, "weight": 2},
            "Shaman": {"hp": 9, "power": 3, "weight": 2},
        },
        "map": {
            "fov_radius": 8
        }
    }
    cfg_dir = _path("config")
    os.makedirs(cfg_dir, exist_ok=True)
    enemies_path = os.path.join(cfg_dir, "enemies.json")
    if not os.path.exists(enemies_path):
        try:
            with open(enemies_path, "w", encoding="utf-8") as f:
                json.dump(defaults, f, indent=2)
        except Exception:
            pass

    # autoplay.json example with anti-oscillation and pathing parameters
    autoplay_defaults = {
        "api": "v1",
        "autoplay": {
            "backtrack_penalty_base": 3,
            "backtrack_penalty_step": 2,
            "backtrack_penalty_max": 10,
            "visit_weight": 0.8,
            "visit_cap": 8,
            "commit_steps": 2,
            "smoothing_max_skip": 1,
            "tie_break_tiny": 0.01
        }
    }
    autoplay_path = os.path.join(cfg_dir, "autoplay.json")
    if not os.path.exists(autoplay_path):
        try:
            with open(autoplay_path, "w", encoding="utf-8") as f:
                json.dump(autoplay_defaults, f, indent=2)
        except Exception:
            pass


def _load_json_file(p: str) -> Dict[str, Any]:
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_toml_file(p: str) -> Dict[str, Any]:  # pragma: no cover
    if tomllib is None:
        return {}
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore
        else:
            out[k] = v
    return out


def _scan_patch_zip(path: str) -> Optional[PatchInfo]:
    try:
        with zipfile.ZipFile(path, "r") as z:
            # Read manifest
            try:
                with z.open("patch.json") as mf:
                    man = json.loads(mf.read().decode("utf-8"))
            except Exception:
                log(f"Invalid patch (no patch.json): {path}")
                return None
            pid = str(man.get("id") or os.path.basename(path))
            ver = str(man.get("version") or "0")
            api = str(man.get("api") or "v1")
            prio = int(man.get("priority") or 0)
            modules = [str(m).replace(".py", "") for m in (man.get("modules") or [])]
            replaces = [str(x) for x in (man.get("replaces") or [])]
            assets = [str(x) for x in (man.get("assets") or [])]
            requires = man.get("requires")
            p = PatchInfo(id=pid, version=ver, api=api, priority=prio, path=path,
                          modules=modules, replaces=replaces, assets=assets, requires=requires)
            return p
    except Exception:
        log(f"Failed to scan patch zip: {path}\n{traceback.format_exc()}")
        return None


def _load_state() -> Dict[str, Any]:
    p = _state_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"enabled": {}, "priority_override": {}}


def _save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def _extract_zip_parts(patch: PatchInfo, cache_root: str) -> None:
    """Extract py/ and config/ parts of a patch zip into cache.

    We use extraction to avoid custom import hooks and leverage sys.path.
    """
    try:
        with zipfile.ZipFile(patch.path, "r") as z:
            # py/
            if any(n.startswith("py/") for n in z.namelist()):
                py_dst = os.path.join(cache_root, f"{patch.id}_{patch.version}", "py")
                os.makedirs(py_dst, exist_ok=True)
                for n in z.namelist():
                    if n.startswith("py/") and not n.endswith("/"):
                        dst = os.path.join(py_dst, n[len("py/"):])
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        with z.open(n) as src, open(dst, "wb") as out:
                            out.write(src.read())
                patch.cache_py = py_dst
            # config/
            if any(n.startswith("config/") for n in z.namelist()):
                cfg_dst = os.path.join(cache_root, f"{patch.id}_{patch.version}", "config")
                os.makedirs(cfg_dst, exist_ok=True)
                for n in z.namelist():
                    if n.startswith("config/") and not n.endswith("/"):
                        dst = os.path.join(cfg_dst, n[len("config/"):])
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        with z.open(n) as src, open(dst, "wb") as out:
                            out.write(src.read())
                patch.cache_cfg = cfg_dst
    except Exception:
        log(f"Failed to extract zip parts for {patch.path}:\n{traceback.format_exc()}")


def _scan_mount_sources() -> None:
    """Scan patches/mods, build sys.path order and import declared modules.

    Also extracts patch py/config contents into %APPDATA%/TextCrawler2/cache.
    """
    global _PATCHES, _MOD_DIRS, _SYS_PATH_MOUNTED
    # Clear previous mounts
    for p in list(_SYS_PATH_MOUNTED):
        try:
            if p in sys.path:
                sys.path.remove(p)
        except Exception:
            pass
    _SYS_PATH_MOUNTED = []

    # Clean cache on rescan
    cache_root = _path("cache")
    os.makedirs(cache_root, exist_ok=True)
    # We don't wipe entire cache to avoid churn; but we can refresh per rescan
    # Remove previous extracted subdirs
    try:
        for n in os.listdir(cache_root):
            p = os.path.join(cache_root, n)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

    # Scan zip patches
    patches_dir = _path("patches")
    os.makedirs(patches_dir, exist_ok=True)
    zips = [os.path.join(patches_dir, n) for n in os.listdir(patches_dir) if n.lower().endswith(".zip")]
    infos: List[PatchInfo] = []
    for z in zips:
        inf = _scan_patch_zip(z)
        if inf is not None:
            infos.append(inf)

    # Apply state (enabled/prio overrides)
    state = _load_state()
    en = state.get("enabled", {})
    por = state.get("priority_override", {})
    for p in infos:
        if p.id in en:
            p.enabled = bool(en.get(p.id))
        if p.id in por:
            try:
                p.priority = int(por.get(p.id))
            except Exception:
                pass

    # Sort by priority (desc: higher earlier)
    infos.sort(key=lambda i: int(i.priority), reverse=True)

    # Extract to cache and mount py dirs onto sys.path (front)
    for p in infos:
        _extract_zip_parts(p, cache_root)
    mount_order: List[str] = []
    for p in infos:
        if not p.enabled:
            continue
        if p.cache_py and os.path.isdir(p.cache_py):
            mount_order.append(p.cache_py)

    # Mods/* directories
    mods_dir = _path("mods")
    os.makedirs(mods_dir, exist_ok=True)
    mod_dirs = []
    for name in os.listdir(mods_dir):
        full = os.path.join(mods_dir, name)
        if os.path.isdir(full):
            mod_dirs.append(full)
    # Mods come after zip patches
    mount_order.extend(mod_dirs)

    # Mount in sys.path front to follow priority
    for entry in reversed(mount_order):  # reversed because we insert at front
        if entry and os.path.isdir(entry):
            if entry not in sys.path:
                sys.path.insert(0, entry)
            _SYS_PATH_MOUNTED.append(entry)

    _PATCHES = infos
    _MOD_DIRS = mod_dirs

    # Import patch modules declared in manifest (best-effort)
    _import_patch_modules()


def _dir_snapshot(root: str, exts: Optional[Tuple[str, ...]] = None, files_only: bool = False, recursive: bool = True) -> Dict[str, Tuple[float, int]]:
    out: Dict[str, Tuple[float, int]] = {}
    try:
        if not os.path.isdir(root):
            return out
        if not recursive:
            for name in os.listdir(root):
                full = os.path.join(root, name)
                if os.path.isdir(full) and files_only:
                    continue
                if os.path.isfile(full):
                    if exts and not name.lower().endswith(exts):
                        continue
                    try:
                        st = os.stat(full)
                        out[full] = (st.st_mtime, st.st_size)
                    except Exception:
                        pass
        else:
            for r, _, names in os.walk(root):
                for name in names:
                    if exts and not name.lower().endswith(exts):
                        continue
                    full = os.path.join(r, name)
                    try:
                        st = os.stat(full)
                        out[full] = (st.st_mtime, st.st_size)
                    except Exception:
                        pass
    except Exception:
        pass
    return out


def _detect_changes(prev: Dict[str, Tuple[float, int]], cur: Dict[str, Tuple[float, int]]) -> bool:
    if len(prev) != len(cur):
        return True
    for k, v in cur.items():
        pv = prev.get(k)
        if pv is None or pv != v:
            return True
    for k in prev.keys():
        if k not in cur:
            return True
    return False


def _watch_loop():
    global _LAST_CHANGE_MONO
    inbox = _path("updates_inbox")
    patches = _path("patches")
    mods = _path("mods")
    assets = _path("assets")
    config = _path("config")
    # initialize snapshots
    _SNAP_PREV["patches"] = _dir_snapshot(patches, exts=(".zip",), files_only=True, recursive=False)
    _SNAP_PREV["mods"] = _dir_snapshot(mods)
    _SNAP_PREV["assets"] = _dir_snapshot(assets)
    _SNAP_PREV["config"] = _dir_snapshot(config, exts=(".json", ".toml", ".tml"))
    while _WATCH_RUNNING:
        try:
            nowm = time.monotonic()
            # Move stable inbox zips into patches
            _check_inbox(inbox, patches)
            # Snapshots
            cur_p = _dir_snapshot(patches, exts=(".zip",), files_only=True, recursive=False)
            cur_m = _dir_snapshot(mods)
            cur_a = _dir_snapshot(assets)
            cur_c = _dir_snapshot(config, exts=(".json", ".toml", ".tml"))
            # Detect per-category
            changed = False
            if _detect_changes(_SNAP_PREV.get("patches", {}), cur_p):
                with _lazy_lock():
                    _PENDING_REASONS.add("patches")
                _SNAP_PREV["patches"] = cur_p
                changed = True
            if _detect_changes(_SNAP_PREV.get("mods", {}), cur_m):
                with _lazy_lock():
                    _PENDING_REASONS.add("mods")
                _SNAP_PREV["mods"] = cur_m
                changed = True
            if _detect_changes(_SNAP_PREV.get("assets", {}), cur_a):
                with _lazy_lock():
                    _PENDING_REASONS.add("assets")
                _SNAP_PREV["assets"] = cur_a
                changed = True
            if _detect_changes(_SNAP_PREV.get("config", {}), cur_c):
                with _lazy_lock():
                    _PENDING_REASONS.add("config")
                _SNAP_PREV["config"] = cur_c
                changed = True
            if changed:
                _LAST_CHANGE_MONO = nowm
            # Debounce and gate
            if has_pending_reload():
                idle_for = nowm - _LAST_CHANGE_MONO
                last_apply = _LAST_APPLY_TIME or 0.0
                if idle_for >= _DEBOUNCE_S and (time.time() - last_apply) >= _MIN_APPLY_INTERVAL_S:
                    # signal ready; GUI/console will consume
                    pass
            time.sleep(_SCAN_INTERVAL_S)
        except Exception:
            log("Watcher loop error:\n" + traceback.format_exc())
            time.sleep(1.0)


def _check_inbox(inbox: str, patches: str):
    try:
        os.makedirs(inbox, exist_ok=True)
        for name in os.listdir(inbox):
            if not name.lower().endswith(".zip"):
                continue
            full = os.path.join(inbox, name)
            if not os.path.isfile(full):
                continue
            try:
                st = os.stat(full)
            except Exception:
                continue
            last = _INBOX_STABLE.get(full)
            if last is None:
                _INBOX_STABLE[full] = (st.st_mtime, st.st_size, 0)
                continue
            lm, ls, cnt = last
            if st.st_size == ls and st.st_mtime == lm:
                cnt += 1
            else:
                cnt = 0
            _INBOX_STABLE[full] = (st.st_mtime, st.st_size, cnt)
            if cnt >= 2:  # stable across two scans
                # move into patches
                try:
                    dst = os.path.join(patches, os.path.basename(full))
                    if os.path.exists(dst):
                        root, ext = os.path.splitext(dst)
                        dst = f"{root}-{int(time.time())}{ext}"
                    shutil.move(full, dst)
                    log(f"Inbox: moved {full} -> {dst}")
                    with _lazy_lock():
                        _PENDING_REASONS.add("patches")
                except Exception:
                    log(f"Inbox move failed for {full}:\n{traceback.format_exc()}")
    except Exception:
        pass


def start_watcher():
    """Start background polling watcher if not already running."""
    global _WATCH_THREAD, _WATCH_RUNNING
    if _WATCH_RUNNING:
        return
    _WATCH_RUNNING = True
    import threading
    t = threading.Thread(target=_watch_loop, name="tc2-watcher", daemon=True)
    _WATCH_THREAD = (t, True)
    t.start()


def stop_watcher():  # pragma: no cover
    global _WATCH_RUNNING
    _WATCH_RUNNING = False


def has_pending_reload() -> bool:
    if not _PENDING_REASONS:
        return False
    # Debounce window: ensure no recent changes are still happening
    if _LAST_CHANGE_MONO <= 0:
        return False
    idle = time.monotonic() - _LAST_CHANGE_MONO
    if idle < _DEBOUNCE_S:
        return False
    last_apply = _LAST_APPLY_TIME or 0.0
    if (time.time() - last_apply) < _MIN_APPLY_INTERVAL_S:
        return False
    return True


def consume_reload_reasons() -> List[str]:
    with _lazy_lock():
        reasons = list(sorted(_PENDING_REASONS))
        _PENDING_REASONS.clear()
    return reasons


def _import_patch_modules():
    for p in _PATCHES:
        if not p.enabled:
            continue
        for mod_name in p.modules:
            try:
                if mod_name.endswith(".py"):
                    mod_name = mod_name[:-3]
                __import__(mod_name)
                log(f"Imported patch module: {mod_name} from {p.id}")
            except Exception:
                log(f"Failed to import module {mod_name} from {p.id}:\n{traceback.format_exc()}")


def _iter_config_files() -> List[str]:
    files: List[str] = []
    # 2) %APPDATA%/config/*.json|*.toml
    cfg_dir = _path("config")
    for n in os.listdir(cfg_dir):
        if n.lower().endswith(".json") or n.lower().endswith(".toml"):
            files.append(os.path.join(cfg_dir, n))
    # 3) patches/*/config extracted
    for p in _PATCHES:
        if not p.enabled:
            continue
        if p.cache_cfg and os.path.isdir(p.cache_cfg):
            for root, _, names in os.walk(p.cache_cfg):
                for n in names:
                    if n.lower().endswith(".json") or n.lower().endswith(".toml"):
                        files.append(os.path.join(root, n))
    # 4) mods/*/config
    for d in _MOD_DIRS:
        cfg = os.path.join(d, "config")
        if os.path.isdir(cfg):
            for root, _, names in os.walk(cfg):
                for n in names:
                    if n.lower().endswith(".json") or n.lower().endswith(".toml"):
                        files.append(os.path.join(root, n))
    return files


def _rebuild_config() -> None:
    global _CONFIG
    # defaults (embedded) are minimal; we merge user and patch configs on top of them
    cfg: Dict[str, Any] = {"api": "v1", "enemies": {}, "map": {}}
    # Merge in order: appdata config -> patches -> mods
    for f in _iter_config_files():
        ext = os.path.splitext(f)[1].lower()
        data: Dict[str, Any] = {}
        if ext == ".json":
            data = _load_json_file(f)
        elif ext in (".toml", ".tml"):
            data = _load_toml_file(f)
        if data:
            cfg = _deep_merge(cfg, data)
    _CONFIG = cfg
    log("Config rebuilt")


def get_config() -> Dict[str, Any]:
    if not _BOOTSTRAPPED:
        bootstrap()
    return dict(_CONFIG)


def finalize_enemy_types(defaults: List[Tuple[str, str, str, str, int, int, int]]) -> List[Tuple[str, str, str, str, int, int, int]]:
    """Apply config overrides (hp, power, weight) by enemy name.

    We keep colors/chars from defaults.
    """
    if not _BOOTSTRAPPED:
        bootstrap()
    cfg = _CONFIG or {}
    overrides = dict((k, dict(v)) for k, v in (cfg.get("enemies") or {}).items())
    out: List[Tuple[str, str, str, str, int, int, int]] = []
    for name, ch, cv, cd, hp, pow_, w in defaults:
        o = overrides.get(name)
        if o:
            try:
                hp = int(o.get("hp", hp))
                pow_ = int(o.get("power", pow_))
                w = int(o.get("weight", w))
            except Exception:
                pass
        out.append((name, ch, cv, cd, int(hp), int(pow_), int(w)))
    return out


def get_active_summary() -> str:
    if not _BOOTSTRAPPED:
        bootstrap()
    n_patches = sum(1 for p in _PATCHES if p.enabled)
    n_mods = len(_MOD_DIRS)
    return f"Patches: {n_patches} active; Mods: {n_mods}"


def import_patch_zip(src_zip: str) -> Optional[str]:
    """Copy a user-selected zip into patches folder. Returns destination path or None."""
    try:
        if not os.path.isfile(src_zip):
            return None
        dst_dir = _path("patches")
        os.makedirs(dst_dir, exist_ok=True)
        base = os.path.basename(src_zip)
        dst = os.path.join(dst_dir, base)
        # If exists, back it up with timestamp
        if os.path.exists(dst):
            root, ext = os.path.splitext(base)
            ts = time.strftime("%Y%m%d-%H%M%S")
            dst = os.path.join(dst_dir, f"{root}-{ts}{ext}")
        shutil.copy2(src_zip, dst)
        log(f"Imported patch zip: {dst}")
        return dst
    except Exception:
        log(f"Failed to import patch zip {src_zip}:\n{traceback.format_exc()}")
        return None


def reload_all() -> Tuple[bool, str]:
    """Hot-reload external patches and configs.

    Returns (ok, message)
    """
    try:
        # Identify external module origins
        mount_roots = set(_SYS_PATH_MOUNTED)
        to_drop: List[str] = []
        for name, mod in list(sys.modules.items()):
            if not hasattr(mod, "__file__"):
                continue
            f = getattr(mod, "__file__", None)
            if not f:
                continue
            try:
                f = os.path.abspath(f)
            except Exception:
                continue
            if any(f.startswith(os.path.abspath(root)) for root in mount_roots):
                # keep patchloader itself
                if name.startswith("patchloader"):
                    continue
                to_drop.append(name)
        # Drop cached modules
        for n in to_drop:
            try:
                del sys.modules[n]
            except Exception:
                pass
        log(f"Dropped modules: {to_drop}")
        # Rescan + mount sources and reimport modules
        _scan_mount_sources()
        # Rebuild config
        _rebuild_config()
        _set_last_apply(True, "OK")
        return True, "Reloaded patches: OK"
    except Exception:
        log(f"Reload failed:\n{traceback.format_exc()}")
        _set_last_apply(False, "FAILED")
        return False, "Reload failed; see logs/loader.log"


def _set_last_apply(ok: bool, msg: str):
    global _LAST_APPLY_OK, _LAST_APPLY_TIME, _LAST_APPLY_MSG
    _LAST_APPLY_OK = bool(ok)
    _LAST_APPLY_TIME = time.time()
    _LAST_APPLY_MSG = str(msg)


def open_config_folder() -> Optional[str]:
    p = _path("config")
    try:
        if sys.platform.startswith("win"):
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f"open '{p}'")
        else:
            os.system(f"xdg-open '{p}'")
        return p
    except Exception:
        return None


def get_patches() -> List[PatchInfo]:
    if not _BOOTSTRAPPED:
        bootstrap()
    return list(_PATCHES)


def get_live_status() -> Dict[str, Any]:
    return {
        "enabled": bool(_WATCH_RUNNING),
        "last_ok": _LAST_APPLY_OK,
        "last_time": _LAST_APPLY_TIME,
        "pending": has_pending_reload(),
    }


def set_patch_enabled(pid: str, enabled: bool) -> None:
    state = _load_state()
    en = state.setdefault("enabled", {})
    en[pid] = bool(enabled)
    _save_state(state)


def adjust_patch_priority(pid: str, new_priority: int) -> None:
    state = _load_state()
    por = state.setdefault("priority_override", {})
    por[pid] = int(new_priority)
    _save_state(state)
