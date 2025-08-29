import os, sys
from pathlib import Path

def _hook_bootstrap():
    modules_dir = Path(r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules")
    if modules_dir.exists():
        if str(modules_dir) not in sys.path:
            sys.path.append(str(modules_dir))

    dll = None
    env_dll = os.environ.get("RESOLVE_SCRIPT_API", "")
    if env_dll and Path(env_dll).exists():
        dll = Path(env_dll)
    else:
        cand = Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
        if cand.exists():
            dll = cand
            os.environ.setdefault("RESOLVE_SCRIPT_API", str(cand))

    if dll:
        bin_dir = dll.parent
        try:
            os.add_dll_directory(str(bin_dir))
        except Exception:
            pass
        if str(bin_dir) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

_hook_bootstrap()
