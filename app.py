# app.py — MediaSolver Web UI (Flask)

import os, sys, threading, time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from flask import Flask, render_template, request, jsonify
import os, time, socket, platform, subprocess, sys
from pathlib import Path
import os, socket
try:
    import psutil
except Exception:
    psutil = None
try:
    import winreg
except Exception:
    winreg = None

from flask import jsonify, request, make_response

# ---------- Bootstrap Resolve API (crucial en exe/venv/onefile) ----------
def _add_dll_dir(p: Optional[Path]):
    try:
        if p and p.exists():
            try:
                os.add_dll_directory(str(p))  # Py3.8+
            except Exception:
                os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass

def _bootstrap_resolve_api():
    # Exe dir + _MEIPASS (si packagé en one-file)
    try:
        exe_dir = Path(sys.executable).parent
        _add_dll_dir(exe_dir)
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        _add_dll_dir(Path(meipass))

    # Resolve bin & Modules
    # 1) chercher RESOLVE_SCRIPT_API, sinon chemin standard
    env_dll = os.environ.get("RESOLVE_SCRIPT_API")
    dll = Path(env_dll) if env_dll else Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    if dll.exists():
        os.environ.setdefault("RESOLVE_SCRIPT_API", str(dll))
        _add_dll_dir(dll.parent)

    modules_dir = Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
    if modules_dir.exists() and str(modules_dir) not in sys.path:
        sys.path.append(str(modules_dir))

_bootstrap_resolve_api()


def _bootstrap_resolve_worker(project_name: str):
    try:
        # 1) si Resolve déjà ON, tenter d'ouvrir/créer le projet
        if is_resolve_running():
            try:
                r = Resolve()
                pm = r.get_project_manager()
                if not pm:
                    r, pm = wait_api_ready(timeout=10.0, interval=1.0)
                if pm:
                    ensure_project_open(pm, project_name)
                    return
            except Exception:
                pass

        # 2) OFF → lancer
        exe = find_resolve_exe()
        if not exe:
            return
        cwd = str(Path(exe).parent)
        subprocess.Popen([exe], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 3) attendre l’API puis ouvrir/créer le projet
        r, pm = wait_api_ready(timeout=120.0, interval=1.5)
        if pm:
            ensure_project_open(pm, project_name)
    except Exception:
        pass




# ---------- Imports Resolve (après bootstrap) ----------
from pybmd import Resolve  # noqa: E402



# --- Dialogues natifs de sélection de dossier (Windows/macOS/Linux) ---
import tkinter as tk
from tkinter import filedialog

def pick_folder_dialog(initial_dir: Optional[str] = None) -> str:
    """
    Ouvre une boîte native 'Choisir un dossier' et retourne le chemin.
    Retourne '' si l'utilisateur annule.
    """
    root = tk.Tk()
    root.withdraw()
    # place la boîte au premier plan
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass
    try:
        path = filedialog.askdirectory(
            initialdir=initial_dir or os.getcwd(),
            title="Sélectionner un dossier"
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass
    return path or ""





# ---------- Helpers Resolve ----------


def _file_exists(p: str) -> bool:
    try:
        return Path(p).is_file()
    except Exception:
        return False

def find_resolve_exe() -> str | None:
    """
    Tente de localiser Resolve.exe :
    - variable d'env RESOLVE_EXE
    - chemin standard Program Files
    - Registre Windows (InstallDir)
    - scan léger dans Program Files\Blackmagic Design\
    """
    # 1) env
    envp = os.environ.get("RESOLVE_EXE")
    if envp and _file_exists(envp):
        return envp

    # 2) standard
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    std = os.path.join(pf, r"Blackmagic Design\DaVinci Resolve\Resolve.exe")
    if _file_exists(std):
        return std

    # 3) registre
    if winreg is not None:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for keypath in (
                r"SOFTWARE\Blackmagic Design\DaVinci Resolve",
                r"SOFTWARE\WOW6432Node\Blackmagic Design\DaVinci Resolve",
            ):
                try:
                    with winreg.OpenKey(hive, keypath) as k:
                        for valname in ("InstallDir", "InstallFolder", "InstallPath"):
                            try:
                                v, _ = winreg.QueryValueEx(k, valname)
                                if v:
                                    cand = os.path.join(v, "Resolve.exe")
                                    if _file_exists(cand):
                                        return cand
                            except OSError:
                                pass
                except OSError:
                    pass

    # 4) scan rapide dans Blackmagic Design
    root = os.path.join(pf, "Blackmagic Design")
    try:
        for sub in ("DaVinci Resolve", "DaVinci Resolve Studio"):
            cand = os.path.join(root, sub, "Resolve.exe")
            if _file_exists(cand):
                return cand
    except Exception:
        pass
    return None

def is_resolve_running() -> bool:
    # essai API (plus fiable)
    try:
        r = Resolve()
        return bool(r.get_project_manager())
    except Exception:
        pass
    # fallback process
    if psutil is not None:
        try:
            for p in psutil.process_iter(["name"]):
                name = (p.info.get("name") or "").lower()
                if "resolve" in name:
                    return True
        except Exception:
            pass
    return False

def wait_api_ready(timeout: float = 90.0, interval: float = 1.5):
    """
    Attend que l'API Resolve soit dispo et renvoie (Resolve, ProjectManager) ou (None, None).
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = Resolve()
            pm = r.get_project_manager()
            if pm:
                return r, pm
        except Exception:
            pass
        time.sleep(interval)
    return None, None

def _pm_call(pm, name: str, *args, **kw):
    """
    Appelle une méthode du ProjectManager en gérant snake_case / CamelCase.
    """
    for attr in (name, "".join(part.capitalize() for part in name.split("_"))):
        if hasattr(pm, attr):
            return getattr(pm, attr)(*args, **kw)
    raise AttributeError(f"ProjectManager has no method '{name}'/'{attr}'")

def ensure_project_open(pm, project_name: str):
    """
    Charge ou crée le projet 'project_name'. Retourne True si OK.
    """
    # liste des projets
    proj_list = []
    try:
        proj_list = _pm_call(pm, "get_project_list") or []
    except Exception:
        pass

    if proj_list and project_name in proj_list:
        ok = _pm_call(pm, "load_project", project_name)
        return bool(ok)

    # Essaie de charger quand même au cas où la liste est vide sur certaines builds
    try:
        ok = _pm_call(pm, "load_project", project_name)
        if ok:
            return True
    except Exception:
        pass

    # sinon créer
    created = None
    try:
        created = _pm_call(pm, "create_project", project_name)
    except Exception:
        # variantes API native
        for alt in ("CreateProject",):
            if hasattr(pm, alt):
                created = getattr(pm, alt)(project_name)
                break
    return bool(created)



def get_project(resolve=None):
    r = resolve or Resolve()
    pm = r.get_project_manager()
    project = pm.get_current_project()
    if not project:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")
    return r, project

def list_presets() -> List[str]:
    _, project = get_project()
    for attr in ("get_render_preset_list", "GetRenderPresets", "get_render_presets"):
        if hasattr(project, attr):
            try:
                presets = getattr(project, attr)() or []
                return list(presets) if not isinstance(presets, dict) else list(presets.keys())
            except Exception:
                pass
    return []

def find_or_create_bin_path(media_pool, path_parts: List[str]):
    root = media_pool.get_root_folder()
    cur = root
    for name in path_parts:
        if not name:
            continue
        subs = []
        try:
            subs = cur.get_sub_folder_list() or []
        except AttributeError:
            for attr in ("GetSubFolderList", "GetSubFolders"):
                if hasattr(cur, attr):
                    subs = getattr(cur, attr)() or []
                    break
        hit = None
        for sf in subs or []:
            n = sf.get_name() if hasattr(sf, "get_name") else getattr(sf, "GetName")()
            if n == name:
                hit = sf; break
        if hit is None:
            hit = media_pool.add_sub_folder(cur, name)
            if not hit:
                raise RuntimeError(f"Impossible de créer le bin '{name}'.")
        cur = hit
    if not media_pool.set_current_folder(cur):
        raise RuntimeError("Impossible de sélectionner le bin cible.")
    return cur

def collect_clips(folder, recursive: bool = False) -> List[object]:
    clips: List[object] = []
    try:
        clips.extend(folder.get_clip_list() or [])
    except AttributeError:
        if hasattr(folder, "GetClipList"):
            clips.extend(folder.GetClipList() or [])
    if recursive:
        subs = []
        try:
            subs = folder.get_sub_folder_list() or []
        except AttributeError:
            for attr in ("GetSubFolderList", "GetSubFolders"):
                if hasattr(folder, attr):
                    subs = getattr(folder, attr)() or []
                    break
        for sf in subs or []:
            clips.extend(collect_clips(sf, recursive=True))
    return clips

def filter_video_audio(items: List[object], allow_stills: bool) -> List[object]:
    if allow_stills:
        return items
    out = []
    for it in items:
        props = {}
        for attr in ("GetClipProperty", "get_clip_property"):
            if hasattr(it, attr):
                try:
                    props = getattr(it, attr)() or {}
                except Exception:
                    props = {}
                break
        ctype = (props.get("Type") or props.get("MediaType") or "").lower()
        if "still" in ctype:
            continue
        out.append(it)
    return out

def clip_source_name(clip) -> str:
    props = {}
    for attr in ("GetClipProperty", "get_clip_property"):
        if hasattr(clip, attr):
            try:
                props = getattr(clip, attr)() or {}
            except Exception:
                pass
            break
    if props.get("File Path"):
        return Path(props["File Path"]).name
    if props.get("Filename"):
        return props["Filename"]
    try:
        return clip.get_name()
    except Exception:
        return getattr(clip, "GetName", lambda: "UNKNOWN")()

def maybe_set_first_timeline_settings(project, fps: Optional[float], width: Optional[int], height: Optional[int]):
    try:
        tl_count = project.get_timeline_count()
    except AttributeError:
        tl_count = project.GetTimelineCount()
    if tl_count > 0:
        return
    if fps:
        project.set_setting("timelineFrameRate", str(fps))
        project.set_setting("timelinePlaybackFrameRate", str(fps))
    if width and height:
        project.set_setting("timelineResolutionWidth", str(width))
        project.set_setting("timelineResolutionHeight", str(height))

def get_wrapped_timeline_by_name(project, name: str):
    try:
        count = project.get_timeline_count()
        getter = project.get_timeline_by_index
    except AttributeError:
        count = project.GetTimelineCount()
        getter = project.GetTimelineByIndex
    for i in range(1, count + 1):
        tl_i = getter(i)
        if not tl_i:
            continue
        try:
            nm = tl_i.get_name()
        except AttributeError:
            nm = tl_i.GetName()
        if nm == name:
            return tl_i
    return None



# --- Helpers ETA / % ---
def _sec_to_hms(secs):
    try:
        secs = max(0, int(float(secs)))
    except Exception:
        return "–"
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"

def _eta_from_status(st: dict, pct: int, started_at: float | None):
    """Prend en charge EstimatedTimeRemainingInMs (prioritaire) + fallbacks texte/seconds + calcul si besoin."""
    if not isinstance(st, dict):
        return None
    # 1) clé en millisecondes (ta build 19.1.3)
    ms = st.get("EstimatedTimeRemainingInMs")
    if ms is not None:
        try:
            return _sec_to_hms(float(ms) / 1000.0)
        except Exception:
            pass
    # 2) fallbacks éventuels fournis par d'autres builds
    for k in ("TimeRemaining", "EstimatedTimeRemaining", "ETA"):
        v = st.get(k)
        if v in (None, "", 0, "0"):
            continue
        if isinstance(v, (int, float)):
            return _sec_to_hms(v)
        if isinstance(v, str):
            s = v.strip()
            if ":" in s:             # "mm:ss" ou "hh:mm:ss"
                return s
            try:                      # "120" => secondes
                return _sec_to_hms(float(s))
            except Exception:
                return s              # texte libre ("about a minute")
    # 3) fallback calculé si on a un pourcentage > 0
    if started_at and pct > 0:
        elapsed = time.time() - started_at
        remaining = elapsed * (100 - pct) / pct
        return _sec_to_hms(remaining)
    return None


# ---------- Job state (thread-safe) ----------
JOB = {
    "state": "idle",        # idle | preparing | rendering | done | error
    "percent": 0,
    "eta": None,
    "fps": None,
    "current_clip": None,
    "message": "",
    "error": "",
    "started_at": None,
    "finished_at": None,
    "job_id": None,
}
JOB_LOCK = threading.Lock()

def job_update(**kwargs):
    with JOB_LOCK:
        JOB.update(kwargs)

def parse_progress_dict(st: dict) -> int:
    if not isinstance(st, dict):
        return 0
    for key in ("Progress", "JobPercentage", "CompletionPercentage", "PercentComplete"):
        v = st.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if v.endswith("%"):
                v = v[:-1]
            try:
                v = float(v)
            except Exception:
                continue
        if isinstance(v, (int, float)):
            return max(0, min(100, int(round(v))))
    return 0

def start_rendering(project, job_ids: List[str]) -> bool:
    for attr in ("start_rendering", "StartRendering"):
        if hasattr(project, attr):
            fn = getattr(project, attr)
            try:
                return bool(fn(job_ids))
            except TypeError:
                try:
                    return bool(fn())
                except Exception:
                    pass
            except Exception:
                pass
    return False

def is_rendering(project) -> bool:
    for attr in ("is_rendering_in_progress", "IsRenderingInProgress"):
        if hasattr(project, attr):
            try:
                return bool(getattr(project, attr)())
            except Exception:
                pass
    return False

def get_job_status(project, job_id: str) -> Optional[dict]:
    for attr in ("get_render_job_status", "GetRenderJobStatus"):
        if hasattr(project, attr):
            try:
                return getattr(project, attr)(job_id)
            except Exception:
                return None
    return None

def add_render_job(project) -> Optional[str]:
    for attr in ("add_render_job", "AddRenderJob"):
        if hasattr(project, attr):
            try:
                return getattr(project, attr)()
            except Exception:
                return None
    return None

def delete_render_job(project, job_id: str) -> None:
    for attr in ("delete_render_job", "DeleteRenderJob"):
        if hasattr(project, attr):
            try:
                getattr(project, attr)(job_id)
            except Exception:
                pass


# ---------- Pipeline thread ----------
def run_pipeline_thread(src_folder: str, outdir: str, preset_name: str, recursive: bool = False):
    try:
        # état initial
        job_update(state="preparing", percent=0, message="Préparation…", error="", eta=None,
                   started_at=time.time(), finished_at=None, job_id=None, job_status="")

        # --- Resolve + projet ---
        r, project = get_project()
        media_pool = project.get_media_pool()

        # --- 1) Lister MP4 ---
        src = Path(src_folder).expanduser().resolve()
        mp4s = [str(p) for p in (src.rglob("*.mp4") if recursive else src.glob("*.mp4"))]
        if not mp4s:
            raise RuntimeError("Aucun .mp4 trouvé dans le dossier source.")
        job_update(message=f"Import {len(mp4s)} fichiers…", percent=3)

        # --- 2) Bin daté ---
        tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        bin_name = f"MEDIASOLVERJOB_{tag}"
        dest_bin = find_or_create_bin_path(media_pool, [bin_name])

        # --- 3) Import Media Pool ---
        items = media_pool.import_media(mp4s)
        if not items:
            raise RuntimeError("Aucun média importé (Media Storage ?).")
        job_update(message="Import terminé.", percent=10)

        # --- 4) Timeline (tri alpha par nom de fichier) ---
        clips = collect_clips(dest_bin, recursive=False)
        clips = filter_video_audio(clips, allow_stills=False)
        if not clips:
            raise RuntimeError("Aucun clip utilisable.")
        clips.sort(key=lambda c: clip_source_name(c).lower())

        maybe_set_first_timeline_settings(project, None, None, None)
        tl_name = bin_name
        try:
            tl_obj = media_pool.create_timeline_from_clips(tl_name, clips)
            if not tl_obj:
                raise RuntimeError("create_timeline_from_clips() a renvoyé None")
        except Exception:
            bmd_mp = getattr(media_pool, "_media_pool", None)
            if not bmd_mp:
                raise
            tl_obj = bmd_mp.CreateTimelineFromClips(tl_name, clips)
            if not tl_obj:
                empty = media_pool.create_empty_timeline(tl_name) or bmd_mp.CreateEmptyTimeline(tl_name)
                if not empty:
                    raise RuntimeError("Impossible de créer une timeline vide.")
                try:
                    project.set_current_timeline(empty)
                except AttributeError:
                    project.SetCurrentTimeline(empty)
                ok = False
                try:
                    ok = bool(media_pool.append_to_timeline(clips))
                except Exception:
                    pass
                if not ok:
                    try:
                        ok = bool(bmd_mp.AppendToTimeline(clips))
                    except Exception:
                        ok = False
                if not ok:
                    raise RuntimeError("Append vers la timeline vide a échoué.")

        tl_wrapped = get_wrapped_timeline_by_name(project, tl_name)
        if not tl_wrapped:
            raise RuntimeError("Timeline introuvable après création.")
        project.set_current_timeline(tl_wrapped)
        job_update(message="Timeline prête.", percent=20)

        # --- 5) Preset + settings ---
        presets = list_presets()
        if presets and preset_name not in presets:
            raise RuntimeError(f"Preset '{preset_name}' introuvable. Disponibles: {', '.join(presets)}")
        for attr in ("load_render_preset", "LoadRenderPreset"):
            if hasattr(project, attr):
                try:
                    getattr(project, attr)(preset_name)
                except Exception:
                    pass
        settings = {"TargetDir": str(Path(outdir).expanduser().resolve()), "UniqueFilename": True}
        for attr in ("set_render_settings", "SetRenderSettings"):
            if hasattr(project, attr):
                try:
                    getattr(project, attr)(settings)
                except Exception:
                    pass

        # --- 6) Render queue + start ---
        job_id = add_render_job(project)
        if not job_id:
            raise RuntimeError("AddRenderJob a échoué.")
        job_update(state="rendering", message="Encodage…", job_id=job_id, percent=20, job_status="Queued")

        if not start_rendering(project, [job_id]):
            # tentative sans job_ids pour anciennes builds
            if not start_rendering(project, []):
                delete_render_job(project, job_id)
                raise RuntimeError("StartRendering a échoué.")

        # --- 7) Boucle de progression robuste (reprend après reload) ---
        last_pct = -1
        while True:
            st = get_job_status(project, job_id) or {}
            job_status = (st.get("JobStatus") or st.get("Status") or st.get("State") or "").strip()
            job_status_l = job_status.lower()

            prog = parse_progress_dict(st)          # gère CompletionPercentage/Progress/...
            pct = max(20, min(100, int(prog)))      # 20..100 pour l'affichage global
            eta = _eta_from_status(st, pct, JOB.get("started_at"))

            # pousser les infos (pour reprise après reload)
            if pct != last_pct:
                job_update(percent=pct, eta=eta, job_status=job_status)
                last_pct = pct
            else:
                # met à jour ETA même si % inchangé (utile sur reload)
                job_update(eta=eta, job_status=job_status)

            # états terminaux négatifs -> error (rouge)
            if ("cancel" in job_status_l) or ("fail" in job_status_l) or ("error" in job_status_l):
                job_update(state="error", job_status=job_status, percent=min(pct, 99))
                break

            # succès -> done (vert)
            if ("complete" in job_status_l) or ("success" in job_status_l) or ("finished" in job_status_l) or (
                prog >= 100 and not st.get("Error")
            ):
                job_update(state="done", job_status=job_status, percent=100)
                break

            time.sleep(0.5)

        # nettoyage sans écraser l'état final
        try:
            delete_render_job(project, job_id)
        except Exception:
            pass

        # marquer la fin si pas déjà fait (ne PAS convertir un error en done)
        with JOB_LOCK:
            if JOB.get("state") not in ("error", "done"):
                JOB["state"] = "done"
                JOB["percent"] = max(JOB.get("percent") or 100, 100)
            JOB["finished_at"] = time.time()

    except Exception as e:
        job_update(state="error", error=str(e), message="Erreur ❌", finished_at=time.time())

# ---------- Flask ----------
app = Flask(__name__)

@app.route("/")
def index():
    # On essaie de charger la liste des presets pour pré-remplir (fallback côté client via /presets)
    try:
        presets = list_presets()
    except Exception:
        presets = []
    return render_template("index.html", presets=presets)


@app.route("/start-resolve", methods=["POST"])
def start_resolve():
    """
    Démarre/attache Resolve en tâche de fond et ouvre/crée le projet 'MediaSolver'.
    Répond immédiatement pour éviter les timeouts côté navigateur.
    """
    data = request.get_json(silent=True) or {}
    project_name = data.get("project") or "MediaSolver"

    # lance le bootstrap en arrière-plan, réponse immédiate
    t = threading.Thread(target=_bootstrap_resolve_worker, args=(project_name,), daemon=True)
    t.start()

    resp = make_response(jsonify({"ok": True, "message": "Resolve starting in background"}))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp



@app.route("/pick-folder/<which>", methods=["POST"])
def api_pick_folder(which: str):
    """
    Ouvre un sélecteur natif et renvoie { ok: true, path: "C:\\..."}.
    which ∈ {"src", "out"} (libre, on l'utilise juste côté UI).
    """
    try:
        # optionnel : point de départ différent selon le champ
        initial = os.path.expanduser("~")
        path = pick_folder_dialog(initial_dir=initial)
        if not path:
            return jsonify({"ok": False, "error": "Sélection annulée.", "path": ""}), 200
        return jsonify({"ok": True, "path": path})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "path": ""}), 500


@app.route("/presets")
def api_presets():
    # si Resolve OFF -> répondre vite sans bloquer
    if not is_resolve_running_fast():
        return jsonify({"ok": False, "presets": [], "error": "Resolve OFF"}), 200
    # sinon, votre logique actuelle list_presets() ici :
    try:
        presets = list_presets() or []
        return jsonify({"ok": True, "presets": presets})
    except Exception as e:
        return jsonify({"ok": False, "presets": [], "error": str(e)}), 200


@app.route("/start", methods=["POST"])
def api_start():
    data = request.get_json(force=True)
    src = data.get("src") or ""
    outdir = data.get("outdir") or ""
    preset = data.get("preset") or ""
    recursive = bool(data.get("recursive", False))

    if not src or not outdir or not preset:
        return jsonify({"ok": False, "error": "Champs requis: dossier source, dossier de sortie, preset."}), 400

    with JOB_LOCK:
        if JOB["state"] in ("preparing", "rendering"):
            return jsonify({"ok": False, "error": "Un job est déjà en cours."}), 409
        JOB.update({"state": "idle", "percent": 0, "error": "", "message": ""})

    t = threading.Thread(target=run_pipeline_thread, args=(src, outdir, preset, recursive), daemon=True)
    t.start()
    return jsonify({"ok": True})

from flask import jsonify, make_response

@app.route("/progress")
def api_progress():
    # renvoyer TOUT l'état courant (persistant en mémoire du process)
    with JOB_LOCK:
        payload = dict(JOB)  # copie pour éviter une mutation concurrente

    # Anti-cache pour que le navigateur ne serve pas une vieille réponse
    resp = make_response(jsonify(payload))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/debug/jobstatus")
def debug_jobstatus():
    with JOB_LOCK:
        jid = JOB.get("job_id")
    if not jid:
        return jsonify({"ok": False, "error": "Aucun job actif"}), 400
    _, project = get_project()
    st = get_job_status(project, jid) or {}
    return jsonify({"ok": True, "raw": st})


def is_resolve_running_fast() -> bool:
    """Check ultra-rapide basé sur la présence du process Resolve (pas d'attachement API)."""
    if psutil is None:
        return False
    try:
        for p in psutil.process_iter(["name"]):
            name = (p.info.get("name") or "").lower()
            if "resolve" in name:
                return True
    except Exception:
        pass
    return False

@app.route("/hoststatus")
def hoststatus():
    """Renvoie { ok, hostname, resolve_running } sans bloquer."""
    hostname = socket.gethostname() or platform.node() or os.environ.get("COMPUTERNAME") or "Unknown Host"
    running = is_resolve_running_fast()
    resp = make_response(jsonify({"ok": True, "hostname": hostname, "resolve_running": running}))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp

if __name__ == "__main__":
    # ⚠️ pas de reloader ni debug en usage normal, sinon les requêtes se font couper
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
