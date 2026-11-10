# 문헌 주의정보 모듈

`match.py`가 원료와 선택한 상태·병용 약물에 해당하는 문헌 규칙을 조회합니다. 현재 COS Lab의 보고서 화면에 연결되어 있으며 피부·눈 모델 점수와 별도로 표시합니다.

- `ingredient_tags.json`: 성분명·별칭·구조와 주의 태그
- `conditions.json`, `medications.json`: 상태와 병용 약물·치료 선택지
- `rules.json`: 태그와 선택 항목을 연결하는 규칙
- `citations.json`: 문헌 출처
- `examples/`, `verify.py`: 독립적인 회귀 예제와 검사

앱은 원료의 이름·구조를 확인한 뒤 관련 선택지를 표시하고, 사전에 없는 원료를 별도로 안내합니다. 매칭되지 않았다는 사실은 안전 판정이 아닙니다. `alcohol_high_conc` 규칙은 15% 초과 여부를 사용하며, 다른 규칙은 주로 성분 검출에 기반합니다. 이 모듈은 질환별 사용 가능 여부를 결정하지 않습니다.

앱 폴더에서 `.venv-eye\Scripts\python.exe caution\verify.py`로 검사할 수 있습니다.
