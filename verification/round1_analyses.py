"""Analyses requested by review round 1 (exploratory, 2026-10-23). Output: verification/results/round1.json"""
from pathlib import Path
import json, numpy as np, pandas as pd
from sklearn.metrics import average_precision_score as AP, roc_auc_score as AUC
R = Path(__file__).resolve().parents[1]; RQ = R / 'publication/experiments/rq_completion'
P = pd.read_parquet(R / 'data/processed/paired.parquet'); ORG = ['2021-12-31', '2022-12-31', '2023-12-31']
CFG = json.loads((RQ / 'executed_config.json').read_text()); FEAT = CFG['features']
rng = np.random.default_rng(42); out = {}

def exp_recall(y, s, frac=.1):
    """Expected recall@budget under uniform random tie-breaking (analytic)."""
    k = int(np.ceil(len(y) * frac)); order = np.argsort(-s, kind='stable'); ss = s[order]; yy = y[order]
    thr = ss[k - 1]; above = ss > thr; tie = ss == thr
    hits = yy[above].sum() + (k - above.sum()) * (yy[tie].mean())
    return float(hits / y.sum())
def groups(df, unit='package'):
    codes, uniq = pd.factorize(df[unit]); order = np.argsort(codes, kind='stable'); b = np.searchsorted(codes[order], np.arange(len(uniq) + 1))
    return [order[b[i]:b[i + 1]] for i in range(len(uniq))]
def boot_diff(df, a, b, metric, reps=1000):
    g = groups(df); y = df.label.to_numpy(); sa = df[a].to_numpy(); sb = df[b].to_numpy(); v = []
    for _ in range(reps):
        idx = np.concatenate([g[i] for i in rng.integers(0, len(g), len(g))])
        if 0 < y[idx].sum() < len(idx): v.append(metric(y[idx], sa[idx]) - metric(y[idx], sb[idx]))
    return [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)]

# B1: prior-history baselines + C5 algorithm pairs + M6 tie-aware recall + M8 family ablation CIs
out['B1'] = {}; out['M5'] = {}; out['M6'] = {}; out['M8'] = {}
for o in ORG:
    pr = pd.read_csv(RQ / o / 'predictions_wide.csv', keep_default_na=False)
    tr = P[(P.origin < o) & (P.window_end <= o)]
    hist_any = set(tr[tr.label == 1].package)
    cnt = tr[tr.label == 1].groupby('package').size(); rate = tr.groupby('package').label.mean()
    pr['hist_any'] = pr.package.isin(hist_any).astype(float)
    pr['hist_count'] = pr.package.map(cnt).fillna(0).astype(float)
    pr['hist_rate'] = pr.package.map(rate).fillna(tr.label.mean()).astype(float)   # = package target encoding
    y = pr.label.to_numpy()
    res = {}
    for m in ['full_lr', 'full_rf', 'full_xgb', 'hist_any', 'hist_count', 'hist_rate', 'libyear_gt_1.0', 'libyear_only_lr']:
        s = pr[m].to_numpy(); res[m] = {'ap': round(float(AP(y, s)), 4), 'auc': round(float(AUC(y, s)), 4), 'recall10_expected': round(exp_recall(y, s), 3)}
    res['ci_ap'] = {f'{m}-hist_rate': boot_diff(pr, m, 'hist_rate', AP) for m in ['full_lr', 'full_rf', 'full_xgb']}
    res['ci_auc'] = {f'{m}-hist_rate': boot_diff(pr, m, 'hist_rate', AUC) for m in ['full_lr', 'full_rf', 'full_xgb']}
    res['positives_seen_positive_before'] = round(float(pr[(pr.label == 1)].hist_any.mean()), 3)
    # ML performance among rows whose package had NO prior positive (history cannot help there)
    nh = pr[pr.hist_any == 0]
    res['no_history_subset'] = {'n': int(len(nh)), 'pos': int(nh.label.sum()), **{m: {'ap': round(float(AP(nh.label, nh[m])), 4), 'auc': round(float(AUC(nh.label, nh[m])), 4)} for m in ['full_lr', 'full_rf', 'full_xgb', 'libyear_only_lr', 'hist_rate']}}
    out['B1'][o] = res
    out['M5'][o] = {f'{a}-{b}': {'d_ap': round(float(AP(y, pr[a]) - AP(y, pr[b])), 4), 'ci_ap': boot_diff(pr, a, b, AP), 'd_auc': round(float(AUC(y, pr[a]) - AUC(y, pr[b])), 4), 'ci_auc': boot_diff(pr, a, b, AUC)}
                    for a, b in [('full_lr', 'full_rf'), ('full_lr', 'full_xgb'), ('full_rf', 'full_xgb')]}
    out['M6'][o] = {m: round(exp_recall(y, pr[m].to_numpy()), 3) for m in ['full_lr', 'full_rf', 'full_xgb', 'libyear_only_lr', 'libyear_score', 'libyear_gt_0.25', 'libyear_gt_0.5', 'libyear_gt_1.0']}
    ns = pd.read_csv(R / f'publication/experiments/four_step/new_scores/{o}.csv', keep_default_na=False)
    mg = pr[['project', 'package', 'dependency_type', 'used_version', 'label', 'full_lr', 'full_rf', 'full_xgb']].merge(ns[['project', 'package', 'dependency_type', 'used_version', 'drop_lag_recency_family_lr', 'drop_lag_recency_family_rf', 'drop_lag_recency_family_xgb']], on=['project', 'package', 'dependency_type', 'used_version'], how='inner')
    out['M8'][o] = {'rows': len(mg), **{k: {'d_ap': round(float(AP(mg.label, mg['full_' + k]) - AP(mg.label, mg['drop_lag_recency_family_' + k])), 4), 'ci_ap': boot_diff(mg, 'full_' + k, 'drop_lag_recency_family_' + k, AP)} for k in ('lr', 'rf', 'xgb')}}

# B2: lockfile vs inferred libyear distribution
L = R / 'publication/experiments/lockfile_sensitivity'
inf = pd.read_csv(L / 'inferred_matched.csv', keep_default_na=False, low_memory=False); rec = pd.read_csv(L / 'recorded.csv', keep_default_na=False, low_memory=False)
out['B2'] = {}
for o in sorted(inf.origin.unique()):
    a = pd.to_numeric(inf[inf.origin == o].libyear, errors='coerce'); b = pd.to_numeric(rec[rec.origin == o].libyear, errors='coerce')
    la = pd.to_numeric(inf[inf.origin == o].label, errors='coerce'); lb = pd.to_numeric(rec[rec.origin == o].label, errors='coerce')
    out['B2'][o] = {'n': int(len(a)), 'zero_inferred': round(float((a == 0).mean()), 3), 'zero_lockfile': round(float((b == 0).mean()), 3), 'mean_inferred': round(float(a.mean()), 2), 'mean_lockfile': round(float(b.mean()), 2),
                    'pos_inferred': int(la.sum()), 'pos_lockfile': int(lb.sum())}

# M9: rank-based effect (AUC of libyear = probability of superiority) + package-cluster CI, both units; d without top3
out['M9'] = {}
for o, g in P.groupby('origin'):
    u = g.groupby(['package', 'used_version']).agg(libyear=('libyear', 'first'), label=('label', 'max'), package_age=('package_age', 'first')).reset_index()
    r = {}
    for name, df in (('instance', g), ('unique', u)):
        gg = groups(df); y = df.label.to_numpy(); x = df.libyear.to_numpy(); v = []
        for _ in range(1000):
            idx = np.concatenate([gg[i] for i in rng.integers(0, len(gg), len(gg))])
            if 0 < y[idx].sum() < len(idx): v.append(AUC(y[idx], x[idx]))
        r[name] = {'auc_libyear': round(float(AUC(y, x)), 3), 'ci': [round(float(np.percentile(v, 2.5)), 3), round(float(np.percentile(v, 97.5)), 3)]}
    pos, neg = u[u.label == 1].package_age, u[u.label == 0].package_age
    sp = np.sqrt(((len(pos) - 1) * pos.var() + (len(neg) - 1) * neg.var()) / (len(pos) + len(neg) - 2)); r['package_age_d_unique'] = round(float((pos.mean() - neg.mean()) / sp), 3)
    out['M9'][o] = r

# M10: advisories per year and review lag
adv = json.load(open(R / 'cache/ghsa/advisories.json', encoding='utf-8'))
df = pd.DataFrame([{'pub': a['published_at'], 'rev': a.get('github_reviewed_at'), 'wd': a.get('withdrawn_at')} for a in adv])
df = df[df.wd.isna()]; df['year'] = df.pub.str[:4]; df['lag_days'] = (pd.to_datetime(df.rev) - pd.to_datetime(df.pub)).dt.days
out['M10'] = {y: {'n': int(len(g)), 'reviewed_gt_365d_after_pub': int((g.lag_days > 365).sum()), 'median_lag_days': float(g.lag_days.median())} for y, g in df.groupby('year')}

# M3: positives where a patched version was already published at the origin
times = {}
for f in (R / 'cache/npm').glob('*.json'):
    p = json.loads(f.read_text(encoding='utf-8')); times[p['package']] = p['times']
fp = {}
for a in adv:
    if a.get('withdrawn_at'): continue
    for v in a.get('vulnerabilities', []):
        if v['package']['ecosystem'] == 'npm': fp[(a['ghsa_id'], v['package']['name'])] = (v.get('first_patched_version') or {}) if isinstance(v.get('first_patched_version'), dict) else v.get('first_patched_version')
out['M3'] = {}
for o, g in P[P.label == 1].groupby('origin'):
    pre = []
    for r in g.itertuples():
        ok = False
        for gid in str(r.matched_ghsa_ids).split(';'):
            fv = fp.get((gid, r.package)); fv = fv.get('identifier') if isinstance(fv, dict) else fv
            t = times.get(r.package, {}).get(fv) if fv else None
            if t and t <= o + 'T23:59:59.999Z': ok = True
        pre.append(ok)
    pre = np.array(pre); gg = g.assign(pre=pre)
    out['M3'][o] = {'positives': int(len(g)), 'fix_available_at_origin': int(pre.sum()), 'share': round(float(pre.mean()), 3),
                    'mean_libyear_fix_available': round(float(gg[gg.pre].libyear.mean()), 2) if pre.any() else None, 'mean_libyear_no_fix': round(float(gg[~gg.pre].libyear.mean()), 2)}

# M11: fixed-size training (most recent eligible snapshot only)
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
out['M11'] = {}
for o in ORG:
    elig = sorted(P[(P.origin < o) & (P.window_end <= o)].origin.unique()); tr = P[P.origin == elig[-1]]; te = P[P.origin == o]; y = te.label.to_numpy(); r = {'train_origin': elig[-1], 'train_pos': int(tr.label.sum())}
    for k, C in (('lr', LogisticRegression), ('rf', RandomForestClassifier), ('xgb', XGBClassifier)):
        s = make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), C(**CFG['models'][k])).fit(tr[FEAT], tr.label).predict_proba(te[FEAT])[:, 1]
        r[k] = {'ap': round(float(AP(y, s)), 4), 'auc': round(float(AUC(y, s)), 4)}
    out['M11'][o] = r
(R / 'verification/results/round1.json').write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8'); print('done')
