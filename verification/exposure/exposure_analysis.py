"""F-2 exposure analysis (exploratory, post hoc): do point-in-time exposure covariates
(npm downloads, prior GHSA advisories) change the main conclusions?

Run with the pipeline's bundled Python 3.12 (same numpy/pandas/sklearn/xgboost as rq_completion):
  python verification/exposure/fetch_exposure.py all      # once; network; cached
  python verification/exposure/exposure_analysis.py        # offline from cache
Writes only into verification/exposure/.
Models, preprocessing, training-window rule, metrics and bootstrap are copied from
publication/experiments/rq_completion/executed_source.py (unchanged parameters, seed 42).
"""
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
import json, math, sys, glob

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / 'publication/tools/vendor'), str(ROOT / 'tools/vendor')]
sys.path.insert(0, str(HERE))
import fetch_exposure as fx  # noqa: E402

SRC = ROOT / 'publication/experiments/rq_completion'
CFG = json.loads((SRC / 'executed_config.json').read_text(encoding='utf-8'))
FEATURES = CFG['features']
LAG = ['libyear', 'major_versions_behind', 'minor_versions_behind', 'patch_versions_behind']
EXP = ['log_downloads_365d', 'prior_advisories']
GAP_RUN_DAYS = 14        # a run of >=14 consecutive zero days after the package existed = API history gap
MIN_OBSERVED_DAYS = 30   # fewer observed (non-gap, post-creation) days -> downloads treated as missing


# ---------------------------------------------------------------- copied from executed_source.py
def score_plan(scores):
    import numpy as np
    levels, codes = np.unique(scores, return_inverse=True)
    return len(levels) - 1 - codes, len(levels)


def fast_ap(y, w, plan):
    import numpy as np
    codes, n = plan; pos = np.bincount(codes, weights=w * y, minlength=n); total = np.bincount(codes, weights=w, minlength=n)
    cp = np.cumsum(pos); ct = np.cumsum(total)
    return float((np.divide(cp, ct, out=np.zeros(n), where=ct > 0) * pos).sum() / pos.sum())
# ---------------------------------------------------------------------------------------------


def fast_auc(y, w, plan):
    """Weighted ROC-AUC with ties counted 1/2 (equals sklearn roc_auc_score with sample_weight)."""
    import numpy as np
    codes, n = plan  # code 0 = highest score
    pos = np.bincount(codes, weights=w * y, minlength=n); neg = np.bincount(codes, weights=w * (1 - y), minlength=n)
    neg_below = neg[::-1].cumsum()[::-1] - neg  # negatives with strictly lower score (higher code)
    return float((pos * (neg_below + 0.5 * neg)).sum() / (pos.sum() * neg.sum()))


def expected_recall_at_budget(y, s, frac):
    """Recall at ceil(n*frac) under uniformly random tie-breaking (expected value)."""
    import numpy as np
    k = math.ceil(len(y) * frac); levels, codes = np.unique(-s, return_inverse=True)
    size = np.bincount(codes); pos = np.bincount(codes, weights=y)
    taken = 0; hits = 0.0
    for c in range(len(levels)):
        if taken + size[c] <= k:
            taken += size[c]; hits += pos[c]
        else:
            hits += pos[c] * (k - taken) / size[c]; break
    return hits / y.sum()


def load_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8'))


# ---------------------------------------------------------------- covariates
def creation_dates():
    out = {}
    for f in (ROOT / 'cache/npm').glob('*.json'):
        p = load_json(f)
        ds = [v for k, v in p['times'].items() if k not in ('created', 'modified') and isinstance(v, str)]
        ds = [datetime.fromisoformat(d.replace('Z', '+00:00')).date() for d in ds if d]
        if ds:
            out[p['package']] = min(ds)
    return out


def downloads_table(packages, created):
    rows = []
    for origin in fx.ORIGINS:
        start, end = (date.fromisoformat(x) for x in fx.window(origin))
        for p in packages:
            f = fx.cache_file(origin, p)
            rec = {'origin': origin, 'package': p}
            if not f.exists():
                raise SystemExit(f'missing download cache {origin} {p}; run fetch_exposure.py downloads')
            c = load_json(f); r = c['response']
            ok = isinstance(r, dict) and isinstance(r.get('downloads'), list)
            if not ok:
                rec.update(api_status='not_found', raw_sum=math.nan, observed_days=0, gap_days=0, eligible_days=0)
                rows.append(rec); continue
            daily = {d['day']: d['downloads'] for d in r['downloads']}
            days = [start + timedelta(days=i) for i in range(365)]
            vals = [daily.get(d.isoformat(), 0) for d in days]
            first = created.get(p)
            elig = [first is None or d >= first for d in days]
            # zero runs (on eligible days) of length >= GAP_RUN_DAYS are treated as API history gaps
            gap = [False] * 365; i = 0
            while i < 365:
                if elig[i] and vals[i] == 0:
                    j = i
                    while j < 365 and elig[j] and vals[j] == 0:
                        j += 1
                    if j - i >= GAP_RUN_DAYS:
                        for t in range(i, j):
                            gap[t] = True
                    i = j
                else:
                    i += 1
            obs = [elig[t] and not gap[t] for t in range(365)]
            raw = sum(vals); obs_sum = sum(v for v, o in zip(vals, obs) if o); nobs = sum(obs)
            rec.update(api_status='ok', raw_sum=raw, observed_days=nobs, gap_days=sum(gap), eligible_days=sum(elig),
                       annualised=(obs_sum * 365 / nobs) if nobs >= MIN_OBSERVED_DAYS else math.nan)
            rows.append(rec)
    import pandas as pd
    t = pd.DataFrame(rows)
    t['log_downloads_365d'] = __import__('numpy').log1p(t['annualised'])
    t['log_downloads_raw'] = __import__('numpy').log1p(t['raw_sum'])
    return t


def advisory_index():
    """Non-withdrawn reviewed npm advisories: package -> list of published datetimes (deduplicated by GHSA id)."""
    seen = {}
    for f in [ROOT / 'cache/ghsa/advisories.json', HERE / 'cache/ghsa_pre2021/advisories.json']:
        for a in load_json(f):
            seen[a['ghsa_id']] = a
    idx = {}; withdrawn = 0
    for a in seen.values():
        if a.get('withdrawn_at'):
            withdrawn += 1; continue
        pub = datetime.fromisoformat(a['published_at'].replace('Z', '+00:00'))
        for name in {v['package']['name'] for v in a.get('vulnerabilities') or [] if v['package']['ecosystem'] == 'npm'}:
            idx.setdefault(name, []).append(pub)
    return idx, {'advisories_total': len(seen), 'withdrawn_excluded': withdrawn}


def prior_count(idx, package, origin):
    cut = datetime.fromisoformat(origin + 'T23:59:59.999+00:00')  # same boundary as semver_batch.cjs
    return sum(1 for d in idx.get(package, []) if d <= cut)


# ---------------------------------------------------------------- models
def factories():
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier
    m = CFG['models']
    return {'lr': lambda: LogisticRegression(**m['lr']), 'rf': lambda: RandomForestClassifier(**m['rf']), 'xgb': lambda: XGBClassifier(**m['xgb'])}


def specs():
    no_lib = [f for f in FEATURES if f != 'libyear']
    return {
        'full9': FEATURES,
        'drop_libyear9': no_lib,  # = rq_completion drop_libyear_* (bootstrap reproduction check)
        'full_exp': FEATURES + EXP,
        'full_exp_minus_libyear': no_lib + EXP,
        'full_exp_minus_lag': [f for f in FEATURES if f not in LAG] + EXP,
        'exp_only': EXP,
        'full9_plus_downloads': FEATURES + ['log_downloads_365d'],
        'full9_plus_prior': FEATURES + ['prior_advisories'],
        # sensitivity: uncorrected downloads (raw 365-day sum incl. API zero gaps; not-found = 0)
        'full_exp_rawdl': FEATURES + ['log_downloads_raw0', 'prior_advisories'],
    }


def metric_row(y, s, name, origin, kind, train=None):
    import numpy as np
    from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
    k = math.ceil(len(y) * CFG['inspection_budget_fraction']); top = np.argsort(-s, kind='stable')[:k]
    row = {'origin': origin, 'model': name, 'kind': kind, 'test_n': int(len(y)), 'positive': int(y.sum()), 'prevalence': float(y.mean()),
           'ap': float(average_precision_score(y, s)), 'roc_auc': float(roc_auc_score(y, s)),
           'recall_at_10pct_stable': float(y[top].sum() / y.sum()), 'recall_at_10pct_expected_ties': float(expected_recall_at_budget(y, s, CFG['inspection_budget_fraction'])),
           'distinct_scores': int(len(np.unique(s)))}
    row['brier'] = float(brier_score_loss(y, s)) if kind == 'model' else None
    if train is not None:
        row['train_n'] = int(len(train))
    return row


def bootstrap(frame, scores, pairs, unit='package'):
    """Paired package-cluster bootstrap identical in RNG use to executed_source.intervals(), plus ΔAUC."""
    import numpy as np
    y = frame.label.to_numpy(int); names, codes = np.unique(frame[unit], return_inverse=True)
    rng = np.random.default_rng(CFG['seed']); plans = {n: score_plan(s) for n, s in scores.items()}
    need = sorted({n for p in pairs for n in p})
    samp = {p: {'ap': [], 'auc': []} for p in pairs}
    for _ in range(CFG['bootstrap_repeats']):
        counts = np.bincount(rng.integers(0, len(names), len(names)), minlength=len(names)); w = counts[codes]
        if not (w @ y) or not (w @ (1 - y)):
            continue
        ap = {n: fast_ap(y, w, plans[n]) for n in need}; auc = {n: fast_auc(y, w, plans[n]) for n in need}
        for a, b in pairs:
            samp[(a, b)]['ap'].append(ap[a] - ap[b]); samp[(a, b)]['auc'].append(auc[a] - auc[b])
    ones = np.ones(len(y))
    out = []
    for (a, b), v in samp.items():
        out.append({'model_a': a, 'model_b': b, 'cluster_unit': unit, 'valid_repeats': len(v['ap']),
                    'delta_ap': fast_ap(y, ones, plans[a]) - fast_ap(y, ones, plans[b]),
                    'delta_ap_ci_low': float(np.quantile(v['ap'], .025)), 'delta_ap_ci_high': float(np.quantile(v['ap'], .975)),
                    'delta_auc': fast_auc(y, ones, plans[a]) - fast_auc(y, ones, plans[b]),
                    'delta_auc_ci_low': float(np.quantile(v['auc'], .025)), 'delta_auc_ci_high': float(np.quantile(v['auc'], .975))})
    return out


def run():
    import numpy as np, pandas as pd, sklearn, xgboost, scipy
    from scipy.stats import spearmanr
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    assert xgboost.__version__ == '3.0.5'
    frame = pd.read_csv(ROOT / 'robustness/data/date_12_paired.csv', keep_default_na=False)  # exact input of rq_completion
    packages = sorted(frame.package.unique())

    created = creation_dates()
    dl = downloads_table(packages, created)
    idx, adv_meta = advisory_index()
    frame = frame.merge(dl[['origin', 'package', 'log_downloads_365d', 'log_downloads_raw', 'api_status', 'gap_days', 'observed_days']], on=['origin', 'package'], how='left', validate='many_to_one')
    frame['log_downloads_raw0'] = frame['log_downloads_raw'].fillna(0.0)
    frame['prior_advisories'] = [prior_count(idx, p, o) for p, o in zip(frame.package, frame.origin)]

    # coverage
    coverage = {}
    for origin in fx.ORIGINS:
        f = frame[frame.origin == origin]; d = dl[(dl.origin == origin) & dl.package.isin(set(f.package))]  # packages present at this origin
        coverage[origin] = {
            'packages': int(len(d)), 'not_found_in_api': int((d.api_status == 'not_found').sum()),
            'packages_with_gap_days': int((d.gap_days > 0).sum()),
            'packages_all_zero_raw': int(((d.raw_sum == 0) & (d.api_status == 'ok')).sum()),
            'packages_missing_after_gap_rule': int(d.log_downloads_365d.isna().sum()),
            'instances': int(len(f)), 'instances_missing_downloads': int(f.log_downloads_365d.isna().sum()),
            'positives_missing_downloads': int(f[f.label == 1].log_downloads_365d.isna().sum()),
            'packages_no_creation_date': int(sum(p not in created for p in d.package)),
            'instances_prior_advisories_gt0': int((f.prior_advisories > 0).sum()),
            'packages_prior_advisories_gt0': int(f[f.prior_advisories > 0].package.nunique()),
        }
    gap_examples = dl[dl.gap_days > 0].sort_values('raw_sum', ascending=False).head(15)[['origin', 'package', 'raw_sum', 'gap_days', 'observed_days']].to_dict('records')
    notfound = sorted(dl[dl.api_status == 'not_found'].package.unique().tolist())

    # reproduction reference
    ref = {(r['origin'], r['model']): r for r in load_json(SRC / 'metrics.json')}
    ref_int = load_json(SRC / 'intervals.json')

    facts = factories(); sp = specs()
    allmetrics = []; allci = []; repro = []; corr = []; coefs = []
    for origin in CFG['origins'][1:]:
        test = frame[frame.origin == origin].copy(); train = frame[(frame.origin < origin) & (frame.window_end <= origin)].copy()
        assert train.origin.max() < origin and train.window_end.max() <= origin
        y = test.label.to_numpy(int); scores = {}
        for alg, fac in facts.items():
            for sname, cols in sp.items():
                name = f'{sname}_{alg}'
                model = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), fac())
                model.fit(train[cols], train.label)
                scores[name] = model.predict_proba(test[cols])[:, 1]
                if sname == 'full_exp':
                    clf = model.steps[-1][1]
                    vals = clf.coef_[0] if alg == 'lr' else clf.feature_importances_
                    coefs += [{'origin': origin, 'algorithm': alg, 'feature': c, 'value': float(v), 'type': 'standardized_coefficient' if alg == 'lr' else ('impurity_importance' if alg == 'rf' else 'normalized_gain')} for c, v in zip(cols, vals)]
                allmetrics.append(metric_row(y, scores[name], name, origin, 'model', train))
                print('fit', origin, name, round(allmetrics[-1]['ap'], 4), round(allmetrics[-1]['roc_auc'], 4), flush=True)
        # rules (no training); missing downloads ranked lowest for the downloads rule
        rules = {'rule_prior_advisories': test.prior_advisories.to_numpy(float),
                 'rule_log_downloads': np.nan_to_num(test.log_downloads_365d.to_numpy(float), nan=-1.0),
                 'rule_libyear_score': test.libyear.to_numpy(float)}
        for t in CFG['threshold_baseline_years']:
            rules[f'rule_libyear_gt_{t}'] = (test.libyear.to_numpy() > t).astype(float)
        for name, s in rules.items():
            scores[name] = s; allmetrics.append(metric_row(y, s, name, origin, 'rule'))
        # reproduction check
        for alg in facts:
            for mine, theirs in [(f'full9_{alg}', f'full_{alg}'), (f'drop_libyear9_{alg}', f'drop_libyear_{alg}')]:
                m = next(r for r in allmetrics if r['origin'] == origin and r['model'] == mine); r0 = ref[(origin, theirs)]
                repro.append({'origin': origin, 'model': theirs, 'ap_ref': r0['ap'], 'ap_new': m['ap'], 'auc_ref': r0['roc_auc'], 'auc_new': m['roc_auc'],
                              'recall_ref': r0['recall_at_budget'], 'recall_new': m['recall_at_10pct_stable'], 'brier_ref': r0['brier'], 'brier_new': m['brier'],
                              'max_abs_diff': max(abs(r0['ap'] - m['ap']), abs(r0['roc_auc'] - m['roc_auc']), abs(r0['recall_at_budget'] - m['recall_at_10pct_stable']), abs(r0['brier'] - m['brier']))})
        # bootstrap
        pairs = []
        for alg in facts:
            pairs += [(f'full_exp_{alg}', f'full9_{alg}'), (f'full_exp_{alg}', f'full_exp_minus_libyear_{alg}'),
                      (f'full_exp_{alg}', f'full_exp_minus_lag_{alg}'), (f'full_exp_{alg}', f'exp_only_{alg}'),
                      (f'full_exp_{alg}', 'rule_prior_advisories'), (f'full_exp_{alg}', 'rule_log_downloads'),
                      (f'full_exp_{alg}', 'rule_libyear_score'),
                      (f'full9_{alg}', 'rule_prior_advisories'), (f'full9_{alg}', 'rule_log_downloads'),
                      (f'full9_{alg}', f'drop_libyear9_{alg}')]  # last one reproduces rq_completion interval
        ci = bootstrap(test, scores, pairs)
        for r in ci:
            r['origin'] = origin
            if r['model_b'].startswith('drop_libyear9_'):
                alg = r['model_b'].rsplit('_', 1)[1]
                r0 = next(x for x in ref_int if x['origin'] == origin and x['cluster_unit'] == 'package' and x['model_a'] == f'full_{alg}' and x['model_b'] == f'drop_libyear_{alg}')
                r['reproduces_rq_completion_ci'] = abs(r0['ci_low'] - r['delta_ap_ci_low']) < 1e-10 and abs(r0['ci_high'] - r['delta_ap_ci_high']) < 1e-10
        allci += ci
        print('bootstrap', origin, 'done', flush=True)
        # correlations on test rows (complete cases for downloads)
        tc = test.dropna(subset=['log_downloads_365d'])
        for other in ['package_age', 'days_since_latest_release', 'total_versions', 'prior_advisories', 'libyear']:
            rho, pval = spearmanr(tc.log_downloads_365d, tc[other])
            corr.append({'origin': origin, 'x': 'log_downloads_365d', 'y': other, 'level': 'instance', 'n': int(len(tc)), 'spearman_rho': float(rho)})
        pk = tc.drop_duplicates('package')
        for other in ['package_age', 'days_since_latest_release', 'total_versions', 'prior_advisories']:
            rho, _ = spearmanr(pk.log_downloads_365d, pk[other])
            corr.append({'origin': origin, 'x': 'log_downloads_365d', 'y': other, 'level': 'package', 'n': int(len(pk)), 'spearman_rho': float(rho)})
        q90 = tc.log_downloads_365d.quantile(.9); top = tc.log_downloads_365d >= q90
        corr.append({'origin': origin, 'x': 'top_download_decile', 'level': 'instance', 'threshold_log_downloads': float(q90),
                     'share_of_test_rows': float(top.mean()), 'share_of_positives': float(tc[top].label.sum() / tc.label.sum()),
                     'prevalence_in_top_decile': float(tc[top].label.mean()), 'prevalence_rest': float(tc[~top].label.mean()),
                     'positives_with_prior_advisory_gt0_share': float((test[test.label == 1].prior_advisories > 0).mean()),
                     'prevalence_prior_gt0': float(test[test.prior_advisories > 0].label.mean()) if (test.prior_advisories > 0).any() else None,
                     'prevalence_prior_eq0': float(test[test.prior_advisories == 0].label.mean())})

    result = {
        'status': 'exploratory_post_hoc_reviewer_F2', 'created_at': datetime.now(timezone.utc).isoformat(),
        'versions': {'python': sys.version, 'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__, 'scipy': scipy.__version__, 'xgboost': xgboost.__version__},
        'data': str(Path('robustness/data/date_12_paired.csv')), 'features': FEATURES, 'exposure': EXP, 'lag_family': LAG,
        'gap_rule': {'zero_run_days': GAP_RUN_DAYS, 'min_observed_days': MIN_OBSERVED_DAYS, 'creation_date': 'earliest version timestamp in cache/npm'},
        'advisories': adv_meta, 'downloads_coverage': coverage, 'downloads_not_found_packages': notfound, 'gap_examples': gap_examples,
        'reproduction': {'max_abs_diff': max(r['max_abs_diff'] for r in repro), 'rows': repro,
                         'bootstrap_ci_reproduced': all(r.get('reproduces_rq_completion_ci', True) for r in allci)},
        'metrics': allmetrics, 'intervals_package_cluster': allci, 'correlations': corr, 'full_exp_native': coefs,
    }
    (HERE / 'exposure_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float), encoding='utf-8')
    dl.to_csv(HERE / 'downloads_by_origin_package.csv', index=False)
    print('reproduction max abs diff', result['reproduction']['max_abs_diff'], 'ci reproduced', result['reproduction']['bootstrap_ci_reproduced'], flush=True)


if __name__ == '__main__':
    run()
