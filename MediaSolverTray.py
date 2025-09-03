# MediaSolverTray.py — Lanceur zone de notif pour MediaSolver (Flask + systray)
# Dépendances : flask (déjà), pystray, Pillow
# PyInstaller : ajouter --hidden-import pystray._win32

import os, sys, socket, threading, webbrowser, time, ctypes, atexit
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item


from pathlib import Path
import sys
from PIL import Image

def resource_path(rel_path: str) -> Path:
    """Retourne le chemin absolu vers une ressource, compatible PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / rel_path

# --- Import de ton serveur Flask et de l'ensure ---
import app as mediasolver_app  # <-- ton app.py
from ensure_mediasolver_safe import ensure_mediasolver_ready

HOST = "0.0.0.0"
PORT = 17209
URL  = f"http://127.0.0.1:{PORT}/"




# ---------- Singleton (mutex Windows + port occupé) ----------
def _already_running_via_mutex() -> bool:
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, True, "Global\\MediaSolverTray_v1")
    last_err = kernel32.GetLastError()
    # 183 = ERROR_ALREADY_EXISTS
    if last_err == 183:
        # Un autre instance possède le mutex
        return True
    # garder le mutex vivant jusqu’à la fin du process
    atexit.register(lambda: kernel32.ReleaseMutex(mutex))
    return False

def _port_in_use(host, port) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex((host, port)) == 0

def _open_existing_and_exit():
    try:
        webbrowser.open(URL)
    finally:
        sys.exit(0)

# ---------- Flask server en thread (werkzeug) ----------
class ServerThread(threading.Thread):
    def __init__(self, flask_app, host='0.0.0.0', port=17209):
        super().__init__(daemon=True)
        from werkzeug.serving import make_server
        self._srv = make_server(host, port, flask_app)
        self._ctx = flask_app.app_context()
        self._ctx.push()

    def run(self):
        self._srv.serve_forever()

    def shutdown(self):
        try:
            self._srv.shutdown()
        except Exception:
            pass

server_thread: ServerThread | None = None

def start_server():
    global server_thread
    if server_thread is None:
        server_thread = ServerThread(mediasolver_app.app, HOST, PORT)
        server_thread.start()

def stop_server():
    global server_thread
    if server_thread:
        server_thread.shutdown()
        server_thread = None

# ---------- Icône & menu systray ----------
def _make_icon_image():
    # Chemin normalisé vers TON fichier (dossier "image", nom en minuscules)
    candidates = [
        "static/images/MediaSolver.ico",
    ]
    for rel in candidates:
        p = resource_path(rel)
        if p.exists():
            try:
                return Image.open(p)
            except Exception:
                pass
    # Fallback d'urgence si aucun fichier n’est trouvé
    img = Image.new("RGBA", (32, 32), (79, 140, 255, 255))
    return img


tray_icon: pystray.Icon | None = None

def on_open_ui(icon, item):
    webbrowser.open(URL)

def on_quit(icon, item):
    try:
        stop_server()
    except Exception:
        pass
    icon.visible = False
    icon.stop()

def build_menu():
    return pystray.Menu(
        item("Open Web UI", on_open_ui),
        item("Quit", on_quit)
    )

def run_tray():
    global tray_icon
    image = _make_icon_image()
    tray_icon = pystray.Icon("MediaSolver", image, "MediaSolver", menu=build_menu())
    tray_icon.run()

# ---------- Main ----------
def main():
    # Empêcher plusieurs instances
    if _already_running_via_mutex() or _port_in_use(HOST, PORT):
        _open_existing_and_exit()

    # Démarre Flask en arrière-plan
    start_server()

    # Ouvre l’UI la première fois (optionnel)
    threading.Timer(0.8, lambda: webbrowser.open(URL)).start()

    # Lance l'icône tray (bloquant jusqu’à Quit)
    run_tray()

if __name__ == "__main__":
    main()
