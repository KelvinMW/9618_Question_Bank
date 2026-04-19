import json
import os
import threading
import webbrowser
from pathlib import Path

from app import app, DEFAULT_APP_SETTINGS


BASE_DIR = Path(__file__).resolve().parent
LOCAL_DIR = BASE_DIR / "local"
APP_SETTINGS_PATH = LOCAL_DIR / "app_settings.json"
SAVED_PAPERS_PATH = LOCAL_DIR / "saved_papers.json"
USER_TITLES_PATH = LOCAL_DIR / "user_titles.json"
USER_OVERRIDES_PATH = LOCAL_DIR / "question_overrides.json"
APP_URL = "http://127.0.0.1:5001"


def ensure_local_runtime_files():
    LOCAL_DIR.mkdir(exist_ok=True)

    defaults = {
        APP_SETTINGS_PATH: DEFAULT_APP_SETTINGS,
        SAVED_PAPERS_PATH: {"papers": []},
        USER_TITLES_PATH: {},
        USER_OVERRIDES_PATH: {},
    }

    for path, payload in defaults.items():
        if path.exists():
            continue
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def open_browser():
    if os.environ.get("QBANK_OPEN_BROWSER", "1") == "0":
        return
    webbrowser.open(APP_URL)


if __name__ == "__main__":
    ensure_local_runtime_files()
    threading.Timer(1.0, open_browser).start()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=5001)
