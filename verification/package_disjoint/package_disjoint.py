"""Package-disjoint evaluation (ISWA plan, advisor item 5). Exploratory, post hoc; protocol fixed before the run.

Question: do the models still rank test dependencies when no package of a test row was seen in training?
Design (per test origin, same training eligibility as the main backtest):
- Rows, labels, features, model parameters: robustness/data/date_12_paired.csv + publication/protocol/rq_completion.json
  (identical to rq_completion/executed_source.py; library versions asserted equal to its frozen manifest).
- Packages of the test snapshot are split into 5 groups by sha256(package) % 5 (deterministic, outcome-blind).
- For group g, every training row whose package is in group g is removed; models are fitted on the rest and
  score only the test rows of group g. The 5 group predictions are pooled, so every test row is scored by a
  model that never saw its package.
- Scorers: full LR/RF/XGB, the same without libyear, libyear-only LR (all disjoint-trained); libyear score and the
  prior-advisory rule (no training data, unchanged); the main (seen-package) full models on the same rows.
- Metrics: AP, ROC-AUC, Precision/Recall@K for K = 1/5/10/20 % with the four_step tie policy (expected value under
  random order within the cutoff tie). Intervals: package-cluster paired bootstrap, 1,000 resamples, seed 42.
Run with the bundled Python 3.12 (offline):  & $py verification\\package_disjoint\\package_disjoint.py
Writes only into verification/package_disjoint/.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, math, sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'publication'
sys.path[:0] = [str(P / 'tools/vendor'), str(ROOT / 'tools/vendor'), str(ROOT / 'verification/exposure')]
import exposure_analysis as ex  # noqa: E402  (advisory_index, prior_count; offline caches)

FOLDS, RULE = 5, 'prior_advisory_rule'
KEYS = ['origin', 'project', 'package', 'dependency_type', 'used_version', 'label']


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def group_of(package):
    return int(hashlib.sha256(package.encode('utf-8')).hexdigest(), 16) % FOLDS


def run():
    import numpy as np, pandas as pd, sklearn, scipy, xgboost
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score
    from xgboost import XGBClassifier
    cfg = load(P / 'protocol/rq_completion.json'); follow = load(P / 'protocol/four_step_followup.json')
    versions = {'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__, 'scipy': scipy.__version__, 'xgboost': xgboost.__version__}
    assert versions == load(P / 'experiments/rq_completion/frozen_manifest.json')['versions'], versions
    features, budgets = cfg['features'], follow['budgets']
    factories = {'lr': lambda: LogisticRegression(**cfg['models']['lr']), 'rf': lambda: RandomForestClassifier(**cfg['models']['rf']),
                 'xgb': lambda: XGBClassifier(**cfg['models']['xgb'])}
    specs = [(f'full_{a}', a, features) for a in factories] + [(f'drop_libyear_{a}', a, [f for f in features if f != 'libyear']) for a in factories] \
        + [('libyear_only_lr', 'lr', ['libyear'])]

    # ------------------------------------------------ copied from four_step/executed_evaluate.py (tie-aware budget stats)
    def plan(s):
        levels, codes = np.unique(s, return_inverse=True); return len(levels) - 1 - codes, len(levels)

    def stats(y, w, pl, budget):
        codes, n = pl; pos = np.bincount(codes, weights=w * y, minlength=n); counts = np.bincount(codes, weights=w, minlength=n); cp = np.cumsum(pos); ct = np.cumsum(counts); total = counts.sum(); positive = pos.sum()
        ap = float((np.divide(cp, ct, out=np.zeros(n), where=ct > 0) * pos).sum() / positive)
        k = min(int(round(total)), max(1, math.ceil(total * budget - 1e-10))); index = int(np.searchsorted(ct, k, side='left')); before = ct[index - 1] if index else 0.; ph = cp[index - 1] if index else 0.
        hits = float(ph + (k - before) * pos[index] / counts[index])
        return {'ap': ap, 'budget_n': k, 'hits': hits, 'precision': hits / k, 'recall': hits / positive}
    # ------------------------------------------------

    frame_all = pd.read_csv(ROOT / 'robustness/data/date_12_paired.csv', keep_default_na=False)
    idx, adv_meta = ex.advisory_index()
    points, intervals, folds_log = [], [], []
    for origin in cfg['origins'][1:]:
        test = frame_all[frame_all.origin == origin].reset_index(drop=True)
        train = frame_all[(frame_all.origin < origin) & (frame_all.window_end <= origin)].reset_index(drop=True)
        main = pd.read_csv(P / 'experiments/rq_completion' / origin / 'predictions_wide.csv', keep_default_na=False)
        assert test[KEYS].equals(main[KEYS])
        test_group = test.package.map(group_of).to_numpy(); test_packages = set(test.package)
        scores = {name: np.full(len(test), np.nan) for name, _, _ in specs}
        for g in range(FOLDS):
            held = {p for p in test_packages if group_of(p) == g}
            tr = train[~train.package.isin(held)]; rows = test_group == g
            assert tr.label.nunique() == 2 and not (set(tr.package) & held)
            for name, algorithm, columns in specs:
                model = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), factories[algorithm]())
                model.fit(tr[columns], tr.label); scores[name][rows] = model.predict_proba(test.loc[rows, columns])[:, 1]
            folds_log.append({'origin': origin, 'group': g, 'test_rows': int(rows.sum()), 'test_positives': int(test.label[rows].sum()), 'test_packages': len(held),
                              'train_rows': len(tr), 'train_positives': int(tr.label.sum()), 'removed_train_rows': len(train) - len(tr)})
            print('fit', origin, 'group', g, flush=True)
        assert all(not np.isnan(s).any() for s in scores.values())
        scores = {f'disjoint_{k}': v for k, v in scores.items()}
        for a in factories: scores[f'seen_full_{a}'] = main[f'full_{a}'].to_numpy(float)
        scores['libyear_score'] = test.libyear.to_numpy(float)
        scores[RULE] = np.array([float(ex.prior_count(idx, p, origin)) for p in test.package])
        y = test.label.to_numpy(int); ones = np.ones(len(test)); plans = {k: plan(v) for k, v in scores.items()}
        pm = {}
        for name, s in scores.items():
            for q in budgets:
                r = stats(y, ones, plans[name], q); pm[(name, q)] = r
                points.append({'origin': origin, 'model': name, 'budget_fraction': q, 'roc_auc': float(roc_auc_score(y, s)), **r})
            assert abs(pm[(name, budgets[0])]['ap'] - average_precision_score(y, s)) < 1e-10
        # Paired package-cluster bootstrap of differences (AP and Recall@K).
        contrasts = [(f'disjoint_full_{a}', b) for a in factories for b in (f'seen_full_{a}', 'libyear_score', RULE, f'disjoint_drop_libyear_{a}')] \
            + [(f'disjoint_full_{a}', 'disjoint_libyear_only_lr') for a in factories]
        pn, pc = np.unique(test.package, return_inverse=True); rng = np.random.default_rng(cfg['seed'])
        draws = {(a, b, m): [] for a, b in contrasts for m in ['ap'] + [f'recall@{q}' for q in budgets]}
        for _ in range(cfg['bootstrap_repeats']):
            w = np.bincount(rng.integers(0, len(pn), len(pn)), minlength=len(pn))[pc].astype(float)
            if not (w @ y) or not (w @ (1 - y)): continue
            cache = {}
            for name in {n for c in contrasts for n in c}:
                cache[name] = {q: stats(y, w, plans[name], q) for q in budgets}
            for a, b in contrasts:
                draws[(a, b, 'ap')].append(cache[a][budgets[0]]['ap'] - cache[b][budgets[0]]['ap'])
                for q in budgets: draws[(a, b, f'recall@{q}')].append(cache[a][q]['recall'] - cache[b][q]['recall'])
        for (a, b, m), v in draws.items():
            assert len(v) >= cfg['bootstrap_repeats'] * .9
            q = budgets[0] if m == 'ap' else float(m.split('@')[1]); key = 'ap' if m == 'ap' else 'recall'
            lo, hi = float(np.quantile(v, .025)), float(np.quantile(v, .975))
            intervals.append({'origin': origin, 'model_a': a, 'model_b': b, 'measure': 'delta_' + m, 'point': pm[(a, q)][key] - pm[(b, q)][key],
                              'ci_low': lo, 'ci_high': hi, 'excludes_zero': bool(lo > 0 or hi < 0), 'valid_repeats': len(v)})
        print('done', origin, flush=True)
    out = {'status': 'exploratory_post_hoc', 'created_at': datetime.now(timezone.utc).isoformat(), 'versions': versions,
           'design': {'folds': FOLDS, 'assignment': 'sha256(package) % 5 over packages of the test snapshot', 'training': 'main eligibility minus all rows of held-out packages',
                      'pooling': 'scores of the 5 group models pooled into one ranking per origin', 'budgets': budgets, 'tie_policy': follow['tie_policy'],
                      'bootstrap': {'unit': 'package', 'repeats': cfg['bootstrap_repeats'], 'seed': cfg['seed']}},
           'advisory_meta': adv_meta, 'folds': folds_log, 'points': points, 'intervals': intervals}
    (HERE / 'package_disjoint_results.json').write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print('saved', HERE / 'package_disjoint_results.json', flush=True)


if __name__ == '__main__':
    run()
