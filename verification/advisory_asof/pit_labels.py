"""Point-in-time training labels (verification C5, exploratory).

The main pipeline labels every snapshot with *current* GHSA metadata. Here, for test origins
T = 2022-12-31 and 2023-12-31, training labels are rebuilt from github/advisory-database as it
existed at T (sparse snapshot of advisories/github-reviewed at the last commit <= T), the models
are refit with the same fixed parameters, and scored on the unchanged test set.
2021-12-31 cannot be checked: the repository history starts 2022-02-11.

Parser check: labels from the T = 2023-12-31 database are compared with current labels for windows
that closed long before T (the 2020 snapshot) - disagreements there bound parser error + edits.
"""
from pathlib import Path
import json, re, sys, numpy as np, pandas as pd
from sklearn.metrics import average_precision_score as AP, roc_auc_score as AUC
HERE = Path(__file__).resolve().parent; ROOT = HERE.parents[1]
P = pd.read_parquet(ROOT / 'data/processed/paired.parquet')
CFG = json.loads((ROOT / 'publication/experiments/rq_completion/executed_config.json').read_text()); FEATURES = CFG['features']

def parse(v):
    m = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?', str(v).strip())
    if not m: return None
    pre = m.group(4)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre)
def cmp(a, b):
    if a[:3] != b[:3]: return -1 if a[:3] < b[:3] else 1
    if a[3] == b[3]: return 0
    if a[3] is None: return 1
    if b[3] is None: return -1
    for x, y in zip(a[3].split('.'), b[3].split('.')):
        if x == y: continue
        if x.isdigit() and y.isdigit(): return -1 if int(x) < int(y) else 1
        if x.isdigit(): return -1
        if y.isdigit(): return 1
        return -1 if x < y else 1
    la, lb = len(a[3].split('.')), len(b[3].split('.'))
    return (la > lb) - (la < lb)
def in_ranges(ver, affected):
    v = parse(ver)
    if v is None: return None
    for rg in affected.get('ranges', []):
        if rg.get('type') not in ('ECOSYSTEM', 'SEMVER'): continue
        intro = None; hit = False
        for ev in rg['events']:
            if 'introduced' in ev:
                intro = (0, 0, 0, None) if ev['introduced'] == '0' else parse(ev['introduced'])
            elif 'fixed' in ev and intro is not None:
                f = parse(ev['fixed'])
                if f and cmp(v, intro) >= 0 and cmp(v, f) < 0: return True
                intro = None
            elif 'last_affected' in ev and intro is not None:
                la = parse(ev['last_affected'])
                if la and cmp(v, intro) >= 0 and cmp(v, la) <= 0: return True
                intro = None
        if intro is not None and cmp(v, intro) >= 0:      # open-ended introduced
            lk = (affected.get('database_specific') or {}).get('last_known_affected_version_range')
            if lk:
                m = re.match(r'^(<=|<)\s*(\S+)$', lk.strip()); b = parse(m.group(2)) if m else None
                if b is not None: return cmp(v, b) <= 0 if m.group(1) == '<=' else cmp(v, b) < 0
            return True
    if ver in affected.get('versions', []): return True
    return False

def load_db(T):
    adv = {}
    for f in (HERE / f'db_{T}' / 'advisories/github-reviewed').rglob('*.json'):
        d = json.loads(f.read_text(encoding='utf-8'))
        if d.get('withdrawn') and d['withdrawn'] <= T + 'T23:59:59Z': continue
        for a in d.get('affected', []):
            if a['package'].get('ecosystem') == 'npm':
                adv.setdefault(a['package']['name'], []).append((d['published'], a))
    return adv
def label(df, adv):
    out = []
    for r in df.itertuples():
        lo, hi = r.origin + 'T23:59:59.999Z', r.window_end + 'T23:59:59.999Z'
        hit = False
        for pub, a in adv.get(r.package, []):
            p = pub if '.' in pub else pub.replace('Z', '.000Z')
            if lo < p <= hi and in_ranges(r.used_version, a): hit = True; break
        out.append(int(hit))
    return np.array(out)

from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
def model(kind):
    clf = {'lr': LogisticRegression, 'rf': RandomForestClassifier, 'xgb': XGBClassifier}[kind](**CFG['models'][kind])
    return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), clf)

res = {}
for T in ('2022-12-31', '2023-12-31'):
    adv = load_db(T)
    tr = P[(P.origin < T) & (P.window_end <= T)].copy(); te = P[P.origin == T]
    tr['label_pit'] = label(tr, adv)
    agree = {o: {'rows': int(len(g)), 'current_pos': int(g.label.sum()), 'pit_pos': int(g.label_pit.sum()),
                 'pos_to_neg': int(((g.label == 1) & (g.label_pit == 0)).sum()), 'neg_to_pos': int(((g.label == 0) & (g.label_pit == 1)).sum())}
             for o, g in tr.groupby('origin')}
    y = te.label.to_numpy(); perf = {}
    for kind in ('lr', 'rf', 'xgb'):
        s_cur = model(kind).fit(tr[FEATURES], tr.label).predict_proba(te[FEATURES])[:, 1]
        s_pit = model(kind).fit(tr[FEATURES], tr.label_pit).predict_proba(te[FEATURES])[:, 1]
        perf[kind] = {'ap_current_labels': round(float(AP(y, s_cur)), 4), 'ap_pit_labels': round(float(AP(y, s_pit)), 4),
                      'auc_current_labels': round(float(AUC(y, s_cur)), 4), 'auc_pit_labels': round(float(AUC(y, s_pit)), 4)}
    res[T] = {'training_label_changes': agree, 'test_performance': perf}
(HERE / 'pit_results.json').write_text(json.dumps(res, indent=1), encoding='utf-8'); print(json.dumps(res, indent=1))
