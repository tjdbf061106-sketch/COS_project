"""Exercise the portable app with Python/Conda removed from PATH."""
import copy
import hashlib
import json
import math
import os
import subprocess
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop import VERSION
APP = ROOT / "release" / ("COSLab-" + VERSION)
OUTPUT = ROOT / "build" / ("release-verification-" + VERSION)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = str(windows / "System32") + os.pathsep + str(windows)
    for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                "QTWEBENGINEPROCESS_PATH", "QML2_IMPORT_PATH", "QTWEBENGINE_CHROMIUM_FLAGS",
                "QT_OPENGL", "QT_QUICK_BACKEND"):
        env.pop(key, None)
    payload = {"name": "Execution check", "scope": "complete", "components": [
        {"component_id": "ethanol", "name": "Ethanol", "canonical_smiles": "CCO", "amount_pct": 20},
        {"component_id": "water", "name": "Water", "canonical_smiles": "O", "amount_pct": 80}]}
    checks = []
    expected_eye_hash = "5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5"
    expected_eye_threshold = 0.48345327423625106
    bundled_eye = APP / "engines/eye/_internal/eye"
    assert not (bundled_eye / "eye_A_LR_wmean.joblib").exists(), "Obsolete eye model remains in release"
    eye_checks = json.loads((ROOT / "eye/checksums.json").read_text(encoding="utf-8"))["files"]
    assert eye_checks["eye_A_final.joblib"] == expected_eye_hash
    for name, expected in eye_checks.items():
        assert hashlib.sha256((bundled_eye / name).read_bytes()).hexdigest() == expected, name
    release_info = json.loads((APP / "release-info.json").read_text(encoding="utf-8"))
    assert release_info["source_model_commits"]["eye"] == "c20f6b737b992676de66da1b86800c058275ce56"
    assert release_info["model_sha256"]["eye"] == expected_eye_hash
    assert release_info["eye_threshold"] == expected_eye_threshold
    with tempfile.TemporaryDirectory(prefix="cos-release-check-") as cwd:
        env["LOCALAPPDATA"] = cwd
        env["HTTP_PROXY"] = env["HTTPS_PROXY"] = "http://127.0.0.1:9"
        env["NO_PROXY"] = ""
        def worker(endpoint, data, action="predict"):
            exe = APP / "engines" / endpoint / ("COS-" + endpoint + "-engine.exe")
            request = {"action": action, "endpoint": endpoint, "payload": data} if action == "predict" else {"action": action, "smiles": data}
            result = subprocess.run([str(exe)], input=json.dumps(request),
                                    cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=100)
            response = json.loads(result.stdout)
            assert (result.returncode == 0) == response["ok"]
            return response

        for endpoint, expected in (("skin", .178), ("eye", .6232614237228717)):
            response = worker(endpoint, payload)
            assert response["ok"] and math.isclose(response["result"]["score"], expected, rel_tol=0, abs_tol=1e-12), response
            if endpoint == "eye":
                assert response["result"]["model_sha256"] == expected_eye_hash, response
                assert response["result"]["threshold"] == expected_eye_threshold, response
                assert response["result"]["predicted_class"] == int(response["result"]["score"] >= expected_eye_threshold), response
            checks.append({"endpoint": endpoint, "case": "valid", "score": response["result"]["score"],
                           "threshold": response["result"]["threshold"], "model_sha256": response["result"]["model_sha256"], "pass": True})
            for case in ("invalid_smiles", "missing_amount", "all_zero", "excess_total"):
                data = copy.deepcopy(payload)
                if case == "invalid_smiles":
                    data["components"][0]["canonical_smiles"] = "not-a-smiles"
                elif case == "missing_amount":
                    data["components"][0]["amount_pct"] = None
                elif case == "excess_total":
                    data["components"][0]["amount_pct"] = 21
                else:
                    for row in data["components"]:
                        row["amount_pct"] = 0
                response = worker(endpoint, data)
                assert not response["ok"], (endpoint, case)
                checks.append({"endpoint": endpoint, "case": case, "pass": True})
            print(endpoint + " executable: valid input and 4 rejected inputs PASS", flush=True)

        source_hash = json.loads((ROOT / "desktop/similarity/SOURCE.json").read_text(encoding="utf-8"))["sha256"]
        for name, smiles, expected in (("glycerin", "OCC(O)CO", [2/13, 0]),
                                      ("limonene", "CC1=CCC(CC1)C(=C)C", [1, .3]),
                                      ("sls", "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]", [9/37, 1])):
            response = worker("eye", smiles, "evidence")
            assert response["ok"], response
            detail = response["result"]
            assert [item["model_id"] for item in detail["scores"]] == ["fragrance_similarity", "surfactant_likeness"]
            assert all(math.isclose(item["score"], score, abs_tol=1e-12) for item, score in zip(detail["scores"], expected))
            assert detail["source"]["sha256"] == source_hash
            assert all("threshold" not in item and "property_score" not in item for item in detail["scores"])
            if name == "sls":
                assert detail["scores"][1]["longest_aliphatic_chain"] == 12
                assert detail["patterns"][0]["pattern_id"] == "anionic_sulfate_ester" and detail["patterns"][0]["preview"]
            (OUTPUT / (name + "-evidence.json")).write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
            checks.append({"endpoint": "evidence", "case": name, "scores": expected, "pass": True})
        print("Portable local similarity: 3 compounds, 2 scores, pattern image and source hash PASS", flush=True)

        screenshot = OUTPUT / "report.png"
        gui = subprocess.run([str(APP / "COSLab.exe"), "--smoke-test", "--screenshot", str(screenshot)],
                             cwd=cwd, env=env, capture_output=True, timeout=220)
        (OUTPUT / "gui.log").write_bytes(gui.stdout + gui.stderr)
        assert gui.returncode == 0, "GUI failed; see " + str(OUTPUT / "gui.log")
        result = json.loads(screenshot.with_suffix(".json").read_text(encoding="utf-8"))
        assert result["ok"] and result["pdf_created"] and result["stale_result_cleared"], result
        assert result["caution_unmatched"] and result["caution_coverage"] and result["identity_verified"], result
        assert result["auxiliary_cards"] == 2 and result["target_switch"], result
        assert result["auxiliary_ids"] == ["fragrance_similarity", "surfactant_likeness"], result
        assert result["report_body_px"] >= 15 and result["irritation_score_px"] == 43, result
        assert result["eye_model_sha256"] == expected_eye_hash and result["eye_threshold"] == expected_eye_threshold, result
        assert result["demo_components"] == 6 and math.isclose(result["skin"], .202, abs_tol=1e-12), result
        assert math.isclose(result["eye"], .6192026683768463, rel_tol=0, abs_tol=1e-12), result
        print("Portable GUI: structure, both models, report, stale-result invalidation, PDF PASS", flush=True)
    (OUTPUT / "verification.json").write_text(json.dumps({
        "passed": True, "app_version": VERSION, "environment": "Windows; no Python/Conda on PATH; temporary working directory",
        "engine_checks": checks, "gui": result}, indent=2), encoding="utf-8")
    print("ALL RELEASE CHECKS PASSED", flush=True)


if __name__ == "__main__":
    main()
