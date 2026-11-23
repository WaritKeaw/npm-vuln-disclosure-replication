"""Numbers for review round 2 fixes: tie-aware rule recall in 3 views; no-history subset CIs; projects without production deps."""
import json, numpy as np, pandas as pd
from pathlib import Path
from sklearn.metrics import roc_auc_score as AUC, average_precision_score as AP
R = Path(__file__).resolve().parents[1]; RQ = R / 'publication/experiments/rq_completion'; P = pd.read_parquet(R / 'data/processed/paired.parquet')
rng = np.random.default_rng(42); out = {'rule_recall': {}, 'no_history': {}}
def exp_recall(y, s, f=.1):
    k = int(np.ceil(len(y) * f)); o = np.argsort(-s, kind='stable'); ss, yy = s[o], y[o]; thr = ss[k - 1]; a = ss > thr; t = ss == thr
    return float((yy[a].sum() + (k - a.sum()) * yy[t].mean()) / y.sum())
def groups(df):
    c, u = pd.factorize(df.package); o = np.argsort(c, kind='stable'); b = np.searchsorted(c[o], np.arange(len(u) + 1)); return [o[b[i]:b[i + 1]] for i in range(len(u))]
for o in ['2021-12-31', '2022-12-31', '2023-12-31']:
    pr = pd.read_csv(RQ / o / 'predictions_wide.csv', keep_default_na=False)
    top3 = pr[pr.label == 1].package.value_counts().head(3).index
    num = [c for c in pr.columns if c not in ('origin', 'project', 'package', 'dependency_type', 'used_version', 'label')]
    un = pr.groupby(['package', 'used_version']).agg({**{c: 'mean' for c in num}, 'label': 'max'}).reset_index()
    out['rule_recall'][o] = {v: round(exp_recall(d.label.to_numpy(), d['libyear_gt_1.0'].to_numpy()), 3) for v, d in (('instance', pr), ('unique', un), ('excl_top3', pr[~pr.package.isin(top3)]))}
    tr = P[(P.origin < o) & (P.window_end <= o)]; nh = pr[~pr.package.isin(set(tr[tr.label == 1].package))].reset_index(drop=True)
    seen = set(tr.package); g = groups(nh); y = nh.label.to_numpy(); r = {'n': len(nh), 'pos': int(y.sum()), 'share_rows_seen_in_training': round(float(nh.package.isin(seen).mean()), 3)}
    for m in ('full_lr', 'full_rf', 'full_xgb'):
        a, b = nh[m].to_numpy(), nh['libyear_only_lr'].to_numpy(); va, vd = [], []
        for _ in range(1000):
            idx = np.concatenate([g[i] for i in rng.integers(0, len(g), len(g))])
            if 0 < y[idx].sum() < len(idx): va.append(AUC(y[idx], a[idx])); vd.append(AUC(y[idx], a[idx]) - AUC(y[idx], b[idx]))
        r[m] = {'auc': round(float(AUC(y, a)), 3), 'auc_ci': [round(float(np.percentile(va, q)), 3) for q in (2.5, 97.5)], 'auc_minus_libyear_only_ci': [round(float(np.percentile(vd, q)), 3) for q in (2.5, 97.5)]}
    out['no_history'][o] = r
g = P[P.origin == '2023-12-31']; out['projects_without_production_deps_2023'] = int((g.groupby('project').dependency_type.apply(lambda s: (s == 'production').sum()) == 0).sum())
(R / 'verification/results/round2.json').write_text(json.dumps(out, indent=1), encoding='utf-8'); print(json.dumps(out, indent=1))
