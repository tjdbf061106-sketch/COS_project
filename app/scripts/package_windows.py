"""Package an already verified portable application; does not rebuild it."""
import hashlib
import json
import shutil
import zipfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop import VERSION
release = ROOT / "release" / ("COSLab-" + VERSION)
verification = ROOT / "build" / ("release-verification-" + VERSION)
verified = json.loads((verification / "verification.json").read_text(encoding="utf-8"))
if not verified["passed"]:
    raise RuntimeError("Run scripts/verify_release.py successfully before packaging.")
eye_hash = json.loads((ROOT / "eye/checksums.json").read_text(encoding="utf-8"))["files"]["eye_A_final.joblib"]
eye_threshold = json.loads((ROOT / "eye/metadata.json").read_text(encoding="utf-8"))["threshold"]
if verified["gui"].get("eye_model_sha256") != eye_hash or verified["gui"].get("eye_threshold") != eye_threshold:
    raise RuntimeError("Release verification does not cover the current eye model and threshold.")
for name in ("Install-COSLab.bat", "Install-COSLab.ps1"):
    shutil.copy2(ROOT / "scripts" / name, release / name)
shutil.copy2(ROOT / "USER_GUIDE.md", release / "사용안내.md")
shutil.copy2(ROOT / "REPRODUCIBILITY.md", release / "REPRODUCIBILITY.md")
preview = release / "미리보기"
preview.mkdir(exist_ok=True)
for source, target in (("report.png", "결과화면.png"), ("report-input.png", "입력화면.png"), ("report.pdf", "예제보고서.pdf")):
    shutil.copy2(verification / source, preview / target)
for source, target in (("report-evidence.png", "원료참고정보.png"),):
    if (verification / source).exists():
        shutil.copy2(verification / source, preview / target)
archive = ROOT / "release" / ("COSLab-" + VERSION + "-Windows.zip")
files = [file for file in release.rglob("*") if file.is_file()]
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=4, allowZip64=True) as output:
    for file in files:
        output.write(file, file.relative_to(release.parent))
print(f"Archive created: {archive.name}; {archive.stat().st_size / 1024 ** 2:.1f} MiB; {len(files)} files", flush=True)
with zipfile.ZipFile(archive) as output:
    if output.testzip() is not None:
        raise RuntimeError("Archive integrity check failed.")
with archive.open("rb") as source:
    checksum = hashlib.file_digest(source, "sha256").hexdigest()
archive.with_suffix(".zip.sha256").write_text(checksum + "  " + archive.name + "\n", encoding="ascii")
print("Archive integrity: PASS", flush=True)
