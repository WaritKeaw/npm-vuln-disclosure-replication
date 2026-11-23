"""Validate actual datasets, time bounds, predictions and source immutability."""
from pathlib import Path
from datetime import datetime
import csv,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(name):
    with (ROOT/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
cfg=load(ROOT/'config/experiment.json');manifest=load(ROOT/'manifests/dataset.json')
paired=read('data/processed/paired.csv');available=read('data/processed/all_available.csv')
key=lambda r:(r['origin'],r['project'],r['package'],r['dependency_type'])
assert len(set(map(key,paired)))==len(paired),'duplicate dependency keys'
all_keys=set(map(key,available));assert all(key(r) in all_keys for r in paired)
sets=[]
for origin in cfg['origins']:
    rows=[r for r in paired if r['origin']==origin]
    projects={r['project'] for r in rows};sets.append(projects)
    assert len(projects)==manifest['paired_projects']
    for r in rows:
        assert r['package'] and r['project']
        cutoff=datetime.fromisoformat(origin+'T23:59:59.999+00:00')
        for col in ['used_version_date','latest_version_date']:
            assert datetime.fromisoformat(r[col].replace('Z','+00:00'))<=cutoff
        assert float(r['libyear'])>=0
        assert r['label'] in ['0','1']
        assert bool(r['matched_ghsa_ids'])==(r['label']=='1')
        assert r['window_end']==str(int(origin[:4])+1)+origin[4:]
assert all(s==sets[0] for s in sets)
assert load(ROOT/'cache/ghsa/complete.json')['complete'] is True
metrics=load(ROOT/'results/temporal_metrics.json');predictions=read('results/predictions.csv')
for metric in metrics:
    if metric.get('status')!='ok':continue
    origin=metric['origin'];test=[r for r in paired if r['origin']==origin]
    train=[r for r in paired if r['origin']<origin and r['window_end']<=origin]
    assert metric['train_instances']==len(train) and metric['n']==len(test)
    assert metric['training_origins']==';'.join(sorted({r['origin'] for r in train}))
    preds=[r for r in predictions if r['origin']==origin and r['model']==metric['model']]
    assert len(preds)==len(test) and set(map(key,preds))==set(map(key,test))
    assert all(r['label'] in ['0','1'] for r in preds)
    assert 0<=metric['average_precision']<=1 and 0<=metric['roc_auc']<=1
for result in load(ROOT/'results/paired_ap_differences.json'):
    assert 0<result['valid_bootstrap_repeats']<=cfg['bootstrap_repeats']
    assert result['ci_2_5']<=result['ci_97_5']
for source,old_hash in load(ROOT/'manifests/source_hashes.json').items():
    assert digest(ROOT.parent/source)==old_hash,source
run=load(ROOT/'manifests/run.json')
assert run['dataset_sha256']==digest(ROOT/'data/processed/paired.csv')
collection=load(ROOT/'manifests/snapshot_collection.json')
assert len(collection['statuses'])==1000
assert len({(r['project'],r['origin']) for r in collection['statuses']})==1000
for field in ['script_sha256','semver_script_sha256']:
    assert digest(ROOT/run['archived_'+field])==run[field]
summary={'passed':True,'origins':cfg['origins'],'paired_projects':manifest['paired_projects'],'paired_instances':len(paired),'prediction_rows':len(predictions),'original_source_hashes_unchanged':True,'checks':['unique keys','paired cohort identity','feature publication cutoff','fixed label horizon','complete GHSA pagination','prediction coverage','training window maturity','metric ranges','paired interval ordering','dataset and original hashes']}
(ROOT/'manifests/validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
