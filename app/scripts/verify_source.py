"""Verify the self-contained source package, isolated runtimes and offline GUI."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/source-verification"


def verify_manifest():
    manifest = json.loads((ROOT / "SHA256SUMS.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise RuntimeError(f"Missing or invalid manifest path: {name}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Source checksum mismatch: {name}")
    print(f"Source checksums: {len(manifest['files'])} PASS", flush=True)
    return len(manifest["files"])


def python(part):
    path = ROOT / (".venv-" + part) / "Scripts/python.exe"
    if not path.is_file():
        raise RuntimeError("Run scripts/setup_windows.py first: missing " + part + " runtime")
    return str(path)


def check_environment(part, env):
    lock = ROOT / "requirements" / (part + ".lock.txt")
    expected = {}
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, version = line.split()[0].split("==")
            expected[name] = version
    config = ROOT / (".venv-" + part) / "pyvenv.cfg"
    if "include-system-site-packages = false" not in config.read_text(encoding="utf-8"):
        raise RuntimeError(part + " runtime shares global packages")
    code = (
        "import importlib.metadata as m,json,sys; from packaging.version import Version; "
        "expected=json.loads(sys.argv[1]); "
        "actual={name:m.version(name) for name in expected}; "
        "assert all(Version(actual[n])==Version(v) for n,v in expected.items()),actual; "
        "assert sys.prefix!=sys.base_prefix and sys.version_info[:2]==(3,14); "
        "print(json.dumps({'python':sys.version.split()[0],'packages':actual,'isolated':True}))"
    )
    result = subprocess.run([python(part), "-I", "-c", code, json.dumps(expected)],
                            cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    print(part + " isolated runtime and pinned versions: PASS", flush=True)
    return json.loads(result.stdout)


def run_check(label, part, args, env, cwd=ROOT, timeout=240):
    result = subprocess.run([python(part), "-X", "utf8", *args], cwd=cwd, env=env,
                            capture_output=True, timeout=timeout)
    log = OUTPUT / (label + ".log")
    log.write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"{label} failed (exit {result.returncode}); see {log}")
    print(label + ": PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checksums-only", action="store_true")
    args = parser.parse_args()
    count = verify_manifest()
    if args.checksums_only:
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                "QTWEBENGINEPROCESS_PATH", "QML2_IMPORT_PATH", "QTWEBENGINE_CHROMIUM_FLAGS",
                "QT_OPENGL", "QT_QUICK_BACKEND", "ALL_PROXY", "all_proxy", "http_proxy", "https_proxy", "no_proxy"):
        env.pop(key, None)
    env["HTTP_PROXY"] = env["HTTPS_PROXY"] = "http://127.0.0.1:9"
    env["NO_PROXY"] = ""
    runtimes = {part: check_environment(part, env) for part in ("desktop", "skin", "eye")}
    with tempfile.TemporaryDirectory(prefix="cos-source-check-") as temporary:
        env["LOCALAPPDATA"] = temporary
        for label, part, command in (
            ("skin-model", "skin", [str(ROOT / "skin/verify.py")]),
            ("eye-model", "eye", [str(ROOT / "eye/verify.py")]),
            ("unit-tests", "eye", ["-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("caution", "eye", [str(ROOT / "caution/verify.py")]),
            ("similarity", "eye", [str(ROOT / "desktop/similarity/verify.py")]),
        ):
            run_check(label, part, command, env)
        screenshot = OUTPUT / "report.png"
        run_check("gui", "desktop", [str(ROOT / "desktop_app.py"), "--smoke-test", "--screenshot", str(screenshot)],
                  env, cwd=temporary)
        gui = json.loads(screenshot.with_suffix(".json").read_text(encoding="utf-8"))
        for name in ("ok", "pdf_created", "structure_preview", "stale_result_cleared", "caution_live_update",
                     "caution_unmatched", "identity_verified", "caution_coverage", "target_switch", "demo_fragrance", "demo_surfactant_pattern"):
            if gui.get(name) is not True:
                raise RuntimeError("GUI check failed: " + name)
        assert gui["demo_components"] == 6 and gui["auxiliary_cards"] == 2, gui
        assert gui["auxiliary_ids"] == ["fragrance_similarity", "surfactant_likeness"], gui
        assert math.isclose(gui["skin"], .202, rel_tol=0, abs_tol=1e-12), gui
        assert math.isclose(gui["eye"], .6192026683768463, rel_tol=0, abs_tol=1e-12), gui
        assert gui["eye_threshold"] == .48345327423625106, gui
        assert gui["eye_model_sha256"] == "5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5", gui
        assert gui["skin_model_sha256"] == "1ff0bd062fba0fab11c0407731ddb6996c7646bf033e07a4c501a391a2459e34", gui
        assert screenshot.with_suffix(".pdf").read_bytes().startswith(b"%PDF-"), "Invalid PDF"
    (OUTPUT / "verification.json").write_text(json.dumps({
        "passed": True, "checksummed_files": count, "environment": "Windows x64; isolated CPython runtimes; PyPI wheels",
        "external_lookup_disabled": True, "runtimes": runtimes, "gui": gui,
    }, indent=2) + "\n", encoding="utf-8")
    print("ALL SOURCE CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
