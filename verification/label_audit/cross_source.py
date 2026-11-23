"""Cross-source label check (2026-10-24): re-derive each label with OSV.dev (independent range evaluation)
and the npm registry bulk-advisory endpoint, for all positives, all 'hard' negatives (package has a GHSA in
the window but version judged unaffected), and the 100-row audit sample. Output: cross_source_results.json/.csv"""
import json, time, urllib.request
from pathlib import Path
import pandas as pd
H = Path(__file__).resolve().parent; R = H.parents[1]
P = pd.read_parquet(R / 'data/processed/paired.parquet')
adv = {}; pub = {}
for a in json.load(open(R / 'cache/ghsa/advisories.json', encoding='utf-8')):
    pub[a['ghsa_id']] = a['published_at']
    if a.get('withdrawn_at'): continue
    for v in a.get('vulnerabilities', []):
        if v['package']['ecosystem'] == 'npm': adv.setdefault(v['package']['name'], []).append(a['ghsa_id'])
def norm(t): return t if '.' in t else t.replace('Z', '.000Z')
def in_win(gid, o, e): return gid in pub and o + 'T23:59:59.999Z' < norm(pub[gid]) <= e + 'T23:59:59.999Z'
P['hard'] = [r.label == 0 and any(in_win(g, r.origin, r.window_end) for g in adv.get(r.package, [])) for r in P.itertuples()]
audit = pd.read_csv(H / 'label_audit_sample.csv')
akeys = set(zip(audit.origin, audit.project, audit.package, audit.used_version.astype(str)))
P['in_audit'] = [(r.origin, r.project, r.package, str(r.used_version)) in akeys for r in P.itertuples()]
S = P[(P.label == 1) | P.hard | P.in_audit].copy().reset_index(drop=True)
pairs = S[['package', 'used_version']].drop_duplicates().reset_index(drop=True)
def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'User-Agent': 'thesis-label-audit/1.0'})
    for k in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except Exception:
            time.sleep(2 * (k + 1))
    raise RuntimeError(url)
# OSV querybatch (ids only), then aliases -> GHSA ids
osv = {}
for i in range(0, len(pairs), 500):
    chunk = pairs.iloc[i:i + 500]
    res = post('https://api.osv.dev/v1/querybatch', {'queries': [{'package': {'name': r.package, 'ecosystem': 'npm'}, 'version': str(r.used_version)} for r in chunk.itertuples()]})
    for r, x in zip(chunk.itertuples(), res['results']):
        osv[(r.package, str(r.used_version))] = {v['id'] for v in x.get('vulns', []) or []}
# npm bulk advisories per package (all versions of interest)
npm = {}
for pkg, g in pairs.groupby('package'):
    try:
        res = post('https://registry.npmjs.org/-/npm/v1/security/advisories/bulk', {pkg: sorted(set(g.used_version.astype(str)))})
    except Exception:
        res = None
    for v in g.used_version.astype(str):
        npm[(pkg, v)] = None if res is None else set()
    if res:
        import re as _re
        from functools import lru_cache
        for a in res.get(pkg, []):
            gid = a.get('github_advisory_id') or _re.sub(r'.*/', '', a.get('url', ''))
            rng = a.get('vulnerable_versions', '')
            for v in g.used_version.astype(str):
                npm[(pkg, v)].add((gid, rng))
# npm bulk returns advisories that affect ANY requested version; evaluate range per version with node semver
import subprocess, os
RT = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
items = [{'k': f'{p}@@{v}', 'v': v, 'r': rng, 'g': gid} for (p, v), s in npm.items() if s for gid, rng in s]
js = "const s=require(require.resolve('semver',{paths:[process.env.NM]}));const a=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(a.map(x=>{const r=s.validRange(String(x.r).replace(/,/g,' '));return r!==null&&s.satisfies(x.v,r)})))"
ok = json.loads(subprocess.run([str(RT / 'node/bin/node.exe'), '-e', js], input=json.dumps(items), capture_output=True, text=True, encoding='utf-8', env=dict(os.environ, NM=str(RT / 'node/node_modules')), check=True).stdout)
npm_hit = {}
for it, k in zip(items, ok):
    if k: npm_hit.setdefault(it['k'], set()).add(it['g'])
rows = []
for r in S.itertuples():
    key = (r.package, str(r.used_version))
    o_ids = {i for i in osv.get(key, set()) if in_win(i, r.origin, r.window_end)}
    n_ids = None if npm.get(key) is None else {i for i in npm_hit.get(f'{r.package}@@{r.used_version}', set()) if in_win(i, r.origin, r.window_end)}
    rows.append({'origin': r.origin, 'project': r.project, 'package': r.package, 'used_version': r.used_version, 'label': int(r.label), 'hard_negative': bool(r.hard), 'in_audit': bool(r.in_audit),
                 'label_osv': int(bool(o_ids)), 'label_npm': (None if n_ids is None else int(bool(n_ids))), 'osv_ids': ';'.join(sorted(o_ids)), 'npm_ids': '' if not n_ids else ';'.join(sorted(n_ids)), 'pipeline_ids': r.matched_ghsa_ids})
D = pd.DataFrame(rows); D.to_csv(H / 'cross_source_results.csv', index=False)
def agree(df, col):
    d = df[df[col].notna()]; return {'n': int(len(d)), 'agree': int((d[col] == d.label).sum()), 'rate': round(float((d[col] == d.label).mean()), 4) if len(d) else None}
summ = {'positives_vs_osv': agree(D[D.label == 1], 'label_osv'), 'positives_vs_npm': agree(D[D.label == 1], 'label_npm'),
        'hard_negatives_vs_osv': agree(D[D.hard_negative], 'label_osv'), 'hard_negatives_vs_npm': agree(D[D.hard_negative], 'label_npm'),
        'audit_sample_vs_osv': agree(D[D.in_audit], 'label_osv'), 'audit_sample_vs_npm': agree(D[D.in_audit], 'label_npm'),
        'disagreements_osv': D[(D.label_osv != D.label)][['origin', 'package', 'used_version', 'label', 'pipeline_ids', 'osv_ids']].to_dict('records')[:40]}
(H / 'cross_source_results.json').write_text(json.dumps(summ, indent=1, default=str), encoding='utf-8')
print(json.dumps({k: v for k, v in summ.items() if k != 'disagreements_osv'}, indent=1)); print('osv disagreements:', int((D.label_osv != D.label).sum()))
