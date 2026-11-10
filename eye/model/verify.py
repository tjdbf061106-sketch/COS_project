"""Validate this folder's checksums, feature recipe, cutoff, and portable CLI."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd

from predict import load_bundle, predict_components, predict_features, vectorize_components

ROOT=Path(__file__).resolve().parent


def expect_value_error(function, *args):
    try:
        function(*args)
    except ValueError:
        return
    raise AssertionError(f'{function.__name__} accepted invalid input')


def main():
    checks=json.loads((ROOT/'checksums.json').read_text(encoding='utf-8'))
    for name,expected in checks['files'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Checksum path outside package')
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=expected:
            raise ValueError(f'Checksum mismatch: {name}')
    for line in (ROOT/'requirements-lock.txt').read_text(encoding='utf-8').splitlines():
        name,version=line.split('==')
        if importlib.metadata.version(name)!=version:
            raise ValueError(f'Install the locked version: {line}')
    model=load_bundle()
    metadata=json.loads((ROOT/'metadata.json').read_text(encoding='utf-8'))
    names=json.loads((ROOT/'feature_names.json').read_text(encoding='utf-8'))
    if model['metadata']!=metadata or model['feature_names']!=names:
        raise ValueError('Readable metadata and model contents disagree')
    if model['threshold']!=metadata['threshold']:
        raise ValueError('Threshold mismatch')
    required_metadata = {
        'model': 'lr',
        'representation': 'wmean',
        'training_rows': 673,
        'evaluation_unique_rows': 673,
        'n_features': len(names),
        'class_counts': {'negative': 548, 'positive': 125},
        'parameters': {'C': 0.0001, 'solver': 'lbfgs', 'max_iter': 5000, 'tol': 0.0001},
        'comparison_operator': '>=',
    }
    for key, value in required_metadata.items():
        if metadata.get(key) != value:
            raise ValueError(f'Unexpected all673 metadata: {key}')
    if model['model'] != metadata['model'] or model['representation'] != metadata['representation']:
        raise ValueError('Bundle and metadata model configuration disagree')
    estimator_parameters = model['pipeline'].steps[-1][1].get_params()
    for key, value in metadata['parameters'].items():
        if estimator_parameters.get(key) != value:
            raise ValueError(f'Fitted model parameter mismatch: {key}')
    fixture=json.loads((ROOT/'smoke_test_cases.json').read_text(encoding='utf-8'))
    if fixture['source_model_sha256']!=checks['files']['eye_A_final.joblib']:
        raise ValueError('Regression fixtures refer to a different model')
    frames=[]
    for case in fixture['cases']:
        frame=vectorize_components(names,case['smiles'],case['amounts'])
        result=predict_features(model,frame).iloc[0]
        np.testing.assert_allclose(result.eye_A_score,case['expected_score'],rtol=0,atol=1e-10)
        if int(result.eye_A_prediction)!=case['expected_prediction']:
            raise AssertionError(f"Prediction changed: {case['name']}")
        amounts = case['amounts'] if case['amounts'] is not None else [100.0]
        payload = {'components': [{'canonical_smiles': s, 'amount_pct': a}
                                  for s, a in zip(case['smiles'], amounts)]}
        json_result = predict_components(model, payload)
        np.testing.assert_allclose(json_result['eye_A_score'], case['expected_score'], rtol=0, atol=1e-10)
        if json_result['eye_A_prediction'] != case['expected_prediction']:
            raise AssertionError(f"JSON prediction changed: {case['name']}")
        frames.append(frame)
    combined=pd.concat(frames,ignore_index=True)
    expected=predict_features(model,combined)
    np.testing.assert_allclose(predict_features(model,combined[names[::-1]]).eye_A_score,
                               expected.eye_A_score,rtol=0,atol=1e-12)
    expect_value_error(predict_features, model, combined.drop(columns=names[0]))
    expect_value_error(predict_features, model, pd.concat([combined, combined[[names[0]]]], axis=1))
    for value in (np.inf, -np.inf):
        infinite = combined.copy()
        infinite.iloc[0, 0] = value
        expect_value_error(predict_features, model, infinite)
    expect_value_error(predict_features, model, combined.iloc[:0])
    expect_value_error(predict_features, model, np.empty((0, len(names))))
    boundary_frame = combined.iloc[:1]
    boundary_score = float(predict_features(model, boundary_frame).eye_A_score.iloc[0])
    for cutoff, label in [(np.nextafter(boundary_score, -np.inf), 1),
                          (boundary_score, 1),
                          (np.nextafter(boundary_score, np.inf), 0)]:
        boundary_model = dict(model, threshold=cutoff)
        actual = predict_features(boundary_model, boundary_frame).eye_A_prediction.iloc[0]
        if actual != label:
            raise AssertionError('Decision cutoff must use >=, including exact equality')
    # Only these two files are available to the fresh isolated inference process.
    with tempfile.TemporaryDirectory(prefix='eye_final_portable_') as temporary:
        temporary=Path(temporary)
        for key, value in [('format', 'eye-A-lr-wmean-v1'),
                           ('format', 'unknown'),
                           ('model', 'rf'),
                           ('representation', 'max')]:
            invalid_bundle = dict(model)
            invalid_bundle[key] = value
            invalid_path = temporary/'invalid.joblib'
            joblib.dump(invalid_bundle, invalid_path)
            expect_value_error(load_bundle, invalid_path)
        for key in ('format', 'model', 'representation'):
            invalid_bundle = dict(model)
            del invalid_bundle[key]
            joblib.dump(invalid_bundle, invalid_path)
            expect_value_error(load_bundle, invalid_path)
        invalid_path.unlink()
        for name in ['predict.py','eye_A_final.joblib']:
            shutil.copyfile(ROOT/name,temporary/name)
        combined.to_csv(temporary/'input.csv',index=False)
        command=[sys.executable,'-I',str(temporary/'predict.py'),'--input','input.csv','--output','output.csv']
        subprocess.run(command,cwd=temporary,check=True,capture_output=True,text=True,encoding='utf-8')
        actual=pd.read_csv(temporary/'output.csv')
        np.testing.assert_allclose(actual.eye_A_score,expected.eye_A_score,rtol=0,atol=1e-12)
        np.testing.assert_array_equal(actual.eye_A_prediction,expected.eye_A_prediction)
        np.testing.assert_allclose(actual.decision_threshold,model['threshold'],rtol=0,atol=1e-15)
        for example, case_name in [('single_ingredient.json', 'single_ethanol'),
                                    ('two_component_formulation.json', 'two_components')]:
            shutil.copyfile(ROOT/'examples'/example, temporary/example)
            completed = subprocess.run(
                [sys.executable, '-I', str(temporary/'predict.py'), '--input', example],
                cwd=temporary, check=True, capture_output=True, text=True, encoding='utf-8')
            result = json.loads(completed.stdout)
            case = next(c for c in fixture['cases'] if c['name'] == case_name)
            np.testing.assert_allclose(result['eye_A_score'], case['expected_score'], rtol=0, atol=1e-10)
            if result['eye_A_prediction'] != case['expected_prediction']:
                raise AssertionError(f'Isolated JSON prediction changed: {example}')
        # The JSON CLI must reject incomplete or invalid composition input.
        invalid_payloads = [
            {'components': []},
            {'components': [{'canonical_smiles': 'O'}]},
            {'components': [{'canonical_smiles': 'O', 'amount_pct': -1}]},
            {'components': [{'canonical_smiles': 'O', 'amount_pct': 0}]},
            {'components': [{'canonical_smiles': 'O', 'amount_pct': 70},
                            {'canonical_smiles': 'CCO', 'amount_pct': 70}]},
            {'components': [{'canonical_smiles': 'invalid_smiles', 'amount_pct': 100}]},
        ]
        for payload in invalid_payloads:
            (temporary/'invalid.json').write_text(json.dumps(payload), encoding='utf-8')
            completed = subprocess.run(
                [sys.executable, '-I', str(temporary/'predict.py'), '--input', 'invalid.json'],
                cwd=temporary, capture_output=True, text=True, encoding='utf-8')
            if completed.returncode == 0:
                raise AssertionError(f'Invalid JSON input accepted: {payload}')
    print(json.dumps({'status':'passed','checksummed_files':len(checks['files']),
        'synthetic_regression_cases':len(frames),'isolated_cli_prediction_match':True,
        'isolated_json_examples':2,'invalid_json_inputs_rejected':len(invalid_payloads),
        'source_training_folders_required_for_inference':False,'threshold':model['threshold']},indent=2))


if __name__=='__main__':
    main()
