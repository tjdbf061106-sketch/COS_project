from pathlib import Path
import os
import sys


def resources():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def installation():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else resources()


def user_data():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    target = base / "COSLab"
    target.mkdir(parents=True, exist_ok=True)
    return target
