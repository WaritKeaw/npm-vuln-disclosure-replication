"""Label range-validity checks (exploratory, 2026-10-24).

Check 1 - NVD CPE ranges (partly independent source): for every positive instance and every 'hard negative'
          (label 0, but the package has a reviewed non-withdrawn GHSA advisory published in the window whose
          range does not cover used_version), compare the GHSA verdict with the NVD CVE 2.0 configurations.
Check 2 - advisories with no lower bound: classify each matched GHSA range as unbounded-below vs bounded,
          then rerun the main backtest with positives matched only by unbounded ranges dropped (A) or
          relabelled 0 (B), and report libyear means / Cohen's d with and without them.

Protocol reused from publication/experiments/rq_completion/executed_source.py (fixed parameters, expanding
window, seed 42, package-cluster bootstrap 1,000 with the same weighting). Inputs are read-only.

Run (bundled Python 3.12):
  PYTHONIOENCODING=utf-8 python verification/range_checks/range_checks.py fetch     # NVD API -> cache/nvd (<=5 req / 30 s)
  PYTHONIOENCODING=utf-8 python verification/range_checks/range_checks.py analyze   # offline from cache
Outputs: range_checks_results.json (unrounded), nvd_disagreements.csv, nvd_advisory_status.csv
"""
from pathlib import Path
import argparse, csv, importlib.util, json, math, os, re, subprocess, sys, time, urllib.error, urllib.request

H = Path(__file__).resolve().parent; R = H.parents[1]
sys.path[:0] = [str(R / 'publication/tools/vendor'), str(R / 'tools/vendor')]  # exactly as executed_source.py (xgboost 3.0.5, sklearn 1.9.1, numpy 2.5.4)
import numpy as np, pandas as pd

CACHE = H / 'cache/nvd'
RT = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
NODE, NM = RT / 'node/bin/node.exe', RT / 'node/node_modules'
RQ = R / 'publication/experiments/rq_completion'
DATA = pd.read_csv(R / 'robustness/data/date_12_paired.csv', keep_default_na=False)   # same file as executed_source.py
ADVL = json.loads((R / 'cache/ghsa/advisories.json').read_text(encoding='utf-8'))
ADV = {a['ghsa_id']: a for a in ADVL}
ENT = {}   # package -> GHSA entries (reviewed, non-withdrawn, npm) exactly as src/pipeline.py builds them
for a in ADVL:
    if a.get('withdrawn_at'): continue
    for v in a.get('vulnerabilities', []):
        if v['package']['ecosystem'] == 'npm':
            ENT.setdefault(v['package']['name'], []).append({'gid': a['ghsa_id'], 'pub': pd.Timestamp(a['published_at']),
                                                            'range': v['vulnerable_version_range'], 'patched': v.get('first_patched_version')})
def cut(d): return pd.Timestamp(d + 'T23:59:59.999Z')
def ids(s): return [x for x in str(s).split(';') if x]
def cves_of(g):
    a = ADV[g]; c = {i['value'] for i in a.get('identifiers', []) if i.get('type') == 'CVE'}
    if a.get('cve_id'): c.add(a['cve_id'])
    return sorted(c)

# rows of interest: positives + hard negatives, with in-window entries of the package
ROWS = []
for i, r in enumerate(DATA.itertuples()):
    win = [e for e in ENT.get(r.package, []) if cut(r.origin) < e['pub'] <= cut(r.window_end)]
    if r.label == 1 or win:
        ROWS.append({'i': i, 'origin': r.origin, 'project': r.project, 'package': r.package, 'used_version': str(r.used_version),
                     'label': int(r.label), 'matched': ids(r.matched_ghsa_ids), 'win': win, 'libyear': float(r.libyear)})
ADV_INTEREST = sorted({g for r in ROWS for g in (r['matched'] if r['label'] else [e['gid'] for e in r['win']])})
CVES = sorted({c for g in ADV_INTEREST for c in cves_of(g)})


# ------------------------------------------------------------------ stage: fetch
def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    todo = [c for c in CVES if not (CACHE / f'{c}.json').exists()]
    print(f'{len(CVES)} CVEs, {len(todo)} to fetch', flush=True)
    last = 0.
    for n, c in enumerate(todo, 1):
        url = f'https://services.nvd.nist.gov/rest/json/cves/2.0?cveId={c}'
        for attempt in range(8):
            wait = 6.5 - (time.time() - last)          # <= 5 requests per 30 s (public rate without key)
            if wait > 0: time.sleep(wait)
            last = time.time()
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'thesis-range-check/1.0'})
                with urllib.request.urlopen(req, timeout=60) as resp: body = resp.read().decode('utf-8')
                json.loads(body)
                (CACHE / f'{c}.json').write_text(body, encoding='utf-8'); print(n, c, 'ok', flush=True); break
            except Exception as ex:  # 403/429/5xx/timeouts -> back off and retry
                back = min(300, 15 * 2 ** attempt); print(n, c, 'error', repr(ex)[:120], 'retry in', back, flush=True); time.sleep(back)
        else:
            print(n, c, 'FAILED', flush=True)
    print('missing after fetch:', [c for c in CVES if not (CACHE / f'{c}.json').exists()], flush=True)


# ------------------------------------------------------------------ node semver helper
JS = r"""
const s=require(require.resolve('semver',{paths:[process.env.NM]}));
const inp=JSON.parse(require('fs').readFileSync(0,'utf8'));
const isV=x=>x instanceof s.SemVer;
function rangeInfo(v,rs){ // GHSA range: pipeline semantics (commas -> spaces, validRange, satisfies)
  const vr=typeof rs==='string'?s.validRange(rs.replace(/,/g,' ')):null;
  if(vr===null) return {valid:false};
  const R=new s.Range(vr); const sets=[];
  for(const set of R.set){
    let lb=null,ub=null,why=[];
    for(const c of set){
      if(!isV(c.semver)) continue;
      if(c.operator==='>='||c.operator==='>'||c.operator===''){ if(!lb||s.gt(c.semver,lb)) lb=c.semver; }
      if(c.operator==='<='||c.operator==='<'||c.operator===''){ if(!ub||s.lt(c.semver,ub)) ub=c.semver; }
      if(!c.test(v)) why.push((c.operator==='>='||c.operator==='>')?'below_lower':(c.operator===''?'not_exact':'at_or_above_upper'));
    }
    const cover=set.every(c=>c.test(v));
    sets.push({cover,bounded:!!(lb&&s.gt(lb,'0.0.0')),lb:lb?lb.version:null,ub:ub?ub.version:null,why:[...new Set(why)].join('+')});
  }
  return {valid:true,sat:s.satisfies(v,vr),sets};
}
function norm(x){ if(x==null) return null; const v=s.valid(x); if(v) return {v,c:false}; const c=s.coerce(x,{includePrerelease:true}); return c?{v:c.version,c:true}:null; }
function entryAff(v,e){ // NVD cpeMatch evaluated with npm semver ordering
  const hasB=e.si||e.se||e.ei||e.ee; let coerced=false;
  if(!hasB){
    if(e.ver==='*') return {aff:true,why:'all_versions',coerced};
    if(e.ver==='-'||e.ver==null||e.ver==='') return {aff:null,why:'version_na',coerced};
    const x=e.ver+((e.upd&&e.upd!=='*'&&e.upd!=='-')?'-'+e.upd:''); const n=norm(x);
    if(!n) return {aff:null,why:'unparseable_version',coerced};
    const eq=s.eq(v,n.v); return {aff:eq,why:eq?'exact_match':'exact_other',coerced:n.c};
  }
  let ok=true; const why=[];
  for(const [k,op] of [['si','>='],['se','>'],['ei','<='],['ee','<']]) if(e[k]){
    const n=norm(e[k]); if(!n) return {aff:null,why:'unparseable_bound',coerced};
    coerced=coerced||n.c;
    const pass=op==='>='?s.gte(v,n.v):op==='>'?s.gt(v,n.v):op==='<='?s.lte(v,n.v):s.lt(v,n.v);
    if(!pass){ok=false;why.push(k[0]==='s'?'below_lower':'at_or_above_upper');}
  }
  return {aff:ok,why:ok?'in_range':why.join('+'),coerced};
}
const out={ghsa:inp.ghsa.map(t=>rangeInfo(t.v,t.r)),nvd:inp.nvd.map(t=>t.entries.map(e=>entryAff(t.v,e))),sets:[],minv:{}};
for(const [p,vs] of Object.entries(inp.versions)){ const ok=vs.filter(v=>s.valid(v)&&!s.prerelease(v)); out.minv[p]=ok.length?s.sort(ok)[0]:null; }
for(const t of inp.sets){
  const vs=(inp.versions[t.pkg]||[]).filter(v=>s.valid(v)&&!s.prerelease(v));
  const rs=t.ranges.map(r=>s.validRange(r.replace(/,/g,' '))).filter(r=>r!==null);
  let g=0,n=0,b=0,go=[],no=[];
  for(const v of vs){ const a=rs.some(r=>s.satisfies(v,r)); const z=t.entries.some(e=>entryAff(v,e).aff===true);
    if(a)g++; if(z)n++; if(a&&z)b++; if(a&&!z)go.push(v); if(z&&!a)no.push(v); }
  out.sets.push({n_versions:vs.length,ghsa:g,nvd:n,both:b,ghsa_only:go.length,nvd_only:no.length,ghsa_only_ex:s.sort(go).slice(0,8),nvd_only_ex:s.sort(no).slice(0,8)});
}
process.stdout.write(JSON.stringify(out));
"""
def node_eval(payload):
    run = subprocess.run([str(NODE), '-e', JS], input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
                         env=dict(os.environ, NM=str(NM)), check=True)
    return json.loads(run.stdout)


# ------------------------------------------------------------------ NVD parsing
def split_cpe(c): return [x.replace('\\', '') for x in re.split(r'(?<!\\):', c)]
def compact(x): return re.sub(r'[^a-z0-9]', '', x.lower())
def strip_affix(c): return re.sub(r'js$', '', re.sub(r'^node', '', c))
def name_keys(pkg):
    name = pkg.split('/')[-1]; scope = pkg[1:].split('/')[0] if pkg.startswith('@') else ''
    exact = {compact(name)} | ({compact(scope + name)} if scope else set())
    return exact, {strip_affix(k) for k in exact if len(strip_affix(k)) >= 3}
NODE_TARGETS = {'node.js', 'nodejs', 'node', 'npm', '*', '-'}

def nvd_for_cve(c):
    p = CACHE / f'{c}.json'
    if not p.exists(): return {'status': 'not_fetched'}
    d = json.loads(p.read_text(encoding='utf-8'))
    if not d.get('vulnerabilities'): return {'status': 'nvd_not_found'}
    cve = d['vulnerabilities'][0]['cve']; st = cve.get('vulnStatus')
    if st == 'Rejected': return {'status': 'rejected', 'vulnStatus': st}
    ms = []
    for conf in cve.get('configurations', []) or []:
        for node in conf.get('nodes', []) or []:
            if node.get('negate'): continue
            for m in node.get('cpeMatch', []) or []:
                if not m.get('vulnerable'): continue
                f = split_cpe(m['criteria'])
                if len(f) < 13 or f[2] != 'a': continue
                ms.append({'vendor': f[3], 'product': f[4], 'ver': f[5], 'upd': f[6], 'target_sw': f[10], 'criteria': m['criteria'],
                           'si': m.get('versionStartIncluding'), 'se': m.get('versionStartExcluding'),
                           'ei': m.get('versionEndIncluding'), 'ee': m.get('versionEndExcluding')})
    if not cve.get('configurations'): return {'status': 'no_configurations', 'vulnStatus': st}
    return {'status': 'has_configurations', 'vulnStatus': st, 'matches': ms}

def nvd_entries_for(gid, pkg):
    """Select NVD vulnerable application CPE matches for this npm package (heuristic, see README)."""
    cv = cves_of(gid)
    if not cv: return {'status': 'no_cve', 'cves': []}
    infos = {c: nvd_for_cve(c) for c in cv}
    sts = [i['status'] for i in infos.values()]
    allm = [dict(m, cve=c) for c, i in infos.items() for m in i.get('matches', [])]
    vstat = ';'.join(sorted({str(i.get('vulnStatus')) for i in infos.values()}))
    base = {'cves': cv, 'vulnStatus': vstat}
    if 'has_configurations' not in sts:
        order = ['not_fetched', 'nvd_not_found', 'rejected', 'no_configurations']
        return {**base, 'status': min(sts, key=order.index)}
    exact, affix = name_keys(pkg)
    lvl = []
    for m in allm:
        cp = compact(m['product'])
        lvl.append('exact' if cp in exact else ('affix' if strip_affix(cp) in affix else None))
    prods = sorted({f"{m['vendor']}:{m['product']}" for m in allm})
    level = 'exact' if 'exact' in lvl else ('affix' if 'affix' in lvl else None)
    sub = sorted({f"{m['vendor']}:{m['product']}" for m in allm
                  if any(len(k) >= 4 and len(compact(m['product'])) >= 4 and (k in compact(m['product']) or compact(m['product']) in k) for k in exact)})
    if level: chosen = [m for m, l in zip(allm, lvl) if l == level]
    elif len(sub) == 1: chosen, level = [m for m in allm if f"{m['vendor']}:{m['product']}" == sub[0]], 'fallback_name_overlap'
    elif len(prods) == 1: chosen, level = allm, 'fallback_single_product'
    else: return {**base, 'status': 'no_product_match', 'products': prods}
    node_like = [m for m in chosen if m['target_sw'].lower() in NODE_TARGETS]
    if not node_like: return {**base, 'status': 'non_node_target_only', 'products': prods, 'level': level,
                              'targets': sorted({m['target_sw'] for m in chosen})}
    usable = [m for m in node_like if not (m['ver'] in ('-', '') and not any(m[k] for k in ('si', 'se', 'ei', 'ee')))]
    if not usable: return {**base, 'status': 'no_usable_version_info', 'products': prods, 'level': level}
    return {**base, 'status': 'usable', 'level': level, 'products': prods, 'entries': usable,
            'all_versions_star': all(m['ver'] == '*' and not any(m[k] for k in ('si', 'se', 'ei', 'ee')) for m in usable)}

def nvd_str(es):
    out = []
    for m in es:
        b = ' '.join(x for x in [f">={m['si']}" if m['si'] else '', f">{m['se']}" if m['se'] else '', f"<={m['ei']}" if m['ei'] else '', f"<{m['ee']}" if m['ee'] else ''] if x)
        out.append(f"{m['vendor']}:{m['product']}[{m['target_sw']}] " + (b if b else ('*' if m['ver'] == '*' else '=' + m['ver'] + ('' if m['upd'] in ('*', '-') else '-' + m['upd']))))
    return ' | '.join(out)

def wilson(k, n, z=1.959963984540054):
    if n == 0: return [None, None]
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]
def rate(k, n): return {'k': int(k), 'n': int(n), 'rate': (k / n if n else None), 'wilson95': wilson(k, n)}


# ------------------------------------------------------------------ stage: analyze
def analyze():
    res = {'meta': {'data': 'robustness/data/date_12_paired.csv', 'rows': int(len(DATA)), 'positives': int(DATA.label.sum()),
                    'hard_negatives': int(sum(1 for r in ROWS if r['label'] == 0)), 'advisories_of_interest': len(ADV_INTEREST),
                    'cves_of_interest': len(CVES), 'cves_cached': sum((CACHE / f'{c}.json').exists() for c in CVES),
                    'semver': 'node semver ' + json.loads((NM / 'semver/package.json').read_text())['version']}}
    # ---- npm versions of packages of interest (for advisory-level version-set comparison and earliest version)
    pk = {r['package'] for r in ROWS}; versions = {}
    for f in (R / 'cache/npm').glob('*.json'):
        d = json.loads(f.read_text(encoding='utf-8'))
        if d.get('package') in pk: versions[d['package']] = list(d.get('times', {}))
    # ---- GHSA evaluation of every in-window entry for rows of interest
    gt = []; gidx = {}
    for r in ROWS:
        for e in r['win']:
            k = (r['used_version'], e['range'])
            if k not in gidx: gidx[k] = len(gt); gt.append({'v': k[0], 'r': k[1]})
    # ---- NVD selection per (advisory, package) and evaluation tasks
    sel = {}
    for r in ROWS:
        for g in (r['matched'] if r['label'] else sorted({e['gid'] for e in r['win']})):
            if (g, r['package']) not in sel: sel[(g, r['package'])] = nvd_entries_for(g, r['package'])
    nt = []; nidx = {}
    for r in ROWS:
        for g in (r['matched'] if r['label'] else sorted({e['gid'] for e in r['win']})):
            s = sel[(g, r['package'])]
            if s['status'] == 'usable' and (r['used_version'], g, r['package']) not in nidx:
                nidx[(r['used_version'], g, r['package'])] = len(nt); nt.append({'v': r['used_version'], 'entries': s['entries']})
    sets_keys = [k for k, s in sel.items() if s['status'] == 'usable']
    sets = [{'pkg': p, 'ranges': [e['range'] for e in ENT[p] if e['gid'] == g], 'entries': sel[(g, p)]['entries']} for g, p in sets_keys]
    J = node_eval({'ghsa': gt, 'nvd': nt, 'sets': sets, 'versions': versions})
    MINV = J['minv']

    # ---- reproduce labels and classify ranges (Check 2 descriptors)
    mism = 0
    for r in ROWS:
        cov = []
        for e in r['win']:
            info = J['ghsa'][gidx[(r['used_version'], e['range'])]]; assert info['valid'], e
            e2 = dict(e, info=info)
            if info['sat']: cov.append(e2)
            r.setdefault('win_eval', []).append(e2)
        if sorted({e['gid'] for e in cov}) != sorted(r['matched']): mism += 1
        r['cover'] = cov
        per = {}
        for e in cov:
            cs = [s for s in e['info']['sets'] if s['cover']]
            b = any(s['bounded'] for s in cs)
            lbs = [s['lb'] for s in cs if s['bounded']]
            per.setdefault(e['gid'], {'bounded': False, 'ranges': [], 'lb': []})
            per[e['gid']]['bounded'] |= b; per[e['gid']]['ranges'].append(e['range']); per[e['gid']]['lb'] += lbs
        r['per_adv'] = per
        r['all_unbounded'] = bool(r['label']) and not any(v['bounded'] for v in per.values())
    assert mism == 0, mism
    res['label_reproduction'] = {'rows_checked': len(ROWS), 'matched_set_mismatches': mism}

    # effective lower bound: bounded but lower bound <= earliest published non-prerelease version of the package
    def ver_le(a, b):
        pa = [int(x) for x in re.match(r'(\d+)\.(\d+)\.(\d+)', a).groups()]; pb = [int(x) for x in re.match(r'(\d+)\.(\d+)\.(\d+)', b).groups()]
        return pa <= pb
    for r in ROWS:
        if not r['label']: continue
        eff = []
        for g, v in r['per_adv'].items():
            mv = MINV.get(r['package'])
            eff.append(v['bounded'] and not (mv and v['lb'] and all(ver_le(l, mv) for l in v['lb'])))
        r['all_eff_unbounded'] = not any(eff)

    # ---- Check 2 descriptives
    POS = [r for r in ROWS if r['label']]
    c2 = {'definition': ('A matched advisory is "bounded" for an instance if a comparator set of its GHSA range that covers used_version has a '
                         '>=, > or exact lower bound > 0.0.0 (node semver Range parse, commas -> spaces as in src/semver_batch.cjs); '
                         'otherwise "unbounded below" (e.g. "< 4.17.21", "<= x", ">= 0.0.0, < y", "> 0.0.0"). An instance is '
                         '"unbounded-only" if ALL its matched advisories are unbounded. Secondary rule "effectively unbounded": also counts a '
                         'bounded range whose lower bound is <= the lowest non-prerelease version ever published for the package (npm cache).'),
          'per_snapshot': {}}
    snaps = sorted(DATA.origin.unique())
    for o in snaps:
        P = [r for r in POS if r['origin'] == o]
        advs = {}
        for r in P:
            for g, v in r['per_adv'].items(): advs.setdefault((g, r['package']), v['bounded'])
        c2['per_snapshot'][o] = {'positives': len(P), 'unbounded_only': sum(r['all_unbounded'] for r in P),
                                 'share_unbounded_only': sum(r['all_unbounded'] for r in P) / len(P),
                                 'effectively_unbounded_only': sum(r['all_eff_unbounded'] for r in P),
                                 'share_effectively_unbounded_only': sum(r['all_eff_unbounded'] for r in P) / len(P),
                                 'mixed_unbounded_and_bounded': sum((not r['all_unbounded']) and any(not v['bounded'] for v in r['per_adv'].values()) for r in P),
                                 'unique_matched_advisory_package_pairs': len(advs), 'unique_pairs_unbounded': sum(not b for b in advs.values()),
                                 'packages_with_unbounded_only_positives': len({r['package'] for r in P if r['all_unbounded']}),
                                 # overlap with round-3 F-3 group: every matched advisory has nvd_published_at <= origin
                                 'all_nvd_pre_origin': sum(all(ADV[g].get('nvd_published_at') and pd.Timestamp(ADV[g]['nvd_published_at']) <= cut(o) for g in r['matched']) for r in P),
                                 'all_nvd_pre_origin_and_unbounded_only': sum(r['all_unbounded'] and all(ADV[g].get('nvd_published_at') and pd.Timestamp(ADV[g]['nvd_published_at']) <= cut(o) for g in r['matched']) for r in P),
                                 'top_packages_unbounded_only': pd.Series([r['package'] for r in P if r['all_unbounded']]).value_counts().head(8).to_dict()}
    tot = len(POS); c2['overall'] = {'positives': tot, 'unbounded_only': sum(r['all_unbounded'] for r in POS),
                                     'share_unbounded_only': sum(r['all_unbounded'] for r in POS) / tot,
                                     'effectively_unbounded_only': sum(r['all_eff_unbounded'] for r in POS)}
    bpairs = {(g, r['package']): v['lb'] for r in POS for g, v in r['per_adv'].items() if v['bounded']}
    c2['overall']['unique_bounded_advisory_package_pairs'] = len(bpairs)
    c2['overall']['bounded_pairs_with_lower_bound_below_1_0_0'] = sorted(f'{g} {p} >= {min(l)}' for (g, p), l in bpairs.items() if l and all(x.startswith('0.') for x in l))

    # ---- Check 1: NVD
    def verdict(r, gids):
        out = []
        for g in gids:
            s = sel[(g, r['package'])]
            if s['status'] != 'usable': out.append({'gid': g, 'status': s['status'], 'level': s.get('level')}); continue
            ev = J['nvd'][nidx[(r['used_version'], g, r['package'])]]
            known = [x for x in ev if x['aff'] is not None]
            out.append({'gid': g, 'status': 'usable', 'level': s['level'], 'aff': any(x['aff'] for x in known) if known else None,
                        'whys': sorted({x['why'] for x in known}), 'coerced': any(x['coerced'] for x in ev), 'star': s['all_versions_star']})
        return out
    for r in ROWS:
        r['nvd'] = verdict(r, r['matched'] if r['label'] else sorted({e['gid'] for e in r['win']}))
    # advisory-level status table
    adv_rows = []
    for (g, p), s in sorted(sel.items()):
        adv_rows.append({'ghsa_id': g, 'package': p, 'cves': ';'.join(s.get('cves', [])), 'status': s['status'], 'match_level': s.get('level', ''),
                         'nvd_vulnStatus': s.get('vulnStatus', ''), 'nvd_products': ';'.join(s.get('products', [])),
                         'nvd_ranges': nvd_str(s['entries']) if s['status'] == 'usable' else '', 'ghsa_ranges': ' | '.join(e['range'] for e in ENT[p] if e['gid'] == g),
                         'role': 'matched_positive' if any(g in r['matched'] for r in ROWS if r['package'] == p) else 'hard_negative_only'})
    for (g, p), st in zip(sets_keys, J['sets']):
        row = next(a for a in adv_rows if a['ghsa_id'] == g and a['package'] == p); row.update({f'vs_{k}': (';'.join(v) if isinstance(v, list) else v) for k, v in st.items()})
    with (H / 'nvd_advisory_status.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(dict.fromkeys(k for a in adv_rows for k in a))); w.writeheader(); w.writerows(adv_rows)

    def cov_block(keys):
        st = pd.Series([sel[k]['status'] for k in keys]).value_counts().to_dict()
        lv = pd.Series([sel[k].get('level') for k in keys if sel[k]['status'] == 'usable']).value_counts().to_dict()
        return {'n': len(keys), 'with_cve': sum(sel[k]['status'] != 'no_cve' for k in keys), 'status_counts': st, 'usable_match_level_counts': lv,
                'nvd_has_configurations': sum(sel[k]['status'] not in ('no_cve', 'not_fetched', 'nvd_not_found', 'rejected', 'no_configurations') for k in keys)}
    c1 = {'source': 'NVD CVE API 2.0, raw JSON cached in verification/range_checks/cache/nvd/',
          'matching_heuristic': ('vulnerable=true CPE matches with part "a" (non-negated nodes); product matched to the npm name after lower-casing and '
                                 'removing non-alphanumerics: "exact" = product equals the package name (or scope+name for scoped packages); '
                                 '"affix" = equal after stripping a leading "node" and trailing "js" (min. 3 chars); otherwise (ambiguous, reported separately) '
                                 '"fallback_name_overlap" = exactly one application product whose compact name contains or is contained in the package name (>= 4 chars, e.g. lodash-es -> lodash), '
                                 'else "fallback_single_product" = the CVE lists exactly one application product; '
                                 'among matched entries only target_sw in {node.js, nodejs, node, npm, *, -} are kept; entries with version "-" and no bounds are unusable. '
                                 'NVD bounds are compared with npm semver ordering (non-semver bounds coerced, flagged). An advisory with several usable entries is '
                                 '"affected" if any entry covers used_version.'),
          'primary_levels': ['exact', 'affix'], 'inclusive_levels': ['exact', 'affix', 'fallback_name_overlap', 'fallback_single_product']}
    pos_keys = sorted({(g, r['package']) for r in POS for g in r['matched']})
    hn = [r for r in ROWS if not r['label']]
    hn_keys = sorted({(e['gid'], r['package']) for r in hn for e in r['win']})
    c1['coverage'] = {'positive_matched_advisories': cov_block(pos_keys), 'hard_negative_advisories': cov_block(hn_keys),
                      'all_advisories': cov_block(sorted(set(pos_keys) | set(hn_keys)))}
    def row_cov(rows):
        return {'rows': len(rows), 'any_advisory_with_cve': sum(any(x['status'] != 'no_cve' for x in r['nvd']) for r in rows),
                'any_usable_primary': sum(any(x['status'] == 'usable' and x['level'] in ('exact', 'affix') and x['aff'] is not None for x in r['nvd']) for r in rows),
                'any_usable_inclusive': sum(any(x['status'] == 'usable' and x['aff'] is not None for x in r['nvd']) for r in rows)}
    c1['row_coverage'] = {o: {'positives': row_cov([r for r in POS if r['origin'] == o]), 'hard_negatives': row_cov([r for r in hn if r['origin'] == o])} for o in snaps}
    c1['row_coverage']['all'] = {'positives': row_cov(POS), 'hard_negatives': row_cov(hn)}

    def row_verdict(r, levels):
        us = [x for x in r['nvd'] if x['status'] == 'usable' and x['level'] in levels and x['aff'] is not None]
        if not us: return None
        return any(x['aff'] for x in us)
    agree = {}
    for tag, levels in (('primary', ('exact', 'affix')), ('inclusive', ('exact', 'affix', 'fallback_name_overlap', 'fallback_single_product'))):
        blk = {}
        for o in snaps + ['all']:
            P = [r for r in POS if o in ('all', r['origin'])]; N = [r for r in hn if o in ('all', r['origin'])]
            pv = [row_verdict(r, levels) for r in P]; nv = [row_verdict(r, levels) for r in N]
            pv = [v for v in pv if v is not None]; nv = [v for v in nv if v is not None]
            # unique (package, used_version, advisory) triples
            def triples(rows, want):
                t = {}
                for r in rows:
                    for x in r['nvd']:
                        if x['status'] == 'usable' and x['level'] in levels and x['aff'] is not None: t[(r['package'], r['used_version'], x['gid'])] = x['aff']
                return rate(sum(v == want for v in t.values()), len(t))
            blk[o] = {'positives_nvd_affected': rate(sum(pv), len(pv)), 'hard_negatives_nvd_not_affected': rate(sum(not v for v in nv), len(nv)),
                      'positive_triples_nvd_affected': triples(P, True), 'hard_negative_triples_nvd_not_affected': triples(N, False)}
        agree[tag] = blk
    c1['agreement'] = agree
    c1['agreement_note'] = ('rows are clustered (the same package/version/advisory appears in many projects); Wilson intervals treat rows as independent, '
                            'so the unique (package, used_version, advisory) triples are the more honest denominator')
    # advisory-level version-set comparison
    vs = []
    for (g, p), st in zip(sets_keys, J['sets']):
        vs.append({'gid': g, 'pkg': p, 'level': sel[(g, p)]['level'], **st})
    def vs_summary(items):
        return {'n': len(items), 'identical_version_sets': sum(x['ghsa_only'] == 0 and x['nvd_only'] == 0 for x in items),
                'nvd_superset_strict': sum(x['ghsa_only'] == 0 and x['nvd_only'] > 0 for x in items),
                'nvd_subset_strict': sum(x['ghsa_only'] > 0 and x['nvd_only'] == 0 for x in items),
                'both_differ': sum(x['ghsa_only'] > 0 and x['nvd_only'] > 0 for x in items),
                'median_jaccard': float(np.median([x['both'] / max(1, x['ghsa'] + x['nvd'] - x['both']) for x in items])) if items else None}
    c1['advisory_version_sets'] = {'method': 'all published non-prerelease npm versions of the package (cache/npm) evaluated against the GHSA range(s) of that advisory and the selected NVD entries',
                                   'primary': vs_summary([x for x in vs if x['level'] in ('exact', 'affix')]), 'inclusive': vs_summary(vs)}
    # Check 2 x NVD: are unbounded GHSA ranges also unbounded in NVD?
    ub = {}
    for r in POS:
        for g, v in r['per_adv'].items():
            s = sel[(g, r['package'])]
            if s['status'] == 'usable' and s['level'] in ('exact', 'affix'):
                ev = J['nvd'][nidx[(r['used_version'], g, r['package'])]]
                covering = [m for m, x in zip(s['entries'], ev) if x['aff']]
                if not covering: nv = 'nvd_not_affected'
                elif any(not (m['si'] or m['se']) and (any(m[k] for k in ('ei', 'ee')) or m['ver'] == '*') for m in covering): nv = 'nvd_covering_entry_unbounded_below'
                else: nv = 'nvd_covering_entry_lower_bounded_or_exact'
                ub[(g, r['package'], r['used_version'])] = ('ghsa_bounded' if v['bounded'] else 'ghsa_unbounded', nv)
    c1['unbounded_vs_nvd'] = {'unit': 'unique (advisory, package, used_version) of positives with usable primary NVD entries; NVD entries that cover used_version are inspected',
                              'crosstab': {f'{a}|{b}': int(n) for (a, b), n in pd.Series(list(ub.values())).value_counts().items()}}
    # disagreements -> CSV (unique package/version/advisory, with row counts)
    dis = {}; rowset = {}
    for r in ROWS:
        for x in r['nvd']:
            if x['status'] != 'usable' or x['aff'] is None: continue
            ghsa_aff = bool(r['label']) and x['gid'] in r['matched']
            if r['label'] and not ghsa_aff: continue
            if x['aff'] == ghsa_aff: continue
            if r['label'] and row_verdict(r, ('exact', 'affix', 'fallback_name_overlap', 'fallback_single_product')):
                kind = 'positive_advisory_level_only'   # another matched advisory of this row is NVD-affected
            else:
                kind = 'positive' if r['label'] else 'hard_negative'
            k = (kind, r['package'], r['used_version'], x['gid'])
            s = sel[(x['gid'], r['package'])]
            ents = [e for e in r['win_eval'] if e['gid'] == x['gid']]
            if r['label']:
                cat = {'below_lower': 'NVD narrower: NVD lower bound above used_version', 'at_or_above_upper': 'NVD narrower: NVD upper bound at/below used_version',
                       'exact_other': 'NVD lists explicit versions only; used_version not listed'}
                parts = {p for w in x['whys'] for p in w.split('+')}
                if parts - {'exact_other'}: parts.discard('exact_other')   # explicit (e.g. beta) versions listed next to ranges: the ranges decide
                c = '; '.join(sorted(cat.get(p, p) for p in parts))
            else:
                gw = sorted({s2['why'] for e in ents for s2 in e['info']['sets'] if not s2['cover']})
                gtxt = 'GHSA excludes: ' + ('used_version below GHSA lower bound' if all('below_lower' in w for w in gw) else
                                             'used_version at/above GHSA fix' if all('at_or_above_upper' in w and 'below_lower' not in w for w in gw) else '/'.join(gw))
                ntxt = 'NVD lists all versions (*)' if 'all_versions' in x['whys'] else ('NVD exact version listed' if 'exact_match' in x['whys'] else 'NVD range includes used_version')
                c = 'NVD broader: ' + ntxt + '; ' + gtxt
            if s['level'].startswith('fallback'): c += '; product matched only by ' + s['level']
            if x['coerced']: c += '; NVD version coerced to semver'
            d = dis.setdefault(k, {'kind': kind, 'package': r['package'], 'used_version': r['used_version'], 'ghsa_id': x['gid'], 'cves': ';'.join(s['cves']),
                                   'nvd_match_level': s['level'], 'ghsa_range': ' | '.join(e['range'] for e in ents),
                                   'nvd_range': nvd_str(s['entries']), 'category': c, 'nvd_vulnStatus': s.get('vulnStatus'), 'rows': 0, 'origins': set(), 'projects': set()})
            d['rows'] += 1; d['origins'].add(r['origin']); d['projects'].add(r['project'])
            rowset.setdefault(kind, {})[r['i']] = r
    drows = [dict(v, origins=';'.join(sorted(v['origins'])), projects=len(v['projects'])) for v in dis.values()]
    drows.sort(key=lambda x: (x['kind'], x['package'], x['used_version'], x['ghsa_id']))
    cols = ['kind', 'package', 'used_version', 'ghsa_id', 'cves', 'ghsa_range', 'nvd_range', 'category', 'nvd_match_level', 'nvd_vulnStatus', 'rows', 'projects', 'origins']
    with (H / 'nvd_disagreements.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(drows)
    c1['disagreements'] = {'unique_rows_in_csv': len(drows), 'by_kind': pd.Series([d['kind'] for d in drows]).value_counts().to_dict(),
                           'row_advisory_pairs_by_kind': {k: int(sum(d['rows'] for d in drows if d['kind'] == k)) for k in {d['kind'] for d in drows}},
                           'distinct_instances_by_kind': {k: len(v) for k, v in rowset.items()},
                           'distinct_instances_by_kind_and_snapshot': {k: pd.Series([r['origin'] for r in v.values()]).value_counts().sort_index().to_dict() for k, v in rowset.items()},
                           'mean_libyear_of_disagreeing_instances': {k: {o: float(np.mean([r['libyear'] for r in v.values() if r['origin'] == o])) for o in sorted({r['origin'] for r in v.values()})} for k, v in rowset.items()},
                           'by_category': pd.Series([d['category'] for d in drows]).value_counts().to_dict(), 'list': drows}
    res['check1_nvd'] = c1
    res['check2_unbounded'] = c2
    print('Check 1 primary agreement (all):', json.dumps(agree['primary']['all'], default=str), flush=True)
    print('Check 2 overall:', c2['overall'], flush=True)

    # ---- Check 2 backtests and libyear effect sizes
    D = DATA.copy()
    flag = np.zeros(len(D), bool); eflag = np.zeros(len(D), bool)
    for r in POS: flag[r['i']] = r['all_unbounded']; eflag[r['i']] = r['all_eff_unbounded']
    D['unb'] = flag; D['eunb'] = eflag
    res['check2_backtests'] = backtests(D)
    res['check2_libyear'] = libyear_effects(D)

    def conv(x):
        if isinstance(x, (np.integer,)): return int(x)
        if isinstance(x, (np.floating,)): return float(x)
        if isinstance(x, (np.bool_,)): return bool(x)
        if isinstance(x, set): return sorted(x)
        raise TypeError(type(x))
    (H / 'range_checks_results.json').write_text(json.dumps(res, indent=1, ensure_ascii=False, default=conv, allow_nan=False) + '\n', encoding='utf-8')
    print('done ->', H / 'range_checks_results.json', flush=True)


# ------------------------------------------------------------------ backtest machinery (copied from verification/round3/round3_analyses.py)
def backtests(D):
    import sklearn, xgboost
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score as AP, roc_auc_score as AUC
    from xgboost import XGBClassifier
    assert xgboost.__version__ == '3.0.5'
    spec = importlib.util.spec_from_file_location('rq_executed', RQ / 'executed_source.py')
    EX = importlib.util.module_from_spec(spec); spec.loader.exec_module(EX)
    score_plan, fast_ap = EX.score_plan, EX.fast_ap
    CFG = json.loads((RQ / 'executed_config.json').read_text(encoding='utf-8'))
    FEAT = CFG['features']; ORG = CFG['origins'][1:]; SEED = CFG['seed']; B = CFG['bootstrap_repeats']
    REF = {(r['origin'], r['model']): r for r in json.loads((RQ / 'metrics.json').read_text(encoding='utf-8'))}
    IV = {(r['origin'], r['model_a'], r['model_b']): r for r in json.loads((RQ / 'intervals.json').read_text(encoding='utf-8')) if r['cluster_unit'] == 'package'}

    def model(alg):
        clf = {'lr': LogisticRegression, 'rf': RandomForestClassifier, 'xgb': XGBClassifier}[alg](**CFG['models'][alg])
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
        codes, n = plan
        pos = np.bincount(codes, weights=w * y, minlength=n); neg = np.bincount(codes, weights=w * (1 - y), minlength=n)
        below = neg.sum() - np.cumsum(neg)
        return float((pos * (below + .5 * neg)).sum() / (pos.sum() * neg.sum()))
    rng = np.random.default_rng(47)
    for _ in range(20):
        y = rng.integers(0, 2, 60); s = rng.choice([.1, .3, .5, .8], 60); w = rng.integers(0, 4, 60).astype(float)
        if w @ y and w @ (1 - y):
            assert math.isclose(fast_auc(y, w, score_plan(s)), AUC(y, s, sample_weight=w), abs_tol=1e-12)
            assert math.isclose(fast_ap(y, w, score_plan(s)), AP(y, s, sample_weight=w), abs_tol=1e-12)
    ALGS = ('lr', 'rf', 'xgb')
    SPECS = {**{f'full_{a}': (a, FEAT) for a in ALGS}, **{f'drop_libyear_{a}': (a, [f for f in FEAT if f != 'libyear']) for a in ALGS},
             'libyear_only_lr': ('lr', ['libyear'])}
    PAIRS = [(f'full_{a}', f'drop_libyear_{a}') for a in ALGS] + [(f'full_{a}', 'libyear_only_lr') for a in ALGS]

    def run(frame):
        out = {}
        for o in ORG:
            te = frame[frame.origin == o]; tr = frame[(frame.origin < o) & (frame.window_end <= o)]
            assert tr.origin.max() < o and tr.window_end.max() <= o
            y = te.label.to_numpy(int); scores = {}
            for name, (alg, cols) in SPECS.items():
                scores[name] = model(alg).fit(tr[cols], tr.label).predict_proba(te[cols])[:, 1]
            scores['libyear_gt_1.0'] = (te.libyear.to_numpy() > 1.0).astype(float)
            plans = {n: score_plan(s) for n, s in scores.items() if n != 'libyear_gt_1.0'}
            names, codes = np.unique(te['package'], return_inverse=True); rngb = np.random.default_rng(SEED); samp = []
            for _ in range(B):
                w = np.bincount(rngb.integers(0, len(names), len(names)), minlength=len(names))[codes].astype(float)
                if not (w @ y) or not (w @ (1 - y)): continue
                samp.append({n: (fast_ap(y, w, p), fast_auc(y, w, p)) for n, p in plans.items()})
            ci = {}
            for a, b in PAIRS:
                dap = np.array([s[a][0] - s[b][0] for s in samp]); dauc = np.array([s[a][1] - s[b][1] for s in samp])
                ci[f'{a}-{b}'] = {'d_ap': float(AP(y, scores[a]) - AP(y, scores[b])), 'd_ap_ci': [float(np.quantile(dap, .025)), float(np.quantile(dap, .975))],
                                  'd_auc': float(AUC(y, scores[a]) - AUC(y, scores[b])), 'd_auc_ci': [float(np.quantile(dauc, .025)), float(np.quantile(dauc, .975))],
                                  'valid_repeats': len(samp)}
            out[o] = {'train_n': int(len(tr)), 'train_pos': int(tr.label.sum()), 'test_n': int(len(te)), 'test_pos': int(y.sum()), 'prevalence': float(y.mean()),
                      'models': {n: metrics(y, s) for n, s in scores.items()}, 'package_cluster_ci': ci}
        return out
    bt = {'protocol': 'executed_source.py fixed parameters, expanding window (train origins < test, window_end <= test origin), seed 42; '
                      'package-cluster bootstrap 1,000 draws, default_rng(42) per origin, np.unique cluster order, draws without both classes skipped; '
                      'recall10 = stable order top ceil(0.1n) as executed_source.py, recall10_expected = tie-aware expectation (relevant for the 0/1 libyear>1 rule)'}
    import scipy
    bt['versions'] = {'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__, 'scipy': scipy.__version__, 'xgboost': xgboost.__version__}
    main = run(D)
    rep = {}
    for o in ORG:
        for m in list(SPECS) + ['libyear_gt_1.0']:
            ref = REF[(o, m)]; now = main[o]['models'][m]
            rep[f'{o}:{m}'] = {'ap': abs(ref['ap'] - now['ap']), 'auc': abs(ref['roc_auc'] - now['roc_auc']), 'recall': abs(ref['recall_at_budget'] - now['recall10'])}
        for a in ALGS:
            for b in (f'drop_libyear_{a}', 'libyear_only_lr'):
                iv = IV.get((o, f'full_{a}', b))
                if iv: rep[f'{o}:ci:full_{a}-{b}'] = {'ci': max(abs(iv['ci_low'] - main[o]['package_cluster_ci'][f'full_{a}-{b}']['d_ap_ci'][0]),
                                                              abs(iv['ci_high'] - main[o]['package_cluster_ci'][f'full_{a}-{b}']['d_ap_ci'][1]))}
    mx = {k: max(v.get(k, 0) for v in rep.values()) for k in ('ap', 'auc', 'recall', 'ci')}
    assert mx['ap'] < 1e-12 and mx['auc'] < 1e-12 and mx['recall'] < 1e-12 and mx['ci'] < 1e-12, mx
    bt['reproduction'] = {'max_abs_diff_vs_metrics_and_intervals_json': mx, 'rows': rep}
    bt['main'] = main; print('Reproduced main metrics/CIs exactly', mx, flush=True)
    variants = {'A_drop_unbounded_only_positives': D[~((D.label == 1) & D.unb)],
                'B_relabel0_unbounded_only_positives': D.assign(label=np.where((D.label == 1) & D.unb, 0, D.label))}
    if (D.unb != D.eunb).any():   # secondary rule only run when it flags different instances
        variants.update({'A_eff_drop_effectively_unbounded_only_positives': D[~((D.label == 1) & D.eunb)],
                         'B_eff_relabel0_effectively_unbounded_only_positives': D.assign(label=np.where((D.label == 1) & D.eunb, 0, D.label))})
    bt['secondary_rule_flags_same_instances'] = bool((D.unb == D.eunb).all())
    for name, frame in variants.items():
        bt[name] = run(frame); print('backtest', name, 'done', flush=True)
    return bt


def libyear_effects(D):
    from sklearn.metrics import roc_auc_score as AUC
    def d(pos, neg):
        pos, neg = np.asarray(pos, float), np.asarray(neg, float)
        sp = np.sqrt(((len(pos) - 1) * pos.var(ddof=1) + (len(neg) - 1) * neg.var(ddof=1)) / (len(pos) + len(neg) - 2)); return float((pos.mean() - neg.mean()) / sp)
    out = {'definition': 'Cohen d with pooled SD (ddof=1), instance level (every row) and unique package/version level, as thesis Table 5.10; '
                         'libyear AUC = P(libyear_pos > libyear_neg) with ties 1/2'}
    for o, g in D.groupby('origin'):
        neg = g[g.label == 0]; pos = g[g.label == 1]; pu = pos[pos.unb]; pb = pos[~pos.unb]; peu = pos[pos.eunb]; peb = pos[~pos.eunb]
        def auc(p, n): return float(AUC(np.r_[np.ones(len(p)), np.zeros(len(n))], np.r_[p.libyear, n.libyear])) if len(p) else None
        gB = g.assign(label=np.where(g.unb & (g.label == 1), 0, g.label))
        def pair(frame):
            u = frame.groupby(['package', 'used_version']).agg(label=('label', 'max'), libyear=('libyear', 'first'), ly_sd=('libyear', 'std')).reset_index()
            return u
        uM = pair(g); uA = pair(g[~((g.label == 1) & g.unb)]); uB = pair(gB)
        out[o] = {'n_negatives': int(len(neg)), 'n_pos': int(len(pos)), 'n_pos_unbounded_only': int(len(pu)), 'n_pos_bounded': int(len(pb)),
                  'mean_libyear': {'negatives': float(neg.libyear.mean()), 'positives_all': float(pos.libyear.mean()),
                                   'positives_unbounded_only': float(pu.libyear.mean()) if len(pu) else None, 'positives_bounded': float(pb.libyear.mean()) if len(pb) else None,
                                   'positives_effectively_unbounded_only': float(peu.libyear.mean()) if len(peu) else None,
                                   'positives_effectively_bounded': float(peb.libyear.mean()) if len(peb) else None},
                  'median_libyear': {'positives_unbounded_only': float(pu.libyear.median()) if len(pu) else None, 'positives_bounded': float(pb.libyear.median()) if len(pb) else None},
                  'd_instance': {'main': d(pos.libyear, neg.libyear), 'A_without_unbounded_only': d(pb.libyear, neg.libyear),
                                 'B_unbounded_only_relabelled_0': d(gB[gB.label == 1].libyear, gB[gB.label == 0].libyear),
                                 'unbounded_only_vs_negatives': d(pu.libyear, neg.libyear) if len(pu) > 1 else None,
                                 'A_eff_without_effectively_unbounded_only': d(peb.libyear, neg.libyear) if len(peb) > 1 else None},
                  'auc_libyear_instance': {'main': auc(pos, neg), 'A_without_unbounded_only': auc(pb, neg), 'unbounded_only_vs_negatives': auc(pu, neg)},
                  'd_unique_package_version': {'main': d(uM[uM.label == 1].libyear, uM[uM.label == 0].libyear), 'A_without_unbounded_only': d(uA[uA.label == 1].libyear, uA[uA.label == 0].libyear),
                                               'B_unbounded_only_relabelled_0': d(uB[uB.label == 1].libyear, uB[uB.label == 0].libyear),
                                               'n_pos_pairs': {'main': int(uM.label.sum()), 'A': int(uA.label.sum()), 'B': int(uB.label.sum())},
                                               'max_within_pair_libyear_sd': float(uM.ly_sd.fillna(0).max())}}
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('stage', choices=['fetch', 'analyze']); a = ap.parse_args()
    fetch() if a.stage == 'fetch' else analyze()
