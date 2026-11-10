"""Install three isolated, hash-locked Windows runtimes without global packages."""
import argparse
import platform
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("desktop", "eye", "skin"))
    parser.add_argument("--reinstall", action="store_true", help="Reinstall pinned wheels after an interrupted installation.")
    args = parser.parse_args()
    if (Path(sys.base_prefix) / "conda-meta").is_dir():
        raise SystemExit("Use official CPython for Qt compatibility. Run Setup-Windows.ps1 to install the pinned local runtime.")
    if sys.platform != "win32" or sys.version_info[:2] != (3, 14) or platform.machine().upper() not in ("AMD64", "X86_64") or sysconfig.get_config_var("Py_GIL_DISABLED"):
        raise SystemExit("Use standard (non-free-threaded) CPython 3.14, Windows x64. Tested: Python 3.14.6.")
    for part in ([args.only] if args.only else ("desktop", "eye", "skin")):
        target = ROOT / (".venv-" + part)
        if target.exists():
            config = target / "pyvenv.cfg"
            if not config.is_file() or "include-system-site-packages = false" not in config.read_text(encoding="utf-8"):
                raise SystemExit(f"{target.name} must be an isolated venv. Use a new checkout for a clean installation.")
            if args.reinstall:
                venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target)
        else:
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target)
        python = str(target / "Scripts/python.exe")
        version = subprocess.check_output([python, "-I", "-c", "import sys; print('.'.join(map(str,sys.version_info[:2])))"], text=True).strip()
        if version != "3.14":
            raise SystemExit(f"{target.name} uses Python {version}; use a new checkout with Python 3.14.")
        base = subprocess.check_output([python, "-I", "-c", "import sys; print(sys.base_prefix)"], text=True).strip()
        if Path(base).resolve() != Path(sys.base_prefix).resolve():
            raise SystemExit(f"{target.name} uses a different base Python. Rerun Setup-Windows.ps1 -Reinstall.")
        print(f"Installing {part} runtime", flush=True)
        subprocess.run([python, "-I", "-m", "pip", "--isolated", "install", "--index-url", "https://pypi.org/simple", "pip==26.1.2", "--disable-pip-version-check"], check=True)
        subprocess.run([python, "-I", "-m", "pip", "--isolated", "install", "--index-url", "https://pypi.org/simple", "--require-hashes", "--only-binary=:all:", "--disable-pip-version-check", *(["--force-reinstall"] if args.reinstall else []), "-r", str(ROOT / "requirements" / (part + ".lock.txt"))], check=True)
        subprocess.run([python, "-I", "-m", "pip", "--isolated", "check"], check=True)
    print("Setup complete. Run Start-COSLab.bat.", flush=True)


if __name__ == "__main__":
    main()
