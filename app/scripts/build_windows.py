"""Build three independent runtimes, then assemble a portable Windows folder."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop import VERSION


def build(part):
    environment = {"skin": ".venv-skin", "eye": ".venv-eye", "desktop": ".venv-desktop"}[part]
    python = ROOT / environment / "Scripts" / "python.exe"
    stage = ROOT / "build" / ("dist-" + part)
    work = ROOT / "build" / ("work-" + part)
    spec = ROOT / "build" / ("spec-" + part)
    for path in (stage, work, spec):
        path.mkdir(parents=True, exist_ok=True)
    args = [str(python), "-m", "PyInstaller", "--noconfirm", "--onedir",
            "--distpath", str(stage), "--workpath", str(work), "--specpath", str(spec),
            "--paths", str(ROOT), "--log-level", "WARN"]
    for module in ("PyQt5", "PyQt6", "PySide2", "IPython", "notebook", "tensorflow", "torch", "matplotlib", "desktop.vendor"):
        args += ["--exclude-module", module]
    if part == "desktop":
        args += ["--name", "COSLab", "--windowed", "--add-data", str(ROOT / "desktop" / "ui") + ":desktop/ui",
                 "--exclude-module", "numpy", "--exclude-module", "pandas", "--exclude-module", "rdkit",
                 "--exclude-module", "sklearn", "--exclude-module", "scipy", "--hidden-import", "caution.match"]
        for name in ("conditions.json", "medications.json", "ingredient_tags.json", "rules.json", "citations.json", "README.md"):
            args += ["--add-data", str(ROOT / "caution" / name) + ":caution"]
        args += ["--add-data", str(ROOT / "desktop" / "identity_catalog.json") + ":desktop"]
        args += [str(ROOT / "desktop_app.py")]
    else:
        args += ["--name", "COS-" + part + "-engine", "--console", "--exclude-module", "PySide6",
                 "--collect-all", "rdkit", "--add-data", str(ROOT / part) + ":" + part,
                 "--hidden-import", "sklearn.tree._tree", "--hidden-import", "sklearn.ensemble._forest",
                 "--hidden-import", "sklearn.utils._weight_vector",
                 "--collect-submodules", "sklearn"]
        if part == "eye":
            args += ["--hidden-import", "pandas"]
        similarity = ROOT / "desktop" / "similarity"
        for name in ("similarity.py", "fragrance_reference.json", "surfactant_patterns.json", "README.md", "verify.py", "SOURCE.json"):
            args += ["--add-data", str(similarity / name) + ":desktop/similarity"]
        args += [str(ROOT / "engine_entry.py")]
    print("Building " + part, flush=True)
    subprocess.run(args, cwd=ROOT, check=True)
    print("Built " + part, flush=True)


def assemble():
    target = ROOT / "release" / ("COSLab-" + VERSION)
    source = ROOT / "build" / "dist-desktop" / "COSLab"
    if not source.exists():
        raise RuntimeError("Desktop build missing")
    shutil.copytree(source, target, dirs_exist_ok=True)
    for part in ("skin", "eye"):
        source = ROOT / "build" / ("dist-" + part) / ("COS-" + part + "-engine")
        if not source.exists():
            raise RuntimeError(part + " build missing")
        shutil.copytree(source, target / "engines" / part, dirs_exist_ok=True)
    for name in ("Install-COSLab.ps1", "Install-COSLab.bat"):
        shutil.copy2(ROOT / "scripts" / name, target / name)
    shutil.copy2(ROOT / "README.md", target / "사용안내.md")
    shutil.copy2(ROOT / "REPRODUCIBILITY.md", target / "REPRODUCIBILITY.md")
    shutil.copy2(ROOT / "examples" / "ingredients.csv", target / "입력예제.csv")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", target / "THIRD_PARTY_NOTICES.md")
    (target / "release-info.json").write_text(json.dumps({
        "app_version": VERSION,
        "source_model_commits": {
            "skin": "4ab6bd83a271f52f0384d7c415c804f600ec8956",
            "eye": "c20f6b737b992676de66da1b86800c058275ce56",
        },
        "model_files": {"skin": "skin_rf_checkpoint.joblib", "eye": "eye_A_final.joblib"},
        "model_sha256": {
            "skin": json.loads((ROOT / "skin/metadata.json").read_text(encoding="utf-8"))["checkpoint_sha256"],
            "eye": json.loads((ROOT / "eye/checksums.json").read_text(encoding="utf-8"))["files"]["eye_A_final.joblib"],
        },
        "eye_threshold": json.loads((ROOT / "eye/metadata.json").read_text(encoding="utf-8"))["threshold"],
        "auxiliary_source": json.loads((ROOT / "desktop/similarity/SOURCE.json").read_text(encoding="utf-8")),
        "auxiliary_scores": ["fragrance_similarity", "surfactant_likeness"],
        "separate_inference_runtimes": True, "python_installation_required": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Portable application: " + str(target), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("part", choices=["skin", "eye", "desktop", "assemble"])
    part = parser.parse_args().part
    assemble() if part == "assemble" else build(part)
