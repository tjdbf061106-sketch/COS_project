"""COS Lab: a local HTML interface inside an independent Windows window."""
import argparse
import json
import os
import sys
from pathlib import Path

# Consistent rendering on PCs without a usable hardware OpenGL context.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --disable-gpu-compositing")
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, Signal, Slot, QRunnable, QThreadPool, QUrl, QTimer, Qt, QMarginsF
from PySide6.QtGui import QIcon, QPixmap, QColor, QPainter, QFont, QDesktopServices, QPageLayout, QPageSize
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox, QSplashScreen
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

from desktop import VERSION
from desktop.paths import resources, user_data
from desktop.validation import validate
from desktop.service import analyze, lookup, structure, evidence, parse_csv, export_csv, caution_options, caution_for_report, validate_ingredients
from desktop.annotations import fetch_annotations


class Signals(QObject):
    done = Signal(str)


class Work(QRunnable):
    def __init__(self, request_id, function):
        super().__init__()
        self.request_id, self.function = request_id, function
        self.signals = Signals()

    def run(self):
        try:
            result = {"id": self.request_id, "ok": True, "result": self.function()}
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            result = {"id": self.request_id, "ok": False, "error": str(exc)}
            encoded = json.dumps(result, ensure_ascii=False)
        self.signals.done.emit(encoded)


class Bridge(QObject):
    completed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.jobs = {}

    @Slot(str)
    def request(self, raw):
        request_id = ""
        try:
            if len(raw) > 4_000_000:
                raise ValueError("요청이 너무 큽니다.")
            message = json.loads(raw)
            request_id = str(message["id"])
            action, data = message["action"], message.get("data", {})
            if action in ("save_draft", "open_draft", "import_csv", "export_json", "export_csv", "print_report"):
                result = self.dialog_action(action, data)
                self.completed.emit(json.dumps({"id": request_id, "ok": True, "result": result}, ensure_ascii=False))
                return
            functions = {
                "info": lambda: {"version": VERSION, "skin": "Random Forest", "eye": "Logistic Regression"},
                "validate": lambda: validate_ingredients(data),
                "lookup": lambda: lookup(data["query"], data.get("mode", "name")),
                "structure": lambda: structure(data["smiles"]),
                "evidence": lambda: evidence(data["smiles"]),
                "annotations": lambda: fetch_annotations(data["smiles"]),
                "analyze": lambda: analyze(data),
                "caution_options": caution_options,
                "caution": lambda: caution_for_report(data),
            }
            if action not in functions:
                raise ValueError("지원하지 않는 작업입니다.")
            job = Work(request_id, functions[action])
            self.jobs[request_id] = job
            job.signals.done.connect(self.finish)
            self.pool.start(job)
        except Exception as exc:
            self.completed.emit(json.dumps({"id": request_id, "ok": False, "error": str(exc)}, ensure_ascii=False))

    @Slot(str)
    def finish(self, result):
        self.jobs.pop(json.loads(result)["id"], None)
        self.completed.emit(result)

    def dialog_action(self, action, data):
        initial = str(Path.home() / "Documents")
        if action in ("open_draft", "import_csv"):
            is_csv = action == "import_csv"
            path, _ = QFileDialog.getOpenFileName(self.window, "CSV 불러오기" if is_csv else "배합 불러오기",
                                                  initial, "CSV (*.csv)" if is_csv else "배합 / 보고서 (*.json)")
            if not path:
                return None
            file = Path(path)
            if file.stat().st_size > 4_000_000:
                raise ValueError("4MB 이하의 파일을 선택해 주세요.")
            if is_csv:
                try:
                    text = file.read_text(encoding="utf-8-sig")
                except UnicodeDecodeError:
                    text = file.read_text(encoding="cp949")
                return {"components": parse_csv(text), "filename": file.name}
            def reject_constant(value):
                raise ValueError("배합 파일에 유효하지 않은 숫자가 있습니다: " + value)
            payload = json.loads(file.read_text(encoding="utf-8-sig"), parse_constant=reject_constant)
            if not isinstance(payload, dict):
                raise ValueError("원료 목록이 있는 배합 JSON 파일을 선택해 주세요.")
            saved_caution = payload.get("caution") if isinstance(payload.get("caution"), dict) else None
            payload = payload.get("input", payload)
            if isinstance(payload, dict) and saved_caution and "caution" not in payload:
                payload = dict(payload, caution={"conditions": saved_caution.get("conditions") or [],
                                                 "medications": saved_caution.get("medications") or []})
            if not isinstance(payload, dict) or not isinstance(payload.get("components"), list):
                raise ValueError("원료 목록이 있는 배합 JSON 파일을 선택해 주세요.")
            if not 1 <= len(payload["components"]) <= 100 or not all(isinstance(r, dict) for r in payload["components"]):
                raise ValueError("올바른 원료 행이 1~100개 있는 파일을 선택해 주세요.")
            return payload
        if action == "print_report":
            if not data.get("results"):
                raise ValueError("분석 후 보고서를 저장할 수 있습니다.")
            path, _ = QFileDialog.getSaveFileName(self.window, "보고서 PDF 저장",
                                                  str(Path(initial) / "COS-분석보고서.pdf"), "PDF (*.pdf)")
            if not path:
                return None
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            self.window.print_pdf(path)
            return {"path": path, "printing": True}
        is_csv = action == "export_csv"
        default = "COS-배합.json" if action == "save_draft" else ("COS-분석결과.csv" if is_csv else "COS-분석보고서.json")
        path, _ = QFileDialog.getSaveFileName(self.window, "저장", str(Path(initial) / default),
                                              "CSV (*.csv)" if is_csv else "JSON (*.json)")
        if not path:
            return None
        suffix = ".csv" if is_csv else ".json"
        if not path.lower().endswith(suffix):
            path += suffix
        if is_csv:
            text = export_csv(data)
        else:
            text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        Path(path).write_text(text, encoding="utf-8-sig" if is_csv else "utf-8")
        return {"path": path}


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, is_main_frame):
        if (kind == QWebEnginePage.NavigationType.NavigationTypeLinkClicked
                and url.scheme() == "https"):
            QDesktopServices.openUrl(url)
            return False
        return url.scheme() in ("file", "qrc", "data", "about")

    def javaScriptConsoleMessage(self, level, message, line, source):
        if os.environ.get("COS_UI_TEST"):
            print(f"JS {level}: {message} ({line})", flush=True)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("COS Lab · 피부·안자극 배합 분석")
        self.resize(1400, 940)
        self.setMinimumSize(1050, 720)
        self.setWindowIcon(QIcon(str(resources() / "desktop" / "ui" / "icon.svg")))
        self.view = QWebEngineView(self)
        self.view.setPage(LocalPage(self.view))
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.setCentralWidget(self.view)
        self.channel = QWebChannel(self.view.page())
        self.bridge = Bridge(self)
        self.channel.registerObject("cos", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.view.page().pdfPrintingFinished.connect(self.pdf_finished)
        self.view.load(QUrl.fromLocalFile(str(resources() / "desktop" / "ui" / "index.html")))

    def pdf_finished(self, path, success):
        self.view.page().runJavaScript("window.pdfFinished && window.pdfFinished(" +
                                       json.dumps(path if success else "", ensure_ascii=True) + ")")

    def print_pdf(self, path):
        # Qt's default printToPdf layout has zero margins and overrides CSS @page.
        layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                             QMarginsF(20, 20, 20, 20), QPageLayout.Unit.Millimeter)
        self.view.page().printToPdf(str(path), layout)

    def closeEvent(self, event):
        if self.bridge.jobs:
            answer = QMessageBox.question(self, "작업 진행 중", "검색 또는 분석이 진행 중입니다. 종료할까요?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ["COS_UI_TEST"] = "1"
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("COS Lab")
    app.setOrganizationName("COS")
    splash_image = QPixmap(440, 230)
    splash_image.fill(QColor("#123f3b"))
    painter = QPainter(splash_image)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Malgun Gothic", 28, QFont.Weight.Bold))
    painter.drawText(36, 94, "COS Lab")
    painter.setFont(QFont("Malgun Gothic", 11))
    painter.setPen(QColor("#b7d4cb"))
    painter.drawText(38, 133, "피부·안자극 배합 분석")
    painter.drawText(38, 187, "분석 공간을 준비하고 있습니다…")
    painter.end()
    splash = QSplashScreen(splash_image)
    if not args.smoke_test:
        splash.show()
    window = Window()
    window.view.loadFinished.connect(lambda ok: splash.finish(window))
    window.show()
    if args.smoke_test:
        # A real Qt WebEngine render, bridge call, and JS-driven end-to-end workflow.
        QTimer.singleShot(180000, lambda: app.exit(2))
        timer = QTimer(window)
        timer.setInterval(500)
        elapsed = {"ticks": 0}
        def tick():
            elapsed["ticks"] += 1
            def state(value):
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except ValueError:
                        pass
                if elapsed["ticks"] % 20 == 0:
                    print("UI_TEST_PROGRESS=" + str(value), flush=True)
                    if args.screenshot:
                        window.grab().save(args.screenshot)
                if isinstance(value, dict) and value.get("done"):
                    timer.stop()
                    window.view.page().runJavaScript(
                        "JSON.stringify({visibility:document.visibilityState,overlay:getComputedStyle(document.getElementById('busy-overlay')).display,report:getComputedStyle(document.getElementById('report-page')).display})",
                        lambda state: print("UI_VISIBILITY=" + str(state), flush=True))
                    def finish():
                        if args.screenshot:
                            screenshot = Path(args.screenshot).resolve()
                            screenshot.parent.mkdir(parents=True, exist_ok=True)
                            window.grab().save(str(screenshot))
                            def pdf_done(path, success):
                                value["pdf_created"] = success and Path(path).exists() and Path(path).stat().st_size > 1000
                                value["ok"] = value.get("ok", False) and value["pdf_created"]
                                screenshot.with_suffix(".json").write_text(json.dumps(value, indent=2), encoding="utf-8")
                                print("UI_TEST_RESULT=" + json.dumps(value, ensure_ascii=True), flush=True)
                                def input_capture():
                                    window.grab().save(str(screenshot.with_name(screenshot.stem + "-input.png")))
                                    app.exit(0 if value.get("ok") else 1)
                                def evidence_capture():
                                    window.grab().save(str(screenshot.with_name(screenshot.stem + "-evidence.png")))
                                    window.view.page().runJavaScript("changePage('input')")
                                    QTimer.singleShot(1000, input_capture)
                                window.view.page().runJavaScript("document.getElementById('evidence-panel').scrollIntoView()")
                                QTimer.singleShot(1200, evidence_capture)
                            window.view.page().pdfPrintingFinished.connect(pdf_done)
                            window.print_pdf(screenshot.with_suffix(".pdf"))
                        else:
                            print("UI_TEST_RESULT=" + json.dumps(value, ensure_ascii=True), flush=True)
                            app.exit(0 if value.get("ok") else 1)
                    QTimer.singleShot(1200, finish)
                elif elapsed["ticks"] > 360:
                    timer.stop()
                    print("UI_TEST_RESULT=timeout", flush=True)
                    app.exit(2)
            window.view.page().runJavaScript("JSON.stringify(window.__uiTest || {ready:document.readyState})", state)
        timer.timeout.connect(tick)
        def loaded(ok):
            print("UI_LOADED=" + str(ok), flush=True)
            if not ok:
                app.exit(1)
                return
            QTimer.singleShot(1200, lambda: window.view.page().runJavaScript(
                "window.runSmokeTest && window.runSmokeTest()"))
        window.view.loadFinished.connect(loaded)
        timer.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
