"""Compare the numeric content of JSON (and optionally CSV) outputs between two copies of this package.

Usage:  python compare_outputs.py <published_root> <rerun_root> [--tol 1e-9] [--csv] [paths ...]

Without paths, every *.json under publication/experiments, results, robustness/results and verification is compared
(unzipped caches are skipped).
Numbers are compared with an absolute tolerance; strings, keys and list lengths must match exactly, except keys that
record run times, file hashes or host paths (see SKIP_KEYS). Exit status 1 if any difference exceeds the tolerance.
Standard library only.
"""
from pathlib import Path
import argparse, csv, json, math, sys

SKIP_KEYS = {'generated_at', 'completed_at', 'started_at', 'finished_at', 'run_at', 'created_at', 'collected_at',
             'elapsed_seconds', 'runtime_seconds', 'seconds', 'python', 'executable', 'host', 'cwd', 'path', 'paths',
             'script_sha256', 'sha256', 'source_sha256', 'output_sha256', 'protected_inputs', 'outputs',
             'versions', 'numpy', 'pandas', 'sklearn', 'scikit-learn', 'scipy', 'xgboost', 'duckdb'}  # library versions are reported, not compared
DEFAULT_DIRS = ['publication/experiments', 'results', 'robustness/results', 'verification']


def walk(a, b, where, tol, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in SKIP_KEYS or str(k).endswith('sha256') or k == 'inputs':
                continue  # hashes of re-written files change with the last digit of floats
            if k not in a or k not in b:
                out.append((where + '/' + str(k), 'key only in ' + ('rerun' if k in b else 'published')))
                continue
            walk(a[k], b[k], where + '/' + str(k), tol, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((where, f'list length {len(a)} vs {len(b)}'))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f'{where}[{i}]', tol, out)
    elif isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            out.append((where, f'{a!r} vs {b!r}'))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return
        if abs(a - b) > tol:
            out.append((where, f'{a!r} vs {b!r} (diff {abs(a - b):.3g})'))
    elif a != b:
        out.append((where, f'{str(a)[:60]!r} vs {str(b)[:60]!r}'))


def num(s):
    try:
        return float(s)
    except ValueError:
        return s


def compare_csv(p, q, tol, out, rel):
    with p.open(encoding='utf-8', newline='') as f1, q.open(encoding='utf-8', newline='') as f2:
        r1, r2 = list(csv.reader(f1)), list(csv.reader(f2))
    if len(r1) != len(r2):
        out.append((rel, f'rows {len(r1)} vs {len(r2)}'))
        return
    for i, (x, y) in enumerate(zip(r1, r2)):
        walk([num(v) for v in x], [num(v) for v in y], f'{rel}:row{i}', tol, out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('published'); ap.add_argument('rerun'); ap.add_argument('paths', nargs='*')
    ap.add_argument('--tol', type=float, default=1e-9); ap.add_argument('--csv', action='store_true')
    a = ap.parse_args()
    A, B = Path(a.published), Path(a.rerun)
    if a.paths:
        rels = a.paths
    else:
        rels = sorted(p.relative_to(B).as_posix() for d in DEFAULT_DIRS if (B / d).exists()
                      for p in (B / d).rglob('*.json' if not a.csv else '*') if p.is_file() and p.suffix in ('.json', '.csv')
                      and not any(part == 'cache' or part.startswith('db_') for part in p.relative_to(B).parts))
    bad = 0
    for rel in rels:
        p, q = A / rel, B / rel
        if not p.exists() or not q.exists():
            print(f'MISSING  {rel}'); bad += 1; continue
        out = []
        if rel.endswith('.json'):
            walk(json.loads(p.read_text(encoding='utf-8')), json.loads(q.read_text(encoding='utf-8')), '', a.tol, out)
        else:
            compare_csv(p, q, a.tol, out, rel)
        if out:
            bad += 1
            print(f'DIFF     {rel}  ({len(out)} differences)')
            for w, msg in out[:5]:
                print(f'           {w}: {msg}')
        else:
            print(f'SAME     {rel}')
    print(f'\n{len(rels) - bad} of {len(rels)} files match within {a.tol}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
