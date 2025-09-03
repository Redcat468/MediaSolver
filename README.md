![MediaSolver Banner and logo](https://i.imgur.com/JtXmbLL.png)

MediaSolver is a suite of Python tools designed to automate media ingest and rendering in DaVinci Resolve. It provides a lightweight web interface, a command-line version, and a system tray application, all centered on a safety script that ensures the MediaSolver project is opened in Resolve.

## 💡 Base idea
This program use pybmd (https://github.com/WheheoHu/pybmd) to control DaVinciResolve using python.

It scans a folder for files, creates a dedicated bin, generates a sorted timeline, then adds a render job with the chosen preset.
Exposes a Flask API to start processing, monitor progress, and query the Resolve engine status (/start, /progress, /presets, etc.)

## 💾 How To Install
Download and launch the latest release setup installer : https://github.com/Redcat468/MediaSolver/releases

Required :
 - Install Python on host (https://www.python.org/downloads/)
 - Install DaVinciResolve Studio v.19.3.1 or higher (https://www.blackmagicdesign.com/fr/products/davinciresolve)
   
## 🚀 Usage
- Manually Start MediaSolver
- Manually Start DaVinci Resolve
- An icon appears in the notification area
- The web interface opens automatically at http://127.0.0.1:17209/.
  
You can also acces this instance of MediaSolver on LAN via IP or Hostname to launch remote renderings on other hosts.

![MediaSolver WebUI screenshot](https://i.imgur.com/6T0nUUE.png)




## 📁 Main Components

### 1. Web Interface
Robust startup of the Resolve API (adds the necessary DLLs and modules)
Minimalist HTML/CSS interface to select folders, choose the preset, and monitor progress.

### 2. Resolve Project Safeguard (ensure_mediasolver_safe.py)
Ensures Resolve is running, the API responds, and the MediaSolver project is loaded, so the job is ready to render.
Handles unnamed (unsaved) projects, automatically creating or loading MediaSolver if needed, and returns a detailed status (OK, APP_OFF, LOAD_FAILED…).
Ingest/render pipeline launched in a thread:
Can be executed whith the "Check Resolve Engine" button directly on webUI

## 3. System Tray Application (MediaSolverTray.py)
Launches the Flask server in the background and displays an icon in the notification area.
Icon menu: Open Web UI and Quit.


## 🔩 Command-Line Tool (MediaSolver-cli.py)
Follows the same ingest logic (sorting, timeline creation, render launch) via CLI parameters: source folder, preset, render options…

CLI
```
python MediaSolver-cli.py --src <FOLDER> --preset <PRESET_NAME> --outdir <FOLDER>
```

📜 License
This project is distributed under the Creative Commons Attribution - NonCommercial - ShareAlike 4.0 International (CC BY-NC-SA 4.0) license.
See the LICENSE file for the full text.

Enjoy using MediaSolver!
