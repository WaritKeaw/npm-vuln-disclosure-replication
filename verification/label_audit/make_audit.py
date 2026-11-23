"""Label audit sample (seed 42): 50 positives + 50 negatives from paired data, stratified by origin.
For each row lists every reviewed GHSA advisory of that package published inside the label window,
with its range, so a reviewer can check by hand whether used_version is in the affected range."""
import json, pandas as pd, numpy as np
from pathlib import Path
R = Path(__file__).resolve().parents[2]
P = pd.read_parquet(R / 'data/processed/paired.parquet')
adv = {}
for a in json.load(open(R / 'cache/ghsa/advisories.json', encoding='utf-8')):
    if a.get('withdrawn_at'): continue
    for v in a.get('vulnerabilities', []):
        if v['package']['ecosystem'] == 'npm': adv.setdefault(v['package']['name'], []).append((a['ghsa_id'], a['published_at'], v['vulnerable_version_range'], a.get('updated_at')))
rows = []
def window_adv(r): return [a for a in adv.get(r.package, []) if r.origin + 'T23:59:59.999Z' < a[1] <= r.window_end + 'T23:59:59.999Z']
P['has_adv_in_window'] = [bool(window_adv(r)) for r in P.itertuples()]
hard = P[(P.label == 0) & P.has_adv_in_window]   # negatives whose package DID get an advisory in the window
print('hard negatives available:', len(hard))
pick = lambda df, n: pd.concat([g.sample(min(len(g), int(np.ceil(n / 4))), random_state=42) for _, g in df.groupby('origin')]).head(n)
for lab, kind, s in ((1, 'positive', pick(P[P.label == 1], 50)), (0, 'negative_hard', pick(hard, 25)), (0, 'negative_random', pick(P[P.label == 0], 25))):
    for _, r in s.iterrows():
        inwin = [a for a in adv.get(r.package, []) if r.origin + 'T23:59:59.999Z' < a[1] <= r.window_end + 'T23:59:59.999Z']
        rows.append({'sample': kind, 'label': lab, 'origin': r.origin, 'project': r.project, 'package': r.package, 'constraint': r.constraint, 'used_version': r.used_version,
                     'matched_ghsa_ids': r.matched_ghsa_ids, 'advisories_in_window': ' | '.join(f'{i} ({p[:10]}) range="{rg}"' for i, p, rg, _ in inwin),
                     'ghsa_urls': ' '.join('https://github.com/advisories/' + i for i, *_ in inwin), 'npm_url': 'https://www.npmjs.com/package/' + r.package + '/v/' + r.used_version,
                     'manual_check (correct/incorrect)': '', 'note': ''})
pd.DataFrame(rows).to_csv(Path(__file__).parent / 'label_audit_sample.csv', index=False, encoding='utf-8-sig')
d = pd.DataFrame(rows); print('rows', len(d), 'negatives with >=1 advisory in window (harder cases):', int(((d.label == 0) & (d.advisories_in_window != '')).sum()))
