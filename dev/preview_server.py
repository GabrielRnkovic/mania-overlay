"""Run only the HTTP side (no GTK) to preview the page in a normal browser: open /?demo&edit"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from mania_overlay.config import Settings
from mania_overlay.server import Controller, start_server

settings = Settings(Path(os.environ.get("PREVIEW_SETTINGS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preview-settings.json"))))
start_server(24055, settings, Controller())
print("preview on http://127.0.0.1:24055/?demo&edit", flush=True)
while True:
    time.sleep(3600)
