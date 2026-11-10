"""Verify inference vectorization against source matrices on stratified real examples."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import predict

ROOT = Path(__file__).resolve().parent


def main():
    source = json.loads((ROOT / 'source_config.json').read_text(encoding='utf-8'))['payload']
    path = ROOT / 'component_linkage.csv'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source['artifact_hashes']['component_linkage.csv']
    linkage = pd.read_csv(path)
    df = pd.read_csv(ROOT / 'input_snapshot.csv', low_memory=False)
    names = json.loads((ROOT / 'feature_names.json').read_text(encoding='utf-8'))
    selected = set()
    for _, rows in df.groupby(['evaluation_role', 'final_label']):
        selected.update(rows.index[:3].tolist())
        selected.add(int(rows.n_components_used.idxmax()))
    selected = sorted(selected)
    for rep in ('wmean', 'max'):
        matrix = np.load(ROOT / (rep + '.npy'))
        bundle = {'feature_names': names, 'representation': rep}
        for i in selected:
            parts = linkage[linkage.row_index == i]
            assert parts.formulation_id.eq(df.formulation_id.iloc[i]).all()
            actual = predict.vectorize_components(bundle, parts.smiles.tolist(), parts.weight.to_numpy()).to_numpy()[0]
            np.testing.assert_allclose(actual, matrix[i], rtol=1e-9, atol=1e-9, equal_nan=True, err_msg=f'{rep} row {i}')
        print(f'{rep}: {len(selected)} source rows reconstructed', flush=True)
    result = {'status': 'passed', 'rows': selected, 'representations': ['wmean', 'max'],
              'selection': 'First 3 and highest component count per original role/EPA class',
              'predict_sha256': hashlib.sha256((ROOT / 'predict.py').read_bytes()).hexdigest(),
              'rtol': 1e-9, 'atol': 1e-9}
    (ROOT / 'feature_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
