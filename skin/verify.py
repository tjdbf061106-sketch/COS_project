"""Run: python skin/verify.py. Uses only the submitted inference package."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

root = Path(__file__).resolve().parent
metadata = json.loads((root / 'metadata.json').read_text(encoding='utf-8'))
assert hashlib.sha256((root / 'skin_rf_checkpoint.joblib').read_bytes()).hexdigest() == metadata['checkpoint_sha256']
cases = json.loads((root / 'smoke_test_cases.json').read_text(encoding='utf-8'))
for case in cases:
    result = subprocess.run(
        [sys.executable, '-I', str(root / 'predict.py'), '--input', str(root / case['input'])],
        check=True, capture_output=True, text=True, encoding='utf-8',
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    assert json.loads(result.stdout) == case['expected'], case['input']
print(f'PASS: checkpoint hash and {len(cases)} isolated inference cases')
