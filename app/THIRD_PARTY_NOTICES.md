# 자료와 의존성 출처

- 피부·눈 모델과 추론 패키지: COS_project 원본. 커밋과 해시는 `REPRODUCIBILITY.md`에 기록합니다. 원본 패키지의 설명과 해석 한계를 각 모델 폴더에 보존했습니다.
- 향료·계면활성제 보조점수: 사용자가 제공한 COS similarity 자료를 `desktop/similarity/`에 동봉했습니다. 계산 코드와 참조 JSON은 보존했고 앱 통합에 맞게 README만 정리했습니다. `SOURCE.json`에 원본 해시와 현재 파일 해시를 구분해 기록합니다. 이전 Chemical Category Scorer의 코드·학습 모델은 포함하지 않습니다.
- 주의정보: 제공된 성분 사전과 문헌 규칙을 사용합니다. 개별 출처는 `caution/citations.json`에 있습니다. 문헌 안내는 모델 점수에 합산하지 않습니다.
- 원료 정체성: PubChem에서 확인한 14개 물질의 이름·구조·선택한 별칭을 `desktop/identity_catalog.json`에 기록했습니다. 물질별 CID, 조회 URL, 조회 시각을 보존합니다. 별도 주석 조회 결과는 실시간 외부 응답이므로 동봉된 고정 자료와 구분합니다.
- UI 구성은 제공된 내분비계 Read-Across 앱의 사용 안내에서 타깃 구조·보조점수·구조패턴·주석 표시 흐름을 참고했습니다. 해당 앱의 실행파일이나 비공개 소스는 동봉하지 않습니다.

PySide6/Qt, RDKit, NumPy, SciPy, pandas, scikit-learn, joblib, PyInstaller 및 관련 패키지는 각 배포 패키지의 라이선스를 따릅니다. 정확한 사용 버전과 wheel 해시는 `requirements/`에 있습니다. 이 파일은 제3자 자료에 새로운 사용 허가를 부여하지 않습니다.
