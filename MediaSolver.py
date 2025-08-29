from pathlib import Path
import sys
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from pybmd import Resolve

# ---------------- Utils communs ----------------
def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def list_mp4(folder: Path, recursive: bool) -> List[str]:
    if not folder.exists():
        raise FileNotFoundError(f"Dossier introuvable: {folder}")
    pat = "**/*.mp4" if recursive else "*.mp4"
    return [str(p.resolve()) for p in folder.glob(pat)]

def get_project(resolve):
    pm = resolve.get_project_manager()
    project = pm.get_current_project()
    if not project:
        raise RuntimeError("Aucun projet ouvert dans Resolve.")
    return project

def ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)

def clip_source_name(clip) -> str:
    """Retourne le nom de fichier source (ou clip name fallback)."""
    props = {}
    for attr in ("GetClipProperty", "get_clip_property"):
        if hasattr(clip, attr):
            try:
                props = getattr(clip, attr)() or {}
            except Exception:
                pass
            break
    # Selon version: "File Path", "Filename", etc.
    if "File Path" in props and props["File Path"]:
        return Path(props["File Path"]).name
    if "Filename" in props and props["Filename"]:
        return props["Filename"]
    # fallback: nom du clip Resolve
    try:
        return clip.get_name()
    except Exception:
        return getattr(clip, "GetName", lambda: "UNKNOWN")()


# ---------------- Media Pool ----------------
def find_or_create_bin_path(media_pool, path_parts: List[str]):
    """Crée/retourne Master/path_parts[0]/... et le sélectionne."""
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
                raise RuntimeError(f"Impossible de créer le bin '{name}'")
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
    """Retourne la timeline (wrapper pybmd) par nom."""
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

# ---------------- Render helpers ----------------
def list_presets(project) -> List[str]:
    for attr in ("get_render_preset_list", "GetRenderPresets", "get_render_presets"):
        if hasattr(project, attr):
            try:
                presets = getattr(project, attr)() or []
                return list(presets) if not isinstance(presets, dict) else list(presets.keys())
            except Exception:
                pass
    return []

def load_preset(project, name: str) -> bool:
    for attr in ("load_render_preset", "LoadRenderPreset"):
        if hasattr(project, attr):
            try:
                return bool(getattr(project, attr)(name))
            except Exception:
                pass
    return False

def set_render_settings(project, settings: Dict[str, Any]) -> bool:
    for attr in ("set_render_settings", "SetRenderSettings"):
        if hasattr(project, attr):
            try:
                return bool(getattr(project, attr)(settings))
            except Exception:
                pass
    return False

def set_render_mode(project, mode: str) -> bool:
    for attr in ("set_current_render_mode", "SetCurrentRenderMode"):
        if hasattr(project, attr):
            try:
                return bool(getattr(project, attr)(mode))
            except Exception:
                pass
    return True

def add_render_job(project) -> Optional[str]:
    for attr in ("add_render_job", "AddRenderJob"):
        if hasattr(project, attr):
            try:
                return getattr(project, attr)()
            except Exception:
                return None
    return None

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

def delete_render_job(project, job_id: str) -> None:
    for attr in ("delete_render_job", "DeleteRenderJob"):
        if hasattr(project, attr):
            try:
                getattr(project, attr)(job_id)
            except Exception:
                pass

# ---------------- Pipeline ----------------
def run_pipeline(
    src_folder: str,
    preset_name: str,
    recursive: bool,
    bin_parent: Optional[str],
    bin_prefix: str,
    tl_prefix: Optional[str],
    allow_stills: bool,
    fps: Optional[float],
    width: Optional[int],
    height: Optional[int],
    outdir: Optional[str],
    outname: Optional[str],
    unique: bool,
    single: bool,
    fmt: Optional[str],
    codec: Optional[str],
):
    resolve = Resolve()
    project = get_project(resolve)
    media_pool = project.get_media_pool()

    # 1) Fichiers source
    sources = list_mp4(Path(src_folder).expanduser().resolve(), recursive)
    if not sources:
        raise RuntimeError("Aucun .mp4 trouvé dans le dossier source.")
    print(f"[INFO] Fichiers détectés: {len(sources)}")

    # 2) Bin daté
    tag = now_tag()
    bin_name = f"{(bin_prefix or '')}{tag}"
    path_parts = []
    if bin_parent:
        path_parts.extend([p for p in Path(bin_parent).parts if p not in ("/", "\\")])
    path_parts.append(bin_name)
    dest_bin = find_or_create_bin_path(media_pool, path_parts)
    print(f"[INFO] Bin cible: {bin_name}")

    # 3) Import
    items = media_pool.import_media(sources)
    if not items:
        raise RuntimeError("Aucun média importé (vérifie Media Storage et redémarre Resolve).")
    print(f"[SUCCESS] Importés dans '{bin_name}': {len(items)} élément(s).")

    # 4) Timeline avec tous les clips du bin
    clips = collect_clips(dest_bin, recursive=False)
    clips = filter_video_audio(clips, allow_stills=allow_stills)
    if not clips:
        raise RuntimeError("Aucun clip utilisable pour la timeline.")

    # ✅ Tri alphabétique par nom de fichier
    clips.sort(key=lambda c: clip_source_name(c).lower())
    print("[INFO] Clips triés :")
    for c in clips:
        print("  -", clip_source_name(c))

    maybe_set_first_timeline_settings(project, fps, width, height)

    tl_name = f"{(tl_prefix or '')}{bin_name}" if tl_prefix is not None else bin_name
    # Création robuste
    try:
        tl_obj = media_pool.create_timeline_from_clips(tl_name, clips)
        if not tl_obj:
            raise RuntimeError("create_timeline_from_clips a renvoyé None")
        print(f"[SUCCESS] Timeline créée: {tl_name}")
    except Exception as e:
        print(f"[INFO] Fallback timeline native: {e}")
        bmd_mp = getattr(media_pool, "_media_pool", None)
        if not bmd_mp:
            raise RuntimeError("API native _media_pool indisponible.")
        tl_obj = bmd_mp.CreateTimelineFromClips(tl_name, clips)
        if not tl_obj:
            empty = media_pool.create_empty_timeline(tl_name) or bmd_mp.CreateEmptyTimeline(tl_name)
            if not empty:
                raise RuntimeError("Impossible de créer une timeline vide.")
            # rendre courante l'empty
            try:
                project.set_current_timeline(empty)
            except AttributeError:
                project.SetCurrentTimeline(empty)
            ok = False
            try:
                ok = bool(media_pool.append_to_timeline(clips))
            except Exception:
                ok = False
            if not ok:
                try:
                    ok = bool(bmd_mp.AppendToTimeline(clips))
                except Exception:
                    ok = False
            if not ok:
                raise RuntimeError("Append vers la timeline vide a échoué.")
            print(f"[SUCCESS] Timeline créée par append: {tl_name}")

    # ✅ Rewrap : récupérer la timeline par son nom (objet wrapper pybmd attendu par set_current_timeline)
    tl_wrapped = get_wrapped_timeline_by_name(project, tl_name)
    if not tl_wrapped:
        raise RuntimeError(f"Timeline '{tl_name}' introuvable après création.")
    project.set_current_timeline(tl_wrapped)

    # 5) Render
    presets = list_presets(project)
    if presets and preset_name not in presets:
        print("[WARN] Preset non trouvé. Presets disponibles :")
        for p in presets:
            print("  -", p)
        raise RuntimeError(f"Preset '{preset_name}' introuvable.")
    if not load_preset(project, preset_name):
        print(f"[WARN] Chargement du preset '{preset_name}' non confirmé. On applique les overrides si fournis.")

    settings: Dict[str, Any] = {}
    if outdir:
        ensure_dir(outdir)
        settings["TargetDir"] = str(Path(outdir).resolve())
    if outname:
        settings["CustomName"] = outname
    if unique:
        settings["UniqueFilename"] = True
    if fmt:
        settings["Format"] = fmt
    if codec:
        settings["VideoCodec"] = codec
    if width and height:
        settings["ResolutionWidth"] = int(width)
        settings["ResolutionHeight"] = int(height)
    if settings:
        ok = False
        for attr in ("set_render_settings", "SetRenderSettings"):
            if hasattr(project, attr):
                try:
                    ok = bool(getattr(project, attr)(settings))
                except Exception:
                    ok = False
        if not ok:
            print("[WARN] Certains overrides n'ont peut-être pas été appliqués.")

    if single:
        set_render_mode(project, "SingleClip")

    job_id = add_render_job(project)
    if not job_id:
        raise RuntimeError("Échec AddRenderJob (vérifie preset/overrides).")
    print(f"[INFO] Job ajouté: {job_id}")

    if not start_rendering(project, [job_id]):
        if not start_rendering(project, []):
            delete_render_job(project, job_id)
            raise RuntimeError("Impossible de démarrer le rendu.")

    def _parse_progress_dict(st: dict) -> int:
        """
        Tente d'extraire un pourcentage robuste depuis divers champs possibles.
        Retourne un int 0..100.
        """
        if not isinstance(st, dict):
            return 0
        cand = None
        for key in ("Progress", "JobPercentage", "CompletionPercentage", "PercentComplete"):
            v = st.get(key)
            if v is None:
                continue
            # ex: "37%", "37.2", 37, 37.0
            if isinstance(v, str):
                v = v.strip()
                if v.endswith("%"):
                    v = v[:-1]
                try:
                    v = float(v)
                except Exception:
                    continue
            if isinstance(v, (int, float)):
                cand = max(0, min(100, int(round(v))))
                break
        return cand if cand is not None else 0

    def _is_terminal_status(st: dict) -> bool:
        """
        Détecte les états terminaux suivant les variantes : 'Complete', 'Completed', 'Success', 'Finished', etc.
        """
        s1 = (st.get("Status") or st.get("State") or st.get("JobStatus") or "").lower()
        if any(k in s1 for k in ("complete", "success", "finished", "done")):
            return True
        # Certains builds n'ont pas de libellé, mais 'Error' = ""/0 en succès
        err = st.get("Error")
        if err in (None, "", 0, "0"):
            # si Progress==100 on peut considérer fini
            if _parse_progress_dict(st) == 100:
                return True
        return False

    print("[INFO] Rendu démarré. Progression :")
    last_print = -1
    st = get_job_status(project, job_id) or {}
    while True:
        st = get_job_status(project, job_id) or {}
        prog = _parse_progress_dict(st)

        # Informations complémentaires quand dispo (ne bloque pas si absentes)
        eta = st.get("TimeRemaining") or st.get("EstimatedTimeRemaining")
        fps_live = st.get("RenderFPS") or st.get("CurrentFPS")
        cur_file = st.get("CurrentClip") or st.get("ClipName")

        # Impression throttlée (évite le spam)
        if prog != last_print:
            line = f"  {prog}%"
            if eta:
                line += f"  | ETA: {eta}"
            if fps_live:
                line += f"  | {fps_live} fps"
            if cur_file:
                # tronque si trop long
                name = (cur_file[:40] + "…") if len(str(cur_file)) > 41 else cur_file
                line += f"  | {name}"
            print(line)
            last_print = prog

        if _is_terminal_status(st):
            break

        # fallback de sécurité : si l’API de statut ne bouge pas, on ne s’arrête que quand la queue dit terminé
        # (sur certains builds IsRenderingInProgress() reste peu fiable, mais on peut l’utiliser en plus)
        time.sleep(0.5)


    st = get_job_status(project, job_id) or {}
    state = (st.get("Status") or st.get("State") or "").lower()
    err = st.get("Error")
    if ("complete" in state) or (err in (None, "", 0)):
        print("[SUCCESS] Rendu terminé.")
    else:
        print(f"[WARN] Statut final du job: {st}")
    delete_render_job(project, job_id)

# ---------------- CLI ----------------
if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or "--src" not in args or "--preset" not in args:
        print(
            "Usage:\n"
            "  py.exe auto_ingest_render.py --src <FOLDER> --preset <PRESET_NAME> [options]\n"
            "Options:\n"
            "  --recursive\n"
            "  --bin-parent <PATH_UNDER_MASTER>\n"
            "  --bin-prefix <STR>\n"
            "  --tl-prefix <STR>\n"
            "  --allow-stills\n"
            "  --fps <float> --width <int> --height <int>\n"
            "  --outdir <DIR> --name <BASENAME> --unique --single\n"
            "  --format <mp4|mov|...> --codec <H.264|H.265|ProRes|...>\n"
        )
        sys.exit(1)

    def opt(flag: str) -> Optional[str]:
        return args[args.index(flag)+1] if flag in args and args.index(flag)+1 < len(args) else None

    src = opt("--src")
    preset = opt("--preset")
    recursive = "--recursive" in args
    bin_parent = opt("--bin-parent")          # ex: "INGEST" ou "INGEST/Day01"
    bin_prefix = opt("--bin-prefix") or "INGEST_"
    tl_prefix = opt("--tl-prefix")            # si None -> timeline = bin_name
    allow_stills = "--allow-stills" in args

    fps = opt("--fps"); fps_f = float(fps) if fps else None
    width = opt("--width"); w_i = int(width) if width else None
    height = opt("--height"); h_i = int(height) if height else None

    outdir = opt("--outdir")
    outname = opt("--name")
    unique = "--unique" in args
    single = "--single" in args
    fmt = opt("--format")
    codec = opt("--codec")

    if not src or not preset:
        print("Arguments requis : --src et --preset")
        sys.exit(1)

    run_pipeline(
        src_folder=src,
        preset_name=preset,
        recursive=recursive,
        bin_parent=bin_parent,
        bin_prefix=bin_prefix,
        tl_prefix=tl_prefix,
        allow_stills=allow_stills,
        fps=fps_f,
        width=w_i,
        height=h_i,
        outdir=outdir,
        outname=outname,
        unique=unique,
        single=single,
        fmt=fmt,
        codec=codec,
    )