# ensure_mediasolver_safe.py — pybmd only / Windows / Python 3.13
# Garantit que "MediaSolver" est chargé, sans prompt, rapide et robuste.

import os, sys, time, threading, re
from pathlib import Path

TARGET_NAME = "MediaSolver"

# --- Bootstrap DLL Resolve (Windows) ---
def _bootstrap_resolve_api():
    dll = os.environ.get("RESOLVE_SCRIPT_API", "")
    p = Path(dll) if dll else Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    if p.exists():
        os.environ["RESOLVE_SCRIPT_API"] = str(p)
        try:
            os.add_dll_directory(str(p.parent))
        except Exception:
            pass
        if str(p.parent) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(p.parent) + os.pathsep + os.environ.get("PATH", "")

_bootstrap_resolve_api()
# ---------------------------------------

# ---------- Utils ----------
def _call_method(obj, *names):
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    raise AttributeError(f"Aucune des méthodes {names} n'existe sur {obj!r}")

def _proj_name(project) -> str:
    try:
        return project.get_name()
    except AttributeError:
        return project.GetName()

def _with_timeout(fn, timeout_s: float):
    box = {"res": None, "exc": None}
    def runner():
        try:
            box["res"] = fn()
        except Exception as e:
            box["exc"] = e
    th = threading.Thread(target=runner, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        return False, TimeoutError("timeout")
    if box["exc"] is not None:
        return True, box["exc"]
    return True, box["res"]

def _get_projects_in_current_folder(pm):
    get_list = _call_method(pm, "get_project_list_in_current_folder", "GetProjectListInCurrentFolder")
    return get_list() or []

def _is_probably_unnamed(name: str) -> bool:
    if not name:
        return True
    patterns = [
        r"^untitled project(\s*\d+)?$",
        r"^projet sans titre(\s*\d+)?$",
        r"^sans titre(\s*\d+)?$",
        r"^unbenannt(es)? projekt(\s*\d+)?$",
        r"^proyecto sin título(\s*\d+)?$",
    ]
    n = name.strip().lower()
    return any(re.match(p, n) for p in patterns)

def _dfs_find_project_fast(pm, target: str, op_timeout: float, max_depth: int = 6) -> bool:
    goto_root = _call_method(pm, "goto_root_folder", "GotoRootFolder")
    goto_parent = _call_method(pm, "goto_parent_folder", "GotoParentFolder")
    open_folder = _call_method(pm, "open_folder", "OpenFolder")
    get_folders = _call_method(pm, "get_folder_list_in_current_folder", "GetFolderListInCurrentFolder")

    ok, _ = _with_timeout(goto_root, op_timeout)
    if not ok:
        return False

    def in_cur_has(name: str) -> bool:
        lst = _get_projects_in_current_folder(pm)
        return name in lst

    def dfs(depth: int) -> bool:
        if depth > max_depth:
            return False
        ok, res = _with_timeout(lambda: in_cur_has(target), op_timeout)
        if not ok:
            return False
        if res:
            return True
        ok, subs = _with_timeout(get_folders, op_timeout)
        if not ok:
            return False
        for f in (subs or []):
            ok, opened = _with_timeout(lambda f=f: open_folder(f), op_timeout)
            if not ok or not opened:
                continue
            if dfs(depth + 1):
                return True
            ok, _ = _with_timeout(goto_parent, op_timeout)
            if not ok:
                return False
        return False

    found = dfs(0)
    _with_timeout(goto_root, op_timeout)
    return found

# ---------- Main ----------
def ensure_mediasolver_ready(init_timeout: float = 0.75, op_timeout: float = 0.75, retries: int = 1):
    """
    Retourne toujours (ok: bool, status: str, details: str)

    status ∈ {
      'OK', 'APP_OFF', 'NO_PM', 'UNRESPONSIVE',
      'CLOSE_FAILED', 'CREATE_FAILED', 'LOAD_FAILED', 'ERROR'
    }
    """
    from pybmd import Resolve, error as pyerr

    def step_once():
        # 1) Resolve
        ok, res = _with_timeout(lambda: Resolve(), init_timeout)
        if not ok:
            return False, "UNRESPONSIVE", "Resolve() timeout"
        if isinstance(res, Exception):
            if isinstance(res, pyerr.ResolveInitError):
                return False, "APP_OFF", "Engine unreachable"
            return False, "ERROR", f"Resolve() error: {res!r}"
        resolve = res

        # 2) PM
        ok, res = _with_timeout(lambda: resolve.get_project_manager(), op_timeout)
        if not ok:
            return False, "UNRESPONSIVE", "get_project_manager() timeout"
        if isinstance(res, Exception) or not res:
            return False, "NO_PM", f"get_project_manager() error: {res!r}"
        pm = res

        # 3) Projet courant
        ok, res = _with_timeout(lambda: _call_method(pm, "get_current_project", "GetCurrentProject")(), op_timeout)
        if not ok:
            return False, "UNRESPONSIVE", "get_current_project() timeout"
        if isinstance(res, Exception):
            return False, "ERROR", f"get_current_project() error: {res!r}"
        cur = res

        if cur and _proj_name(cur) == TARGET_NAME:
            return True, "OK", "MediaSolver already loaded"

        # ---------- IMPORTANT : comportement “sans nom” ----------
        if cur:
            cur_name = _proj_name(cur) or ""
            # Est-ce un nom réel dans le dossier courant ?
            ok, cur_list = _with_timeout(lambda: _get_projects_in_current_folder(pm), op_timeout)
            listed_here = (ok and not isinstance(cur_list, Exception) and cur_name in (cur_list or []))
            is_unnamed = _is_probably_unnamed(cur_name) or not listed_here

            if is_unnamed:
                # ⚡ Pas de save, pas de close explicite -> on tente DIRECT load/create MediaSolver
                exists = _dfs_find_project_fast(pm, TARGET_NAME, op_timeout)
                if not exists:
                    ok, _ = _with_timeout(lambda: _call_method(pm, "goto_root_folder", "GotoRootFolder")(), op_timeout)
                    if not ok:
                        return False, "UNRESPONSIVE", "GotoRootFolder timeout"
                    ok, newp = _with_timeout(lambda: _call_method(pm, "create_project", "CreateProject")(TARGET_NAME), op_timeout)
                    if not ok:
                        return False, "UNRESPONSIVE", "CreateProject timeout"
                    if isinstance(newp, Exception) or not newp:
                        return False, "CREATE_FAILED", "CreateProject returned None/Exception"

                # Charge si pas déjà actif
                ok, res = _with_timeout(lambda: _call_method(pm, "get_current_project", "GetCurrentProject")(), op_timeout)
                loaded = (ok and not isinstance(res, Exception) and res and _proj_name(res) == TARGET_NAME)
                if not loaded:
                    ok, lres = _with_timeout(lambda: _call_method(pm, "load_project", "LoadProject")(TARGET_NAME), op_timeout)
                    if not ok:
                        return False, "UNRESPONSIVE", "LoadProject timeout"
                    if isinstance(lres, Exception) or not lres:
                        return False, "LOAD_FAILED", "LoadProject returned None/Exception"

                # Vérif finale
                ok, res = _with_timeout(lambda: _call_method(pm, "get_current_project", "GetCurrentProject")(), op_timeout)
                if not ok:
                    return False, "UNRESPONSIVE", "get_current_project() timeout (final)"
                if isinstance(res, Exception) or not res or _proj_name(res) != TARGET_NAME:
                    return False, "LOAD_FAILED", "MediaSolver not active after load"
                return True, "OK", "MediaSolver loaded (unnamed project replaced)"

            # ---------- Cas projet nommé : save + close ----------
            # Save best-effort (ne bloque pas si échec)
            _with_timeout(lambda: _call_method(pm, "save_project", "SaveProject")(), op_timeout)

            # Fermer
            closed = False
            for close_name in ("close_project", "CloseProject"):
                if hasattr(pm, close_name):
                    def _try_close_with_arg():
                        try:
                            return getattr(pm, close_name)(cur)
                        except TypeError:
                            return getattr(pm, close_name)()
                    ok, cres = _with_timeout(_try_close_with_arg, op_timeout)
                    if ok and not isinstance(cres, Exception) and cres:
                        closed = True
                        break
            if not closed:
                return False, "CLOSE_FAILED", "Could not close current project"

        # 4) Assurer MediaSolver (projet courant était None OU nommé et fermé)
        exists = _dfs_find_project_fast(pm, TARGET_NAME, op_timeout)
        if not exists:
            ok, _ = _with_timeout(lambda: _call_method(pm, "goto_root_folder", "GotoRootFolder")(), op_timeout)
            if not ok:
                return False, "UNRESPONSIVE", "GotoRootFolder timeout"
            ok, newp = _with_timeout(lambda: _call_method(pm, "create_project", "CreateProject")(TARGET_NAME), op_timeout)
            if not ok:
                return False, "UNRESPONSIVE", "CreateProject timeout"
            if isinstance(newp, Exception) or not newp:
                return False, "CREATE_FAILED", "CreateProject returned None/Exception"

        ok, res = _with_timeout(lambda: _call_method(pm, "get_current_project", "GetCurrentProject")(), op_timeout)
        loaded = (ok and not isinstance(res, Exception) and res and _proj_name(res) == TARGET_NAME)
        if not loaded:
            ok, lres = _with_timeout(lambda: _call_method(pm, "load_project", "LoadProject")(TARGET_NAME), op_timeout)
            if not ok:
                return False, "UNRESPONSIVE", "LoadProject timeout"
            if isinstance(lres, Exception) or not lres:
                return False, "LOAD_FAILED", "LoadProject returned None/Exception"

        ok, res = _with_timeout(lambda: _call_method(pm, "get_current_project", "GetCurrentProject")(), op_timeout)
        if not ok:
            return False, "UNRESPONSIVE", "get_current_project() timeout (final)"
        if isinstance(res, Exception) or not res or _proj_name(res) != TARGET_NAME:
            return False, "LOAD_FAILED", "MediaSolver not active after load"
        return True, "OK", "MediaSolver loaded"

    attempts = max(1, retries + 1)
    last = (False, "ERROR", "not-run")
    for _ in range(attempts):
        last = step_once()
        ok, status, _ = last
        if status in ("APP_OFF", "NO_PM"):
            break
        if ok:
            break
        time.sleep(0.15)
    return last

# --- CLI démo ---
if __name__ == "__main__":
    ok, status, details = ensure_mediasolver_ready(init_timeout=0.7, op_timeout=0.7, retries=1)
    print(f"{'OK' if ok else 'FAIL'} | {status} | {details}")
    codes = {"OK": 0, "APP_OFF": 3, "NO_PM": 3, "UNRESPONSIVE": 4, "CLOSE_FAILED": 5, "CREATE_FAILED": 6, "LOAD_FAILED": 7, "ERROR": 8}
    sys.exit(0 if ok else codes.get(status, 8))
