from pathlib import Path
import csv,json,hashlib,math
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'publication/experiments/lockfile_sensitivity'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def key(r):return tuple(r[k] for k in ['origin','project','package','dependency_type'])
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ap(y,s):
    groups={}
    for t,v in zip(y,s):
        n,p=groups.get(v,(0,0));groups[v]=(n+1,p+t)
    seen=hits=area=0
    for v in sorted(groups,reverse=True):
        n,p=groups[v];seen+=n;hits+=p;area+=p*hits/seen
    return area/sum(y)
m=load(OUT/'manifest.json');assert digest(ROOT/'src/publication_lockfile_sensitivity.py')==digest(OUT/'executed_source.py')==m['script_sha256']
for p,h in m['inputs'].items():assert digest(Path(p))==h,p
a=read(OUT/'inferred_matched.csv');b=read(OUT/'recorded.csv');assert [key(r) for r in a]==[key(r) for r in b]
assert len(a)==13512 and all(r['used_version']==r['recorded_lockfile_version'] for r in b)
assert all(r['window_end']<= '2024-12-31' and r['used_version_date'][:10]<=r['origin'] for r in b)
metrics=load(OUT/'metrics.json');lookup={(r['arm'],r['origin'],r['model']):r for r in metrics};checked=0;observations=0
for arm,data in [('inferred_matched',a),('recorded',b)]:
    source={key(r):r for r in data}
    for origin in ['2021-12-31','2022-12-31','2023-12-31']:
        rows=read(OUT/(arm+'_'+origin+'_predictions.csv'));assert {key(r) for r in rows}=={key(r) for r in data if r['origin']==origin}
        assert all(r['used_version']==source[key(r)]['used_version'] and int(r['label'])==int(source[key(r)]['label']) for r in rows)
        y=[int(r['label']) for r in rows];names=[k for k in rows[0] if k not in ['origin','project','package','dependency_type','used_version','label']]
        assert len(names)==9
        for name in names:
            metric=lookup[(arm,origin,name)];assert metric['train_n']==sum(r['origin']<origin and r['window_end']<=origin for r in data)
            assert math.isclose(ap(y,[float(r[name]) for r in rows]),metric['ap'],abs_tol=1e-12)
            checked+=1
        observations+=len(rows)
cis=load(OUT/'intervals.json');assert len(cis)==72
for row in cis:
    expected=lookup[(row['arm'],row['origin'],row['model_a'])]['ap']-lookup[(row['arm'],row['origin'],row['model_b'])]['ap']
    assert math.isclose(expected,row['ap_difference'],abs_tol=1e-12) and row['valid_repeats']==1000 and row['ci_low']<=row['ci_high']
result={'passed':True,'matched_observations_across_all_origins':len(a),'independent_ap_checks':checked,'test_observations_across_two_arms':observations,'intervals_checked':len(cis),'labels_changed_instances':sum(int(x['label'])!=int(y['label']) for x,y in zip(a,b)),'protected_inputs_verified':True}
(OUT/'artifact_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
