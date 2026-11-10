"""Predict with the full-target refit of the reconstructed Eye transfer model."""
import argparse
import json
from pathlib import Path

import joblib

from common import read_json, score_bundle

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=ROOT/'results/eye_transfer_final.joblib')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        raise FileExistsError(args.output)
    result = score_bundle(joblib.load(args.model), read_json(args.input))
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(serialized)
    else:
        print(serialized, end='')


if __name__ == '__main__':
    main()
