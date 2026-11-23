"""Verification checks for the main pipeline-B results (exploratory, run 2026-10-23).

C1  Concentration: do full models still beat libyear baselines when (a) the top-3 positive packages of
    each test origin are removed, (b) evaluation is at unique (package, used_version) level?
C2  RQ2: package-cluster bootstrap CI of Cohen's d (instance and unique package-version levels).
C6  Reproduction: refit with the installed libraries at seed 42 and compare AP with rq_completion.
C7  Multi-seed RF/XGB (seeds 0-9) + subgroup metrics (production/development, stratum) from stored predictions.
Inputs are read-only: data/processed/paired.parquet, publication/experiments/rq_completion/.
Output: verification/results/checks.json
"""
from pathlib import Path
import json, sys, numpy as np, pandas as pd
from sklearn.metrics import average_precision_score as AP, roc_auc_score as AUC

ROOT = Path(__file__).resolve().parents[1]
RQ = ROOT / 'publication/experiments/rq_completion'
CFG = json.loads((RQ / 'executed_config.json').read_text())
FEATURES = CFG['features']; ORIGINS = ['2021-12-31', '2022-12-31', '2023-12-31']
P = pd.read_parquet(ROOT / 'data/processed/paired.parquet')
STRATUM = P.drop_duplicates('project').set_index('project').stratum
OUT = ROOT / 'verification/results'; OUT.mkdir(parents=True, exist_ok=True)
MODELS = ['full_lr', 'full_rf', 'full_xgb', 'libyear_only_lr', 'libyear_gt_1.0', 'libyear_score']
rng = np.random.default_rng(42)

def recall10(y, s):
    k = max(1, int(np.ceil(len(y) * .1))); o = np.argsort(-s, kind='stable')[:k]; return float(y[o].sum() / y.sum())
def metrics(df, cols=MODELS):
    y = df.label.to_numpy()
    if y.sum() == 0 or y.sum() == len(y): return None
    return {'n': int(len(y)), 'pos': int(y.sum()), **{m: {'ap': round(float(AP(y, df[m])), 4), 'auc': round(float(AUC(y, df[m])), 4), 'r10': round(recall10(y, df[m].to_numpy()), 3)} for m in cols}}
def _groups(df, unit):
    codes, uniq = pd.factorize(df[unit]); order = np.argsort(codes, kind='stable'); bounds = np.searchsorted(codes[order], np.arange(len(uniq) + 1))
    return [order[bounds[i]:bounds[i + 1]] for i in range(len(uniq))]
def cluster_boot_dap(df, a, b, reps=1000, unit='package'):
    g = _groups(df, unit); y = df.label.to_numpy(); sa = df[a].to_numpy(); sb = df[b].to_numpy(); vals = []
    for _ in range(reps):
        idx = np.concatenate([g[i] for i in rng.integers(0, len(g), len(g))])
        if y[idx].sum() == 0: continue
        vals.append(AP(y[idx], sa[idx]) - AP(y[idx], sb[idx]))
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4), len(vals)]
def unique_view(df):
    num = [c for c in df.columns if c not in ('origin', 'project', 'package', 'dependency_type', 'used_version', 'label')]
    return df.groupby(['package', 'used_version']).agg({**{c: 'mean' for c in num}, 'label': 'max'}).reset_index()

res = {'C1': {}, 'C2': {}, 'C6': {}, 'C7': {'subgroups': {}, 'seeds': {}}}
for o in ORIGINS:
    pr = pd.read_csv(RQ / o / 'predictions_wide.csv', keep_default_na=False)
    top3 = pr[pr.label == 1].package.value_counts().head(3).index.tolist()
    ex = pr[~pr.package.isin(top3)]; un = unique_view(pr)
    r = {'top3': top3, 'all': metrics(pr), 'excl_top3': metrics(ex), 'unique_pkg_version': metrics(un), 'ci_package': {}}
    for view, df in (('excl_top3', ex), ('unique_pkg_version', un)):
        for m in ('full_lr', 'full_rf', 'full_xgb'):
            r['ci_package'][f'{view}:{m}-libyear_gt_1.0'] = cluster_boot_dap(df, m, 'libyear_gt_1.0')
            r['ci_package'][f'{view}:{m}-libyear_only_lr'] = cluster_boot_dap(df, m, 'libyear_only_lr')
    res['C1'][o] = r
    pr['stratum'] = pr.project.map(STRATUM)
    res['C7']['subgroups'][o] = {**{f'type:{k}': metrics(g) for k, g in pr.groupby('dependency_type')}, **{f'stratum:{k}': metrics(g) for k, g in pr.groupby('stratum')}}

def d(pos, neg):
    sp = np.sqrt(((len(pos) - 1) * pos.var() + (len(neg) - 1) * neg.var()) / (len(pos) + len(neg) - 2)); return (pos.mean() - neg.mean()) / sp
for o, g in P.groupby('origin'):
    u = g.groupby(['package', 'used_version']).agg(libyear=('libyear', 'first'), label=('label', 'max')).reset_index()
    out = {}
    for name, df in (('instance', g), ('unique_pkg_version', u)):
        gr = _groups(df, 'package'); y = df.label.to_numpy(); ly = df.libyear.to_numpy(); vals = []
        for _ in range(1000):
            idx = np.concatenate([gr[i] for i in rng.integers(0, len(gr), len(gr))]); yy = y[idx]; ll = ly[idx]
            if 1 < yy.sum() < len(yy) - 1: vals.append(d(pd.Series(ll[yy == 1]), pd.Series(ll[yy == 0])))
        out[name] = {'d': round(float(d(df[df.label == 1].libyear, df[df.label == 0].libyear)), 3), 'ci95_package': [round(float(np.percentile(vals, 2.5)), 3), round(float(np.percentile(vals, 97.5)), 3)], 'reps': len(vals)}
    res['C2'][o] = out

# C6 + C7 seeds: refit
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
import sklearn, xgboost
res['C6']['versions'] = {'sklearn': sklearn.__version__, 'xgboost': xgboost.__version__, 'reference_xgboost': '3.0.5'}
ref = {(r['origin'], r['model']): r['ap'] for r in json.load(open(RQ / 'metrics.json'))}
def fit(kind, seed):
    m = dict(CFG['models'][kind]);
    if kind != 'lr': m['random_state'] = seed
    clf = {'lr': LogisticRegression, 'rf': RandomForestClassifier, 'xgb': XGBClassifier}[kind](**m)
    return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), clf)
for o in ORIGINS:
    tr = P[(P.origin < o) & (P.window_end <= o)]; te = P[P.origin == o]; y = te.label.to_numpy()
    rep = {}
    for kind in ('lr', 'rf', 'xgb'):
        s = fit(kind, 42).fit(tr[FEATURES], tr.label).predict_proba(te[FEATURES])[:, 1]
        rep[kind] = {'ap_now': round(float(AP(y, s)), 4), 'ap_reference': round(ref[(o, 'full_' + kind)], 4)}
    res['C6'][o] = rep
    seeds = {}
    for kind in ('rf', 'xgb'):
        aps, aucs = [], []
        for seed in range(10):
            s = fit(kind, seed).fit(tr[FEATURES], tr.label).predict_proba(te[FEATURES])[:, 1]; aps.append(AP(y, s)); aucs.append(AUC(y, s))
        seeds[kind] = {'ap_mean': round(float(np.mean(aps)), 4), 'ap_sd': round(float(np.std(aps)), 4), 'ap_min': round(float(min(aps)), 4), 'ap_max': round(float(max(aps)), 4),
                       'auc_mean': round(float(np.mean(aucs)), 4), 'auc_sd': round(float(np.std(aucs)), 4)}
    res['C7']['seeds'][o] = seeds
(OUT / 'checks.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8'); print('done')
