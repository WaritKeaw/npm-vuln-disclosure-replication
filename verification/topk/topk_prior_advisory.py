"""Top-K (Precision@K / Recall@K) for the prior-advisory rule, on the same footing as four_step budget_points.

Exploratory, post hoc (ISWA plan, advisor item 5: Top-K from existing outputs). No model is fitted.
- Rows, labels and model scores: robustness/data/date_12_paired.csv, rq_completion predictions_wide.csv,
  four_step new_scores (the exact inputs of four_step/executed_evaluate.py).
- Rule score: number of non-withdrawn reviewed npm GHSA advisories naming the package with
  published_at <= origin (verification/exposure, same definition and caches).
- Budgets, tie policy, views, bootstrap: copied from four_step/executed_evaluate.py
  (K = 1/5/10/20 %, uniform selection within the cutoff tie, package-cluster paired bootstrap,
  1,000 resamples, seed 42), extended from the focal 10 % budget to all four budgets.
Run with the bundled Python 3.12:  & $py verification\\topk\\topk_prior_advisory.py
Writes only into verification/topk/.
"""
from pathlib import Path
from datetime import datetime, timezone
import json, math, sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
P = ROOT / 'publication'; O = P / 'experiments/four_step'
sys.path[:0] = [str(P / 'tools/vendor'), str(ROOT / 'tools/vendor'), str(ROOT / 'verification/exposure')]
import exposure_analysis as ex  # noqa: E402  (advisory_index, prior_count; no network on import)

RULE = 'prior_advisory_rule'
MODELS = ['full_lr', 'full_rf', 'full_xgb']
REPRO = MODELS + ['libyear_score', 'libyear_gt_1.0', 'libyear_only_lr']


def load(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


def run():
    import numpy as np, pandas as pd
    from sklearn.metrics import average_precision_score
    cfg = load(P / 'protocol/four_step_followup.json'); base = load(P / 'protocol/rq_completion.json')

    # ------------------------------------------------ copied from four_step/executed_evaluate.py
    def plan(s):
        levels, codes = np.unique(s, return_inverse=True); return len(levels) - 1 - codes, len(levels)

    def stats(y, w, pl, budget):
        codes, n = pl; pos = np.bincount(codes, weights=w * y, minlength=n); counts = np.bincount(codes, weights=w, minlength=n); cp = np.cumsum(pos); ct = np.cumsum(counts); total = counts.sum(); positive = pos.sum()
        if total == 0: return None
        ap = float((np.divide(cp, ct, out=np.zeros(n), where=ct > 0) * pos).sum() / positive) if positive else None
        k = min(int(round(total)), max(1, math.ceil(total * budget - 1e-10))); index = int(np.searchsorted(ct, k, side='left')); before = ct[index - 1] if index else 0.; ph = cp[index - 1] if index else 0.
        assert counts[index] > 0
        hits = float(ph + (k - before) * pos[index] / counts[index]); assert -1e-8 <= hits <= k + 1e-8
        return {'ap': ap, 'n': float(total), 'positive': float(positive), 'budget_n': k, 'hits': hits, 'precision': hits / k, 'recall': hits / positive if positive else None, 'lift': hits / (k * positive / total) if positive else None, 'selected_label_zero': k - hits, 'missed_positives': positive - hits, 'cutoff_tie_weight': float(counts[index]), 'cutoff_slots': float(k - before)}
    rng = np.random.default_rng(19)
    for _ in range(12):
        y = rng.integers(0, 2, 50); s = rng.choice([.1, .2, .7], 50); w = rng.integers(0, 4, 50)
        if w @ y: assert abs(stats(y, w, plan(s), .1)['ap'] - average_precision_score(y, s, sample_weight=w)) < 1e-12
    # ------------------------------------------------

    ref = {(r['origin'], r['view'], r['model'], r['budget_fraction']): r for r in load(O / 'budget_points.json')}
    idx, adv_meta = ex.advisory_index()
    primary = pd.read_csv(ROOT / 'robustness/data/date_12_paired.csv', keep_default_na=False)
    points = []; intervals = []; repro_diff = 0.0; repro_n = 0; rule_profile = {}
    for origin in base['origins'][1:]:
        frame = primary[primary.origin == origin].reset_index(drop=True)
        pred = pd.read_csv(P / 'experiments/rq_completion' / origin / 'predictions_wide.csv', keep_default_na=False); extra = pd.read_csv(O / 'new_scores' / (origin + '.csv'), keep_default_na=False)
        keys = ['origin', 'project', 'package', 'dependency_type', 'used_version', 'label']; assert frame[keys].equals(pred[keys]) and frame[keys].equals(extra[keys])
        for name in REPRO: frame[name] = (extra if name in extra else pred)[name]
        frame[RULE] = [float(ex.prior_count(idx, p, origin)) for p in frame.package]
        names = REPRO + [RULE]
        y = frame.label.to_numpy(int); plans = {name: plan(frame[name].to_numpy(float)) for name in names}
        unique = (~frame.duplicated(['package', 'used_version'])).to_numpy(float)
        rule_profile[origin] = {'distinct_scores': int(plans[RULE][1]), 'rows_with_prior_advisory': int((frame[RULE] > 0).sum()), 'rows': int(len(frame)),
                                'positives_with_prior_advisory': int(((frame[RULE] > 0) & (frame.label == 1)).sum()), 'positives': int(y.sum())}
        pointmap = {}
        for view, weights in [('instance', np.ones(len(frame))), ('unique_package_version_origin', unique)]:
            for name in names:
                for q in cfg['budgets']:
                    row = stats(y, weights, plans[name], q); pointmap[(view, name, q)] = row
                    if name == RULE:
                        points.append({'origin': origin, 'view': view, 'model': name, 'budget_fraction': q, **row})
                    else:
                        r0 = ref[(origin, view, name, q)]
                        d = max(abs(row[k] - r0[k]) for k in ['ap', 'hits', 'precision', 'recall', 'budget_n']); repro_diff = max(repro_diff, d); repro_n += 1
        # Package-cluster paired bootstrap, all budgets (four_step used the same unit/seed at the focal budget only).
        pn, pc = np.unique(frame.package, return_inverse=True)
        for view in ['instance', 'unique_package_version_origin']:
            rng = np.random.default_rng(cfg['seed']); draws = {(m, q): {k: [] for k in ['precision', 'recall']} for m in MODELS for q in cfg['budgets']}
            for _ in range(cfg['bootstrap_repeats']):
                w = np.bincount(rng.integers(0, len(pn), len(pn)), minlength=len(pn))[pc].astype(float)
                if view == 'unique_package_version_origin': w = w * unique
                if not (w @ y) or not (w @ (1 - y)): continue
                for q in cfg['budgets']:
                    b = stats(y, w, plans[RULE], q)
                    for m in MODELS:
                        a = stats(y, w, plans[m], q)
                        for k in draws[(m, q)]: draws[(m, q)][k].append(a[k] - b[k])
            for (m, q), measures in draws.items():
                for k, values in measures.items():
                    assert len(values) >= cfg['bootstrap_repeats'] * .9
                    lo, hi = float(np.quantile(values, .025)), float(np.quantile(values, .975))
                    intervals.append({'origin': origin, 'view': view, 'cluster_unit': 'package', 'model_a': m, 'model_b': RULE, 'budget_fraction': q, 'measure': 'delta_' + k,
                                      'point': pointmap[(view, m, q)][k] - pointmap[(view, RULE, q)][k], 'ci_low': lo, 'ci_high': hi, 'excludes_zero': bool(lo > 0 or hi < 0), 'valid_repeats': len(values)})
        print('done', origin, flush=True)
    assert repro_diff < 1e-12, repro_diff
    out = {'status': 'exploratory_post_hoc', 'created_at': datetime.now(timezone.utc).isoformat(),
           'definition': 'prior_advisory_rule = count of non-withdrawn reviewed npm GHSA advisories naming the package, published_at <= origin 23:59:59.999Z (verification/exposure)',
           'advisory_meta': adv_meta, 'budgets': cfg['budgets'], 'tie_policy': cfg['tie_policy'], 'bootstrap': {'unit': 'package', 'repeats': cfg['bootstrap_repeats'], 'seed': cfg['seed']},
           'reproduction': {'models_checked': REPRO, 'points_checked': repro_n, 'max_abs_diff_vs_four_step_budget_points': repro_diff},
           'rule_profile': rule_profile, 'rule_points': points, 'intervals_model_minus_rule': intervals}
    (HERE / 'topk_results.json').write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    print('reproduction max abs diff', repro_diff, 'over', repro_n, 'points', flush=True)


if __name__ == '__main__':
    run()
