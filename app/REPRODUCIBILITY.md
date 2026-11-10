# 재현 범위와 모델 출처

이 패키지는 **저장된 모델의 추론과 앱 기능 재현**을 대상으로 합니다. 재학습, 독립 외부 성능 평가, EXE/ZIP의 바이트 단위 동일성은 보장 범위가 아닙니다. 빌드 시각과 운영체제·폰트 등의 차이로 실행파일 해시와 PDF 페이지 배치는 달라질 수 있습니다.

## 고정된 모델

원본 저장소: https://github.com/tjdbf061106-sketch/COS_project

| 항목 | 피부 | 눈 |
|---|---|---|
| 모델 | Random Forest | Logistic Regression, all673 그룹 평가 버전 |
| 원본 커밋 | `4ab6bd83a271f52f0384d7c415c804f600ec8956` | `c20f6b737b992676de66da1b86800c058275ce56` |
| 파일 | `skin/skin_rf_checkpoint.joblib` | `eye/eye_A_final.joblib` |
| 임계값 | `0.33` | `0.48345327423625106` |
| 양성 클래스 | EPA I·II·III | EPA I·II |

피부 모델 SHA-256: `1ff0bd062fba0fab11c0407731ddb6996c7646bf033e07a4c501a391a2459e34`

눈 모델 SHA-256: `5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5`

두 모델 폴더는 원본 파일을 보존했습니다. 상위 저장소의 `skin/`, `eye/model/`과 같은 모델을 `app/`에도 포함해 폴더를 단독으로 옮겨 실행할 수 있습니다. 눈 모델의 예전 파일 `eye_A_LR_wmean.joblib`은 포함하지 않습니다. 향후 교체할 때는 모델만 바꾸지 말고 추론 코드·특징 순서·임계값·의존성·회귀 예제를 함께 갱신해야 합니다.

## 환경

- Windows x64, 공식 CPython 3.14.6 기반의 격리된 가상환경 3개. `Setup-Windows.ps1`이 Python NuGet 패키지까지 버전·SHA-256으로 고정하며 시스템 설정을 변경하지 않음
- GUI: PySide6 6.11.0의 PyPI wheel. 기존 개발 PC의 시스템 Qt 패키지에 의존하지 않음
- 피부: NumPy 2.5.0, RDKit 2026.9.1, scikit-learn 1.9.0
- 눈: NumPy 2.4.6, RDKit 2025.9.6, scikit-learn 1.9.0
- 빌드: PyInstaller 6.22.3, hooks 2026.9
- 전체 전이 의존성은 `requirements/*.lock.txt`에 버전과 다운로드 wheel의 SHA-256을 고정

`skin/metadata.json`의 Python 3.13.12는 원본 피부 패키지 준비 환경의 기록입니다. 이 앱은 피부 모델을 Python 3.14.6 환경에서 별도로 재현 검사합니다. 다른 운영체제·아키텍처·Python 버전에는 별도 검증이 필요합니다.

## 검사 방법

`.venv-desktop/Scripts/python.exe scripts/verify_source.py`는 다음을 순서대로 실행합니다.

1. `SHA256SUMS.json`에 기록된 소스·모델·자료의 무결성 확인
2. 세 가상환경의 시스템 패키지 비공유와 잠금 파일의 패키지 버전 확인
3. 피부·눈 원본 `verify.py`: 모델 해시, 특징 계약, 고정 예측값, 잘못된 입력 거부
4. 앱 단위 검사 36개: 입력·성분 정체성·주의정보·보조점수·최종 눈 모델 연결
5. 주의정보·similarity 자체 검사
6. 실제 Qt 화면에서 기본 예제, 새 눈 모델 해시·임계값, 원료 전환, 미확인 원료 표시, PDF 생성 확인

입력 예제와 계산 자료는 고정되어 있습니다. 이름·주석의 외부 조회 기능은 PubChem의 가용성과 응답에 영향을 받으므로 위 오프라인 재현검사의 대상과 구분합니다. `scripts/verify_caution_filter.py`는 추가 GUI 검사이며 일부 외부 이름 조회 때문에 인터넷이 필요합니다.

빌드 후에는 `.venv-desktop/Scripts/python.exe scripts/verify_release.py`로 실제 EXE를 검사합니다. Python/Conda를 PATH에서 제외하고 임시 사용자 폴더에서 실행하지만, Python이 전혀 설치되지 않은 별도 PC에서의 시험을 대신하지는 않습니다. 검사 성공 후 `package_windows.py`가 ZIP의 CRC와 SHA-256을 생성합니다.

로그·스크린샷·PDF·생성된 실행파일은 `build/`, `release/`에만 저장하며 Git에서 제외합니다. 사용자 배합·캐시·개인 보고서는 동봉하지 않습니다.

## 확인 기록 — 2026-11-10

- `Setup-Windows.ps1 -Reinstall`로 공식 CPython 3.14.6과 잠금 파일의 PyPI wheel을 설치했습니다. 세 환경의 의존성 검사와 Qt 로드가 통과했습니다.
- `verify_source.py`에서 동봉 파일 해시, 두 원본 모델 검사, 앱 단위 검사 36개, 주의정보·보조점수 검사와 실제 GUI·PDF 생성이 통과했습니다.
- 기본 6개 원료 예제는 피부 `0.202`, 눈 `0.6192026683768463`을 재현했고 눈 임계값 `0.48345327423625106`과 모델 해시를 확인했습니다.
- 이 폴더에서 GUI·피부·눈 실행파일을 각각 새로 빌드한 뒤 `verify_release.py`가 통과했습니다. 원본 눈 패키지 체크섬 11개, 두 엔진의 정상·오류 입력 10개, 보조점수 입력 3개와 실제 EXE의 예제 분석·PDF 출력을 확인했습니다.
- 간편 설치 프로그램도 별도 설치·바로가기 폴더에서 확인했습니다. 복사된 EXE·두 모델의 해시, Windows 바로가기의 실행 대상·작업 폴더가 일치했고, 설치된 앱을 Python/Conda가 없는 PATH에서 실행해 6개 원료 예제와 PDF 생성을 확인했습니다. `Install-COSLab.ps1`의 선택적 경로 인수는 이 격리 검사에 사용하며, 배치파일을 더블클릭할 때는 기본 사용자 설치 경로와 바탕화면을 사용합니다.

검증 범위는 Windows 11 x64의 위 환경이며, 다른 PC에서의 시험이나 독립적인 예측 성능 평가를 의미하지 않습니다.
