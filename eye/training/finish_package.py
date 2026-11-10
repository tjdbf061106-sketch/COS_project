"""Verify portable predictions and publish a Korean result receipt after successful training."""
from __future__ import annotations
import os
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[name] = '1'
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
import predict
import epa_harness as u

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8-sig'))


def main():
    comparison = read('comparison_verification.json')
    final = read('final_verification.json')
    features = read('feature_verification.json')
    assert comparison['status'] == final['status'] == features['status'] == 'passed'
    assert features['predict_sha256'] == u.file_hash(ROOT / 'predict.py')
    bundle = predict.load_bundle()
    assert bundle['metadata']['comparison_identity'] == comparison['identity']
    assert bundle['metadata']['identity'] == final['identity']
    matrix = np.load(ROOT / (bundle['representation'] + '.npy'))
    reference = pd.read_csv(ROOT / 'refit_reference_predictions.csv')
    result = predict.predict_features(bundle, matrix)
    np.testing.assert_allclose(result.eye_A_score, reference.score, rtol=0, atol=1e-12)
    np.testing.assert_array_equal(result.eye_A_prediction, reference.prediction)
    with tempfile.TemporaryDirectory(prefix='eye-model-verification-') as tmp:
        tmp = Path(tmp)
        frame = pd.DataFrame(matrix[:8], columns=bundle['feature_names'])
        frame.insert(0, 'formulation_id', reference.formulation_id.iloc[:8].to_numpy())
        frame.to_csv(tmp / 'input.csv', index=False)
        subprocess.run([sys.executable, str(ROOT / 'predict.py'), '--model', str(ROOT / 'eye_A_final.joblib'),
                        '--input', str(tmp / 'input.csv'), '--output', str(tmp / 'output.csv')], cwd=tmp, check=True)
        actual = pd.read_csv(tmp / 'output.csv')
        np.testing.assert_allclose(actual.eye_A_score, reference.score.iloc[:8], rtol=1e-10, atol=1e-12)
        np.testing.assert_array_equal(actual.eye_A_prediction, reference.prediction.iloc[:8])
        np.testing.assert_array_equal(actual.formulation_id, reference.formulation_id.iloc[:8])
    cfg = read('comparison_config.json')['payload']
    packages = cfg['environment']['packages']
    (ROOT / 'requirements-lock.txt').write_text(''.join(f'{k}=={v}\n' for k, v in packages.items()), encoding='utf-8')
    ranking = pd.read_csv(ROOT / 'ranking.csv')
    lines = ['673행 전체 그룹 기반 중첩 교차검증 결과', '',
             '대상: EPA I/II 양성, III/IV 음성. 양성 125행 / 음성 548행.',
             'LR / Random Forest / XGBoost × 가중평균 / 특징별 최댓값의 6개 조합.',
             '모든 조합에 동일한 388개 그룹과 3개 시드 × 외부 5폴드 / 내부 3폴드를 적용.',
             '추가 67행도 평가에 포함. 각 시드에서 673행을 한 번씩 외부 평가.',
             '전처리와 클래스 가중치는 학습 폴드에서만 산정. 설정 및 임계값은 내부 폴드에서만 선정.',
             '', '비교 순위 (시드별 전체 OOF 지표의 평균):']
    for _, row in ranking.iterrows():
        lines.append(f"{int(row['rank'])}. {row.model} / {row.representation}: 민감도 {row.sensitivity_mean:.5f}, 특이도 {row.specificity_mean:.5f}, MCC {row.MCC_mean:.5f}, ROC-AUC {row['ROC-AUC_mean']:.5f}")
    lines += ['', '선정 기준: 평균 MCC, 동률이면 평균 AUC, 민감도·특이도 차이 순.',
              f"최종 모델: {bundle['model']} / {bundle['representation']}",
              f"최종 판정: 점수 >= {bundle['threshold']:.16g}",
              '선정 모델의 설정을 673행 반복 그룹 교차검증으로 다시 조정한 뒤 전체 673행으로 재학습.',
              '', '해석상 한계:',
              '- 비교 결과로 우승 모델을 골랐으므로 우승 모델의 같은 성능치는 선택 편향이 없는 독립 평가가 아님.',
              '- 시드당 ROC-AUC는 여러 외부 모델의 OOF 예측을 합친 값이며, 폴드 AUC 평균과 다름.',
              '- 2,019개 반복 예측은 독립 표본 2,019개가 아님. 실제 고유 표본은 673개.',
              '- 시드 간 표준편차는 기술통계이며 독립 코호트 신뢰구간이 아님.',
              '- 최종 모델에 대한 외부 독립 성능 및 실제 자극 확률 보정은 검증하지 않음.',
              '- EPA III/IV 예측은 모든 눈 자극의 부재를 뜻하지 않음.',
              '', '파일:',
              'ranking.csv / metrics_summary.csv: 여섯 조합의 비교와 하위집단 결과',
              'metrics_by_seed.csv / metrics_by_fold.csv: 시드·폴드별 결과',
              'oof_predictions.csv: 6조합 × 3시드 × 673행의 외부 평가 예측',
              'results/: 90개 외부 모델, 내부 후보 예측, 설정·임계값 근거',
              'comparison_verification.json: 분할·선정·예측 재구성·보고서 검증',
              'eye_A_final.joblib / predict.py: 최종 모델과 예측 실행 코드',
              'development_oof_predictions.csv / hyperparameter_search.csv: 최종 설정 선정용 결과 (독립 테스트 아님)',
              'input_snapshot.csv / wmean.npy / max.npy / component_linkage.csv: 재현용 입력',
              '', '예측:',
              'python predict.py --input input_features.csv --output predictions.csv',
              '입력 특징은 반드시 metadata.json의 representation 방식으로 계산해야 함.',
              '특징 열 이름은 원자료와 동일하며 max에서도 fp_w_* 이름을 유지하므로 이름만으로 집계 방식을 판단하면 안 됨.',
              '성분 입력 API: bundle = load_bundle(); features = vectorize_components(bundle, smiles, percentages); predict_features(bundle, features)',
              '', '재현 / 중단 후 재개:',
              'python run_comparison.py --workers 6',
              'python verify_comparison.py',
              'python finalize_model.py --workers 6',
              'python verify_features.py',
              'python finish_package.py']
    (ROOT / 'RESULTS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    u.atomic_json(ROOT / 'package_verification.json', {'status': 'passed', 'comparison_identity': comparison['identity'],
                  'full_row_predictions_checked': 673, 'separate_process_predictions_checked': 8,
                  'feature_parity_rows': len(features['rows']), 'feature_parity_representations': features['representations']})
    u.atomic_json(ROOT / 'status.json', {'status': 'complete', 'identity': comparison['identity'], 'completed_outer': 90,
                  'total_outer': 90, 'model': bundle['model'], 'representation': bundle['representation'],
                  'comparison_verified': True, 'final_package_verified': True})
    hashes = {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in ROOT.rglob('*') if path.is_file() and '__pycache__' not in path.parts
              and path.name not in ('checksums.json', '.comparison.lock') and not path.name.endswith('.tmp')}
    u.atomic_json(ROOT / 'checksums.json', hashes)
    print('FINAL PACKAGE VERIFIED', flush=True)


if __name__ == '__main__':
    main()
