# COS Lab 데스크톱 앱

원료명/CAS 또는 SMILES와 함량(%)을 입력해 피부·눈 자극 모델을 실행하는 Windows 데스크톱 앱입니다. 최신 COS Lab 0.3.0의 화면, 모델, 참고자료, 시연 예제와 실행·빌드 검사를 포함합니다. 이 `app/` 폴더만 따로 복사해도 실행할 수 있습니다.

## 간편 설치

**[Windows 설치용 ZIP 다운로드](https://github.com/tjdbf061106-sketch/COS_project/releases/download/coslab-v0.3.0/COSLab-0.3.0-Windows.zip)** · [릴리스 페이지](https://github.com/tjdbf061106-sketch/COS_project/releases/tag/coslab-v0.3.0)

1. `COSLab-0.3.0-Windows.zip`을 원하는 위치에 **전체 압축 해제**합니다.
2. 압축을 푼 `COSLab-0.3.0` 폴더로 이동합니다.
3. **`Install-COSLab.bat`를 더블클릭**합니다.
4. 설치가 끝나면 바탕화면의 **COS Lab** 바로가기를 실행합니다.

Windows 10/11 x64용이며 Python과 두 분석 엔진이 포함되어 있습니다. 관리자 권한 없이 현재 사용자 계정에 설치합니다. [사용 안내](USER_GUIDE.md)를 참고하세요.

아래는 소스에서 직접 실행하거나 같은 배포본을 만드는 개발·재현 방법입니다.

## 소스 환경 설치

Windows 10/11 x64와 인터넷이 필요합니다. 설치 스크립트가 **공식 CPython 3.14.6**을 앱 폴더 안에 준비하므로 Python을 미리 설치할 필요가 없습니다. free-threaded Python과 ARM64는 이 패키지의 대상이 아닙니다.

저장소를 내려받은 뒤 PowerShell에서 실행합니다.

```powershell
cd COS_project\app
powershell -NoProfile -ExecutionPolicy Bypass -File .\Setup-Windows.ps1
.\Start-COSLab.bat
```

설치 스크립트는 [Python 공식 문서에 안내된 NuGet 배포](https://docs.python.org/3.14/using/windows.html#the-nuget-org-packages)의 고정 버전을 내려받아 SHA-256을 확인합니다. `.runtime/`에 Python을 두고 `.venv-desktop`, `.venv-skin`, `.venv-eye`를 생성합니다. 시스템 Python·PATH를 변경하거나 시스템 패키지를 공유하지 않으며, `requirements/*.lock.txt`의 PyPI wheel 버전·해시를 확인해 설치합니다. `.runtime/`은 가상환경의 기반이므로 설치 후에도 보관하세요.

중단된 설치 복구는 위 설치 명령 끝에 `-Reinstall`을 붙입니다. 공식 CPython 3.14를 별도로 설치한 경우 그 Python으로 `scripts/setup_windows.py`를 직접 실행할 수도 있습니다. Anaconda Python 기반의 PySide6 wheel에서 DLL 오류가 확인되어, 기본 설치 경로는 공식 CPython으로 고정했습니다.

직접 실행할 수도 있습니다.

```powershell
.\.venv-desktop\Scripts\python.exe desktop_app.py
```

## 예제와 주요 기능

앱에서 **예제 불러오기 → 분석**을 선택합니다. 레티놀 0.3%, 리모넨 0.1%, 소듐라우릴설페이트 1%, 에탄올 20%, 글리세린 5%, 정제수 73.6%의 기능 시연용 입력입니다. 같은 조성의 CSV는 `examples/ingredients.csv`에 있습니다. 제품 제조나 사용 권고를 위한 배합은 아닙니다.

- 피부·눈 모델의 독립적인 분석과 판정 기준 표시
- 이름/CAS와 구조 일치 확인, 분자 구조 미리보기
- 로컬 향료 유사도·계면활성제 구조점수와 구조패턴 강조
- 입력 원료와 관련된 문헌 주의정보, 사전에 없는 원료 표시
- 배합 저장·불러오기, CSV 입력, 보고서 JSON·CSV·PDF 저장

동봉한 예제는 외부 조회 없이 실행됩니다. 로컬 사전에 없는 성분명 검색과 선택적 PubChem 주석 조회는 인터넷이 필요하며, 검색어나 선택한 구조가 PubChem으로 전송됩니다. 배합과 함량은 모델 계산을 위해 외부로 전송하지 않습니다. 사용자 초안·조회 캐시는 `%LOCALAPPDATA%\COSLab`에 저장됩니다.

## 재현 검사

```powershell
.\.venv-desktop\Scripts\python.exe scripts\verify_source.py
```

소스·자료 해시, 각 환경의 의존성 버전, 두 원본 모델의 재현검사, 앱 단위 검사, 실제 Qt 화면의 예제 분석·PDF 저장을 확인합니다. GUI 검사는 화면을 잠시 열며, 임시 사용자 폴더를 사용하고 외부 조회를 차단합니다. 로그와 결과는 `build/source-verification/`에 저장됩니다.

| 예제 | 피부 점수 | 눈 점수 |
|---|---:|---:|
| 기본 6개 원료 | 0.202 | 0.6192026683768463 |
| 에탄올 20% + 물 80% | 0.178 | 0.6232614237228717 |

피부 임계값은 `0.33`, 눈 임계값은 `0.48345327423625106`입니다. 이 숫자는 고정 입력의 실행 재현 확인값이며 예측 정확도나 실제 발병 확률이 아닙니다. 검사 범위와 모델 출처는 [REPRODUCIBILITY.md](REPRODUCIBILITY.md)에 정리했습니다.

## Windows 실행파일 빌드

위 설치를 마친 같은 `app/` 폴더에서 실행합니다.

```powershell
.\.venv-desktop\Scripts\python.exe scripts\build_windows.py desktop
.\.venv-desktop\Scripts\python.exe scripts\build_windows.py skin
.\.venv-desktop\Scripts\python.exe scripts\build_windows.py eye
.\.venv-desktop\Scripts\python.exe scripts\build_windows.py assemble
.\.venv-desktop\Scripts\python.exe scripts\verify_release.py
.\.venv-desktop\Scripts\python.exe scripts\package_windows.py
```

실행파일은 `release/COSLab-0.3.0/COSLab.exe`, ZIP은 `release/COSLab-0.3.0-Windows.zip`에 생성됩니다. 배포 폴더 전체에 Python과 두 엔진이 포함되므로, 완성된 배포본을 실행하는 PC에는 별도 Python 설치가 필요하지 않습니다. 배포 폴더의 `Install-COSLab.bat`는 사용자 계정에 복사하고 바탕화면 바로가기를 만듭니다. EXE는 코드 서명되지 않습니다.

## 파일 구성

| 경로 | 용도 |
|---|---|
| `desktop_app.py`, `desktop/ui/` | Qt 창과 로컬 HTML/CSS/JavaScript 화면 |
| `desktop/`, `engine_entry.py` | 입력 확인, 모델별 작업 프로세스, 보고서 |
| `skin/`, `eye/` | 원본 모델·전처리·예측 코드·회귀 예제 |
| `desktop/similarity/` | 향료·계면활성제 로컬 보조점수 |
| `caution/` | 주의정보 사전·규칙·문헌 출처 |
| `requirements/` | 환경별 버전·wheel 해시 잠금 |
| `tests/`, `scripts/` | 설치·재현검사·빌드·배포 |
| `SHA256SUMS.json` | 동봉한 소스·자료의 파일별 해시 |

학습 데이터와 재학습 코드는 포함하지 않습니다. 원본 모델의 독립 실행을 위한 `requirements.txt`와 `eye/requirements-lock.txt`도 보존했지만, **앱 설치에는 `Setup-Windows.ps1`을 사용**하세요.

현재 모델은 농약 제형 자료에 기반한 연구용 예측 모델입니다. 이 앱의 실행 재현은 화장품에서의 외부 성능 검증이나 환자별 사용 적합성 판정을 뜻하지 않습니다. 모델 점수, 문헌 주의정보, 구조 보조점수는 별도로 표시합니다.
