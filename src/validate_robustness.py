"""Validate saved robustness artifacts without rerunning any model."""
from pathlib import Path
from datetime import datetime
import csv,hashlib,json,math
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'robustness'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def key(r):return r['origin'],r['project'],r['package'],r['dependency_type']
config=load(OUT/'config/analysis.json');datasets=load(OUT/'manifests/datasets.json');counts={};pred_count=0
for path,expected in load(OUT/'manifests/protected_inputs.json').items():assert sha(Path(path))==expected,path
maps={}
for info in datasets:
    v=info['variant'];name=v['id'];data=OUT/'data'/(name+'.csv');rows=read(data);mapping={key(r):r for r in rows};maps[name]=mapping
    assert len(mapping)==len(rows) and sha(data)==info['data_sha256']
    for r in rows:
        assert r['label'] in ['0','1'] and bool(r['matched_ghsa_ids'])==(r['label']=='1')
        cutoff=datetime.fromisoformat(r['origin']+'T23:59:59.999+00:00')
        assert datetime.fromisoformat(r['used_version_date'].replace('Z','+00:00'))<=cutoff
        assert datetime.fromisoformat(r['latest_version_date'].replace('Z','+00:00'))<=cutoff
        assert (float(r['raw_libyear'])<0)==bool(int(r['negative_libyear']))
        if v['clamp_negative']:assert math.isclose(float(r['libyear']),max(0,float(r['raw_libyear'])),abs_tol=1e-12)
        if v['latest_rule']=='publication_date':assert float(r['libyear'])>=0
    folder=OUT/'results'/name;complete=load(folder/'complete.json')
    assert complete['data_sha256']==sha(data) and complete['config_sha256']==sha(OUT/'config/analysis.json')
    assert complete['script_sha256']==sha(ROOT/'src/robustness_analysis.py')
    predictions=read(folder/'predictions.csv');pred_count+=len(predictions);preds={}
    for r in predictions:preds.setdefault((r['origin'],r['model']),[]).append(r)
    for r in load(folder/'metrics.json'):
        if 'model' not in r:continue
        origin=r['origin'];train=[x for x in rows if x['origin']<origin and x['window_end']<=origin];test=[x for x in rows if x['origin']==origin]
        assert len(train)==r['train_n'] and len(test)==r['test_n']
        p=preds[(origin,r['model'])];assert len(p)==len(test) and {key(x) for x in p}=={key(x) for x in test}
        assert all(x['label']==mapping[key(x)]['label'] for x in p)
        assert 0<=r['ap']<=1 and 0<=r['roc_auc']<=1
    for filename in ['associations.json','ap_differences.json']:
        for r in load(folder/filename):
            assert 0<=r['valid_repeats']<=config['bootstrap_repeats']
            if r['ci_low'] is not None:assert r['ci_low']<=r['ci_high']
    counts[name]=len(rows)
for short,long in [('date_6_paired','date_12_paired'),('semver_6_clamped','semver_12_clamped')]:
    assert maps[short].keys()==maps[long].keys()
    for k,r in maps[short].items():
        assert int(r['label'])<=int(maps[long][k]['label'])
        assert r['used_version']==maps[long][k]['used_version']
for name in ['semver_12_signed','semver_12_clamped','semver_6_clamped']:
    assert maps[name].keys()==maps['date_12_paired'].keys()
    assert all(r['used_version']==maps['date_12_paired'][k]['used_version'] for k,r in maps[name].items())
result={'passed':True,'variant_rows':counts,'prediction_rows':pred_count,'protected_inputs_unchanged':True,'horizon_labels_nested':True,'prediction_and_training_coverage_verified':True,'source_hashes_verified':True}
(OUT/'manifests/artifact_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
