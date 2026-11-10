# 향료·계면활성제 보조점수

사용자가 제공한 COS similarity 계산 코드와 참조 자료입니다. 현재 앱의 원료별 참고정보에 연결되어 있습니다. 별도의 학습 모델이나 네트워크 연결을 사용하지 않습니다.

- `fragrance_reference.json`: 향료 참조 20종. Morgan fingerprint(radius 2, 2,048 bits)의 최대 Tanimoto 유사도와 최근접 참조를 반환합니다.
- `surfactant_patterns.json`: SMARTS 구조 규칙 6종. 검출 구조와 비방향족 탄소의 최장 경로를 이용한 규칙 점수를 반환합니다.
- `similarity.py`: 두 계산의 구현
- `verify.py`: 고정 예제로 점수와 검출 패턴을 확인
- `SOURCE.json`: 원본 파일 해시, 현재 파일 해시, 문서 변경 이력

두 점수는 개별 원료 구조의 참고값이며 자극·알레르기 확률이 아닙니다. 농도, 혼합물의 상호작용, 피부·눈 모델 점수는 반영하지 않습니다. 구조 규칙 미검출은 안전 판정이 아닙니다.

원본 코드에는 큰 분자의 사슬 평가 제한이 있습니다. 앱 연결 코드 `desktop/evidence.py`는 사슬 평가가 생략된 경우 계면활성제 점수를 보류합니다. 강조 그림은 실제 SMARTS 매칭만 사용합니다.

앱 폴더에서 `.venv-eye\Scripts\python.exe desktop\similarity\verify.py`로 검사할 수 있습니다. 계산 코드·참조 JSON·검사 코드는 원본을 보존했고, 이 README는 현재 앱 통합 상태에 맞게 정리했습니다.
