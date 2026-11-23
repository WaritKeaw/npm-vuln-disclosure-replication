"""Analyses requested by review round 3 (exploratory, post-bug-fix data, 2026-10-24).

Tasks (review finding ids): F-3 NVD-before-origin, F-22 severity, F-19 multiplicity, F-11 lockfile
difference intervals, F-14 semver-ordered versions-behind availability, F-23 seeds, F-20 PIT shifts,
F-24 no-history packages seen in training.

Protocol reused from publication/experiments/rq_completion/executed_source.py (fixed parameters,
expanding-window backtest, seed 42, package-cluster bootstrap 1,000 with the same weighting scheme).
Inputs are read-only. Output: verification/round3/round3_results.json (unrounded).
Run:  PYTHONIOENCODING=utf-8 python verification/round3/round3_analyses.py
"""
from pathlib import Path
import importlib.util, json, math, sys
R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / 'publication/tools/vendor'))  # XGBoost 3.0.5 as in the main run (tools/vendor holds cp312 wheels; not used)
import numpy as np, pandas as pd
import sklearn, xgboost
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import average_precision_score as AP, roc_auc_score as AUC
from xgboost import XGBClassifier

RQ = R / 'publication/experiments/rq_completion'
LOCK = R / 'publication/experiments/lockfile_sensitivity'
OUT = R / 'verification/round3'
spec = importlib.util.spec_from_file_location('rq_executed', RQ / 'executed_source.py')
EX = importlib.util.module_from_spec(spec); spec.loader.exec_module(EX)   # top level only defines paths/functions
score_plan, fast_ap = EX.score_plan, EX.fast_ap
CFG = json.loads((RQ / 'executed_config.json').read_text(encoding='utf-8'))
FEAT = CFG['features']; ORG = CFG['origins'][1:]; SNAP = CFG['origins']; SEED = CFG['seed']; B = CFG['bootstrap_repeats']
DATA = pd.read_csv(R / 'robustness/data/date_12_paired.csv', keep_default_na=False)   # same file as executed_source.py
REF = {(r['origin'], r['model']): r for r in json.loads((RQ / 'metrics.json').read_text(encoding='utf-8'))}
ADV = {a['ghsa_id']: a for a in json.loads((R / 'cache/ghsa/advisories.json').read_text(encoding='utf-8'))}
res = {'meta': {'sklearn': sklearn.__version__, 'xgboost': xgboost.__version__, 'numpy': np.__version__, 'pandas': pd.__version__,
                'data': 'robustness/data/date_12_paired.csv', 'rows': int(len(DATA)), 'seed': SEED, 'bootstrap_repeats': B,
                'recall10': 'stable descending order, top ceil(0.1 n) as executed_source.py; recall10_expected = tie-aware expectation'}}

# ---------------------------------------------------------------- helpers
def model(alg, seed=None):
    params = dict(CFG['models'][alg])
    if seed is not None and alg != 'lr': params['random_state'] = seed
    clf = {'lr': LogisticRegression, 'rf': RandomForestClassifier, 'xgb': XGBClassifier}[alg](**params)
    return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), clf)

def recall10(y, s):
    k = math.ceil(len(y) * CFG['inspection_budget_fraction']); top = np.argsort(-s, kind='stable')[:k]; return float(y[top].sum() / y.sum())

def recall10_expected(y, s):
    k = math.ceil(len(y) * CFG['inspection_budget_fraction']); o = np.argsort(-s, kind='stable'); ss, yy = s[o], y[o]; thr = ss[k - 1]
    above = ss > thr; tie = ss == thr
    return float((yy[above].sum() + (k - above.sum()) * yy[tie].mean()) / y.sum())

def metrics(y, s):
    return {'ap': float(AP(y, s)), 'roc_auc': float(AUC(y, s)), 'recall10': recall10(y, s), 'recall10_expected': recall10_expected(y, s)}

def fast_auc(y, w, plan):
    """Weighted ROC-AUC with ties counted 1/2 (codes: 0 = highest score)."""
    codes, n = plan
    pos = np.bincount(codes, weights=w * y, minlength=n); neg = np.bincount(codes, weights=w * (1 - y), minlength=n)
    below = neg.sum() - np.cumsum(neg)
    return float((pos * (below + .5 * neg)).sum() / (pos.sum() * neg.sum()))

def selfcheck():
    rng = np.random.default_rng(47)
    for _ in range(20):
        y = rng.integers(0, 2, 60); s = rng.choice([.1, .3, .5, .8], 60); w = rng.integers(0, 4, 60).astype(float)
        if w @ y and w @ (1 - y):
            assert math.isclose(fast_auc(y, w, score_plan(s)), AUC(y, s, sample_weight=w), abs_tol=1e-12)
            assert math.isclose(fast_ap(y, w, score_plan(s)), AP(y, s, sample_weight=w), abs_tol=1e-12)
selfcheck()

def boot_weights(frame, unit='package', seed=SEED, reps=B):
    """Yield weight vectors exactly as executed_source.intervals (np.unique cluster order, bincount weights)."""
    names, codes = np.unique(frame[unit], return_inverse=True); rng = np.random.default_rng(seed)
    for _ in range(reps):
        yield np.bincount(rng.integers(0, len(names), len(names)), minlength=len(names))[codes].astype(float)

def p_boot(v):
    v = np.asarray(v); n = len(v)
    raw = min(1., 2 * min((v <= 0).mean(), (v >= 0).mean()))
    plus1 = min(1., 2 * min(((v <= 0).sum() + 1) / (n + 1), ((v >= 0).sum() + 1) / (n + 1)))
    return raw, plus1

def holm(ps):
    ps = np.asarray(ps, float); m = len(ps); order = np.argsort(ps); adj = np.empty(m); running = 0.
    for rank, i in enumerate(order):
        running = max(running, min(1., (m - rank) * ps[i])); adj[i] = running
    return adj

def backtest(frame, specs, rules=('libyear_gt_1.0',), origins=ORG, keep_scores=False, seed=None):
    out = {}; scores_all = {}
    for o in origins:
        te = frame[frame.origin == o]; tr = frame[(frame.origin < o) & (frame.window_end <= o)]
        assert tr.origin.max() < o and tr.window_end.max() <= o
        y = te.label.to_numpy(int); scores = {}
        for name, (alg, cols) in specs.items():
            scores[name] = model(alg, seed).fit(tr[cols], tr.label).predict_proba(te[cols])[:, 1]
        for r in rules: scores[r] = (te.libyear.to_numpy() > float(r.split('_')[-1])).astype(float)
        out[o] = {'train_n': int(len(tr)), 'train_pos': int(tr.label.sum()), 'test_n': int(len(te)), 'test_pos': int(y.sum()),
                  'prevalence': float(y.mean()), 'models': {n: metrics(y, s) for n, s in scores.items()}}
        if keep_scores: scores_all[o] = (te, scores)
    return (out, scores_all) if keep_scores else out

ALGS = ('lr', 'rf', 'xgb')
SPECS = {**{f'full_{a}': (a, FEAT) for a in ALGS}, **{f'drop_libyear_{a}': (a, [f for f in FEAT if f != 'libyear']) for a in ALGS},
         'libyear_only_lr': ('lr', ['libyear'])}
MODELS = list(SPECS) + ['libyear_gt_1.0']

# ---------------------------------------------------------------- 0. reproduce main metrics
main = backtest(DATA, SPECS)
repro = {}
for o in ORG:
    for m in MODELS:
        ref = REF[(o, m)]; now = main[o]['models'][m]
        repro[f'{o}:{m}'] = {'ap_ref': ref['ap'], 'ap_now': now['ap'], 'auc_ref': ref['roc_auc'], 'auc_now': now['roc_auc'],
                             'recall_ref': ref['recall_at_budget'], 'recall_now': now['recall10']}
        assert abs(ref['ap'] - now['ap']) < 5e-5 and abs(ref['roc_auc'] - now['roc_auc']) < 5e-5 and abs(ref['recall_at_budget'] - now['recall10']) < 1e-9, (o, m)
res['reproduction'] = {'max_abs_ap_diff': max(abs(v['ap_ref'] - v['ap_now']) for v in repro.values()),
                       'max_abs_auc_diff': max(abs(v['auc_ref'] - v['auc_now']) for v in repro.values()), 'rows': repro}
res['main'] = main
print('Reproduced main metrics; max |dAP| =', res['reproduction']['max_abs_ap_diff'], flush=True)

# ---------------------------------------------------------------- advisory attributes per row
def ids(s): return [x for x in str(s).split(';') if x]
missing = sorted({g for s in DATA.matched_ghsa_ids for g in ids(s) if g not in ADV}); assert not missing, missing[:5]
end_of = {o: pd.Timestamp(o + 'T23:59:59.999Z') for o in SNAP}
def nvd_pre(g, o):
    t = ADV[g].get('nvd_published_at'); return None if not t else bool(pd.Timestamp(t) <= end_of[o])
SEV_RANK = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
rows = []
for r in DATA.itertuples():
    g = ids(r.matched_ghsa_ids); pre = [nvd_pre(x, r.origin) for x in g]
    rows.append({'all_pre': bool(g) and all(p is True for p in pre), 'any_pre': any(p is True for p in pre),
                 'n_no_nvd': sum(p is None for p in pre),
                 'max_sev': max((ADV[x]['severity'] for x in g), key=lambda s: SEV_RANK[s]) if g else '',
                 'hc': any(ADV[x]['severity'] in ('high', 'critical') for x in g)})
ATT = pd.DataFrame(rows, index=DATA.index); D = pd.concat([DATA, ATT], axis=1)
assert ((D.label == 1) == (D.matched_ghsa_ids != '')).all()

# ---------------------------------------------------------------- F-3 NVD before origin
f3 = {'definition': 'pre-public = advisory nvd_published_at <= origin 23:59:59.999Z; advisories without nvd_published_at are counted as not pre-public',
      'descriptive': {}}
for o in SNAP:
    pos = D[(D.origin == o) & (D.label == 1)]
    adv = sorted({g for s in pos.matched_ghsa_ids for g in ids(s)}); pre_adv = [g for g in adv if nvd_pre(g, o) is True]
    f3['descriptive'][o] = {'positives': int(len(pos)), 'all_matched_pre_public': int(pos.all_pre.sum()), 'share_all': float(pos.all_pre.mean()),
                            'any_matched_pre_public': int(pos.any_pre.sum()), 'share_any': float(pos.any_pre.mean()),
                            'positives_with_matched_advisory_lacking_nvd_date': int((pos.n_no_nvd > 0).sum()),
                            'unique_advisories': len(adv), 'unique_advisories_pre_public': len(pre_adv),
                            'unique_advisories_without_nvd_date': sum(nvd_pre(g, o) is None for g in adv), 'pre_public_ids': pre_adv,
                            'mean_libyear': {'positives_all_pre_public': float(pos[pos.all_pre].libyear.mean()) if pos.all_pre.any() else None,
                                             'positives_any_pre_public': float(pos[pos.any_pre].libyear.mean()) if pos.any_pre.any() else None,
                                             'positives_other': float(pos[~pos.any_pre].libyear.mean()), 'negatives': float(D[(D.origin == o) & (D.label == 0)].libyear.mean())}}
variants = {'drop_all_pre_public_positives': D[~((D.label == 1) & D.all_pre)],
            'drop_any_pre_public_positives': D[~((D.label == 1) & D.any_pre)],
            'relabel0_all_pre_public_positives': D.assign(label=np.where((D.label == 1) & D.all_pre, 0, D.label))}
f3['backtests'] = {}
for name, frame in variants.items():
    f3['backtests'][name] = backtest(frame, SPECS); print('F-3', name, 'done', flush=True)
f3['primary'] = 'drop_all_pre_public_positives (rows removed from train and test); others are secondary'
res['F3_nvd_before_origin'] = f3

# ---------------------------------------------------------------- F-22 severity
f22 = {'definition': 'max severity over matched advisories (GHSA severity field; medium = moderate); outcome sensitivity label=1 iff any matched advisory is high or critical, else 0; models refit on that label',
       'distribution': {}}
for o in SNAP:
    pos = D[(D.origin == o) & (D.label == 1)]; vc = pos.max_sev.value_counts()
    adv = sorted({g for s in pos.matched_ghsa_ids for g in ids(s)}); va = pd.Series([ADV[g]['severity'] for g in adv]).value_counts()
    f22['distribution'][o] = {'positives': int(len(pos)), 'instances_by_max_severity': {k: int(vc.get(k, 0)) for k in SEV_RANK},
                              'share_by_max_severity': {k: float(vc.get(k, 0) / len(pos)) for k in SEV_RANK},
                              'unique_advisories_by_severity': {k: int(va.get(k, 0)) for k in SEV_RANK},
                              'high_critical_positives': int(pos.hc.sum()), 'prevalence_main': float(D[D.origin == o].label.mean()),
                              'prevalence_high_critical': float(D[D.origin == o].hc.mean())}
f22['backtest'] = backtest(D.assign(label=D.hc.astype(int)), SPECS)
res['F22_severity'] = f22; print('F-22 done', flush=True)

# ---------------------------------------------------------------- F-19 multiplicity (stored predictions)
fam = {'dAP_full_minus_libyear_only_lr': [], 'dAUC_full_minus_libyear_only_lr': [], 'dAP_full_minus_drop_libyear': [], 'dAP_full_minus_libyear_only_same_algorithm': []}
check_iv = {(r['origin'], r['model_a'], r['model_b']): r for r in json.loads((RQ / 'intervals.json').read_text(encoding='utf-8')) if r['cluster_unit'] == 'package'}
f19_check = {}
for o in ORG:
    pr = pd.read_csv(RQ / o / 'predictions_wide.csv', keep_default_na=False); y = pr.label.to_numpy(int)
    names = [f'full_{a}' for a in ALGS] + [f'drop_libyear_{a}' for a in ALGS] + [f'libyear_only_{a}' for a in ALGS]
    plans = {n: score_plan(pr[n].to_numpy()) for n in names}; samp = {k: [] for k in ('ap', 'auc')}
    for w in boot_weights(pr):
        if not (w @ y) or not (w @ (1 - y)): continue
        samp['ap'].append({n: fast_ap(y, w, p) for n, p in plans.items()}); samp['auc'].append({n: fast_auc(y, w, p) for n, p in plans.items()})
    for a in ALGS:
        for key, metric, b, mfun in (('dAP_full_minus_libyear_only_lr', 'ap', 'libyear_only_lr', AP), ('dAUC_full_minus_libyear_only_lr', 'auc', 'libyear_only_lr', AUC),
                                     ('dAP_full_minus_drop_libyear', 'ap', f'drop_libyear_{a}', AP), ('dAP_full_minus_libyear_only_same_algorithm', 'ap', f'libyear_only_{a}', AP)):
            v = np.array([s[f'full_{a}'] - s[b] for s in samp[metric]]); raw, p1 = p_boot(v)
            fam[key].append({'origin': o, 'algorithm': a, 'model_b': b, 'estimate': float(mfun(y, pr[f'full_{a}']) - mfun(y, pr[b])),
                             'ci_low': float(np.quantile(v, .025)), 'ci_high': float(np.quantile(v, .975)), 'valid_repeats': int(len(v)),
                             'share_le0': float((v <= 0).mean()), 'p_raw': raw, 'p': p1})
            ref = check_iv.get((o, f'full_{a}', b))
            if metric == 'ap' and ref: f19_check[f'{o}:full_{a}-{b}'] = {'ref': [ref['ci_low'], ref['ci_high']], 'now': [fam[key][-1]['ci_low'], fam[key][-1]['ci_high']]}
for key, lst in fam.items():
    adj = holm([r['p'] for r in lst])
    for r, a in zip(lst, adj): r['p_holm'] = float(a); r['ci_excludes_0'] = bool(r['ci_low'] > 0 or r['ci_high'] < 0); r['holm_sig_05'] = bool(a < .05)
res['F19_multiplicity'] = {'method': 'package-cluster bootstrap (np.unique cluster order, rng default_rng(42) per origin, 1,000 draws, skip draws without both classes) as executed_source.intervals; '
                           'p = min(1, 2*min((#<=0 + 1)/(n+1), (#>=0 + 1)/(n+1))) (p_raw without +1); Holm within each family of nine',
                           'families': fam, 'interval_reproduction_vs_rq_completion': f19_check,
                           'summary': {k: {'ci_excludes_0': sum(r['ci_excludes_0'] for r in v), 'holm_sig_05': sum(r['holm_sig_05'] for r in v)} for k, v in fam.items()}}
assert all(abs(c['ref'][i] - c['now'][i]) < 1e-12 for c in f19_check.values() for i in (0, 1)), f19_check
print('F-19 done', res['F19_multiplicity']['summary'], flush=True)

# ---------------------------------------------------------------- F-11 lockfile differences recorded - inferred
f11 = {'method': 'paired package-cluster bootstrap over the matched lockfile subset (same rows in both arms; labels may differ); difference = recorded - inferred; 1,000 draws, seed 42 per origin; test-set uncertainty only (models fitted separately per arm, training variation not included)',
       'existing_within_arm_intervals': [r for r in json.loads((LOCK / 'intervals.json').read_text(encoding='utf-8')) if r['cluster_unit'] == 'package'],
       'differences': {}}
LM = ['full_lr', 'full_rf', 'full_xgb', 'libyear_only_lr']
for o in ORG:
    a = pd.read_csv(LOCK / f'inferred_matched_{o}_predictions.csv', keep_default_na=False); b = pd.read_csv(LOCK / f'recorded_{o}_predictions.csv', keep_default_na=False)
    key = ['origin', 'project', 'package', 'dependency_type']; assert (a[key].values == b[key].values).all()
    ya, yb = a.label.to_numpy(int), b.label.to_numpy(int); pa = {m: score_plan(a[m].to_numpy()) for m in LM}; pb = {m: score_plan(b[m].to_numpy()) for m in LM}
    v = {m: {'ap': [], 'auc': []} for m in LM}
    for w in boot_weights(a):
        if not (w @ ya and w @ (1 - ya) and w @ yb and w @ (1 - yb)): continue
        for m in LM:
            v[m]['ap'].append(fast_ap(yb, w, pb[m]) - fast_ap(ya, w, pa[m])); v[m]['auc'].append(fast_auc(yb, w, pb[m]) - fast_auc(ya, w, pa[m]))
    f11['differences'][o] = {'n': int(len(a)), 'pos_inferred': int(ya.sum()), 'pos_recorded': int(yb.sum()), **{m: {
        'inferred': {'ap': float(AP(ya, a[m])), 'auc': float(AUC(ya, a[m]))}, 'recorded': {'ap': float(AP(yb, b[m])), 'auc': float(AUC(yb, b[m]))},
        'd_ap': float(AP(yb, b[m]) - AP(ya, a[m])), 'd_ap_ci': [float(np.quantile(v[m]['ap'], q)) for q in (.025, .975)],
        'd_auc': float(AUC(yb, b[m]) - AUC(ya, a[m])), 'd_auc_ci': [float(np.quantile(v[m]['auc'], q)) for q in (.025, .975)],
        'valid_repeats': len(v[m]['ap'])} for m in LM}}
res['F11_lockfile'] = f11; print('F-11 done', flush=True)

# ---------------------------------------------------------------- F-14 versions-behind under semver ordering
def cohen_d(pos, neg):
    sp = np.sqrt(((len(pos) - 1) * pos.var() + (len(neg) - 1) * neg.var()) / (len(pos) + len(neg) - 2)); return float((pos.mean() - neg.mean()) / sp)
f14 = {'variant_equality': {}, 'd_main_definition_instance': {}}
key = ['project', 'origin', 'package', 'dependency_type']
for v in ('semver_12_clamped', 'semver_12_signed', 'semver_6_clamped'):
    S = pd.read_csv(R / f'robustness/data/{v}.csv', keep_default_na=False); m = DATA.merge(S, on=key, suffixes=('', '_s'))
    f14['variant_equality'][v] = {'rows_matched': int(len(m)), **{c: int((m[c] != m[c + '_s']).sum()) for c in
                                  ('major_versions_behind', 'minor_versions_behind', 'patch_versions_behind', 'latest_version', 'libyear')}}
for o, g in DATA.groupby('origin'):
    f14['d_main_definition_instance'][o] = {c: cohen_d(g[g.label == 1][c].astype(float), g[g.label == 0][c].astype(float))
                                            for c in ('major_versions_behind', 'minor_versions_behind', 'patch_versions_behind', 'package_age')}
f14['finding'] = ('No semver-ordered versions-behind exists: src/semver_variants.cjs changes only the latest-version rule; the count loop '
                  '(releases after used_version_date in date order, reference advanced only on a semver increase) is identical in every variant, '
                  'and the semver_* datasets have identical major/minor/patch columns to date_12_paired (0 differing rows).')
ex = DATA[(DATA.package == 'node-fetch') & (DATA.used_version == '2.6.7') & (DATA.origin == '2023-12-31')]
f14['review_example_now'] = ex[['project', 'used_version', 'latest_version', 'libyear', 'major_versions_behind', 'minor_versions_behind', 'patch_versions_behind']].to_dict('records')
res['F14_semver_versions_behind'] = f14

# ---------------------------------------------------------------- F-23 seeds
f23 = {'seeds': list(range(10)), 'reference_seed': SEED, 'per_origin': {}}
for o in ORG:
    te = DATA[DATA.origin == o]; tr = DATA[(DATA.origin < o) & (DATA.window_end <= o)]; y = te.label.to_numpy(int); r = {}
    for alg in ('rf', 'xgb'):
        per = {}
        for s in list(range(10)) + [SEED]:
            per[s] = metrics(y, model(alg, s).fit(tr[FEAT], tr.label).predict_proba(te[FEAT])[:, 1])
        stats = {}
        for met in ('ap', 'roc_auc', 'recall10'):
            vals = np.array([per[s][met] for s in range(10)]); x42 = per[SEED][met]
            stats[met] = {'mean': float(vals.mean()), 'sd_ddof0': float(vals.std()), 'sd_ddof1': float(vals.std(ddof=1)), 'min': float(vals.min()), 'max': float(vals.max()),
                          'seed42': x42, 'seed42_rank_among_11_desc': int((vals > x42).sum() + 1), 'seed42_z_ddof0': float((x42 - vals.mean()) / vals.std()) if np.ptp(vals) > 1e-12 else 0.}
        r[alg] = {'per_seed': {str(k): v for k, v in per.items()}, 'summary': stats}
    f23['per_origin'][o] = r; print('F-23', o, 'done', flush=True)
res['F23_seeds'] = f23

# ---------------------------------------------------------------- F-20 PIT shifts
pit = json.loads((R / 'verification/advisory_asof/pit_results.json').read_text(encoding='utf-8')); f20 = {'shifts': {}}
for o, d in pit.items():
    for alg, t in d['test_performance'].items():
        f20['shifts'][f'{o}:{alg}'] = {'ap_main': t['ap_current_labels'], 'ap_pit': t['ap_pit_labels'], 'd_ap': t['ap_pit_labels'] - t['ap_current_labels'],
                                        'auc_main': t['auc_current_labels'], 'auc_pit': t['auc_pit_labels'], 'd_auc': t['auc_pit_labels'] - t['auc_current_labels']}
f20['max_abs_d_ap'] = max(abs(v['d_ap']) for v in f20['shifts'].values()); f20['max_abs_d_auc'] = max(abs(v['d_auc']) for v in f20['shifts'].values())
f20['note'] = 'values in pit_results.json are rounded to 4 dp at source; 2021-12-31 origin not checkable (history starts Feb 2022)'
res['F20_pit'] = f20

# ---------------------------------------------------------------- F-24 no-history subset: seen in training
f24 = {}
cov = {r['origin']: r for r in json.loads((R / 'publication/experiments/four_step/seen_unseen_coverage.json').read_text(encoding='utf-8'))}
for o in ORG:
    te = DATA[DATA.origin == o]; tr = DATA[(DATA.origin < o) & (DATA.window_end <= o)]
    hist = set(tr[tr.label == 1].package); seen = set(tr.package); nh = te[~te.package.isin(hist)]; pk = set(nh.package)
    f24[o] = {'no_history_rows': int(len(nh)), 'no_history_positives': int(nh.label.sum()), 'no_history_share_of_test_rows': float(len(nh) / len(te)),
              'no_history_packages': len(pk), 'packages_seen_in_training': len(pk & seen), 'share_packages_seen': float(len(pk & seen) / len(pk)),
              'share_rows_seen': float(nh.package.isin(seen).mean()), 'positives_in_seen_packages': int(nh[nh.package.isin(seen)].label.sum()),
              'four_step_unseen_slice': next(s for s in cov[o]['slices'] if s['slice'] == 'unseen')}
res['F24_no_history_seen'] = f24

def conv(x):
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating,)): return float(x)
    if isinstance(x, (np.bool_,)): return bool(x)
    raise TypeError(type(x))
(OUT / 'round3_results.json').write_text(json.dumps(res, indent=1, ensure_ascii=False, default=conv, allow_nan=False) + '\n', encoding='utf-8')
print('done ->', OUT / 'round3_results.json')
