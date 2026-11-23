"""Independent standard-library verification of persisted completion predictions."""
from pathlib import Path
import csv,json,hashlib,math
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'publication/experiments/rq_completion'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def readcsv(p):
    with p.open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))
def key(r):return tuple(r[x] for x in ['origin','project','package','dependency_type','used_version'])
def ap(y,s):
    grouped={}
    for target,score in zip(y,s):
        total,positive=grouped.get(score,(0,0));grouped[score]=(total+1,positive+target)
    cumulative=hits=area=0
    for score in sorted(grouped,reverse=True):
        n,p=grouped[score];cumulative+=n;hits+=p;area+=p*hits/cumulative
    return area/sum(y)
manifest=load(OUT/'frozen_manifest.json');cfg=load(OUT/'executed_config.json')
assert digest(OUT/'executed_source.py')==manifest['script_sha256']
assert digest(ROOT/'src/publication_completion.py')==manifest['script_sha256']
assert digest(OUT/'executed_config.json')==manifest['config_sha256']
assert digest(ROOT/'publication/protocol/rq_completion.json')==manifest['config_sha256']
for path,h in manifest['protected_inputs'].items():assert digest(Path(path))==h,path
data=readcsv(ROOT/'robustness/data/date_12_paired.csv');lookup={key(r):r for r in data}
metrics=load(OUT/'metrics.json');mapping={(r['origin'],r['model']):r for r in metrics};brier_errors=[]
importance=load(OUT/'importance.json');intervals=load(OUT/'intervals.json');nrows=0;checks=0
for origin in cfg['origins'][1:]:
    folder=OUT/origin;marker=load(folder/'complete.json');pred=readcsv(folder/'predictions_wide.csv')
    assert digest(folder/'predictions_wide.csv')==marker['prediction_sha256']
    assert len(pred)==sum(r['origin']==origin for r in data)==marker['test_n']
    assert {key(r) for r in pred}=={key(r) for r in data if r['origin']==origin}
    assert all(r['label']==lookup[key(r)]['label'] for r in pred)
    assert marker['train_n']==sum(r['origin']<origin and r['window_end']<=origin for r in data)
    y=[int(r['label']) for r in pred];models=[k for k in pred[0] if k not in ['origin','project','package','dependency_type','used_version','label']]
    assert len(models)==marker['models_and_scores']==38
    for name in models:
        score=[float(r[name]) for r in pred];m=mapping[(origin,name)]
        assert all(math.isfinite(s) for s in score)
        if name!='libyear_score':assert all(0<=s<=1 for s in score)
        assert math.isclose(ap(y,score),m['ap'],abs_tol=1e-12),(origin,name,'AP')
        budget=math.ceil(len(pred)*cfg['inspection_budget_fraction']);order=sorted(range(len(y)),key=lambda i:-score[i])[:budget]
        assert sum(y[i] for i in order)==m['top_k_hits'] and budget==m['top_k']
        if name.startswith('libyear_gt_'):
            threshold=float(name.removeprefix('libyear_gt_'))
            assert score==[float(float(lookup[key(r)]['libyear'])>threshold) for r in pred]
        if name!='libyear_score':
            p=[int(s>=.5) for s in score];tp=sum(t==1 and z==1 for t,z in zip(y,p));fp=sum(t==0 and z==1 for t,z in zip(y,p));fn=sum(t==1 and z==0 for t,z in zip(y,p));tn=len(y)-tp-fp-fn
            assert [m[k] for k in ['tn','fp','fn','tp']]==[tn,fp,fn,tp]
            brier=sum((s-t)**2 for s,t in zip(score,y))/len(y)
            brier_errors.append(abs(brier-m['brier']))
            # XGBoost emits float32; sklearn preserves float32 in its Brier
            # reduction, while the independent CSV computation uses doubles.
            tolerance=2e-8 if name.endswith('_xgb') else 1e-12
            assert math.isclose(brier,m['brier'],abs_tol=tolerance),(origin,name,'Brier',brier,m['brier'],brier-m['brier'])
        checks+=1
    nrows+=len(pred)
for r in importance:
    full=mapping[(r['origin'],'full_'+r['algorithm'])]['ap'];drop=mapping[(r['origin'],'drop_'+r['feature']+'_'+r['algorithm'])]['ap']
    assert math.isclose(r['delta_ap'],full-drop,abs_tol=1e-12)
for origin in cfg['origins'][1:]:
    for algorithm in cfg['models']:
        ranked=sorted([r for r in importance if r['origin']==origin and r['algorithm']==algorithm],key=lambda r:r['rank'])
        assert len(ranked)==9 and all(a['delta_ap']>=b['delta_ap'] for a,b in zip(ranked,ranked[1:]))
assert len(importance)==81 and len(intervals)==234
for r in intervals:
    assert r['ci_low']<=r['ci_high'] and r['valid_repeats']==1000
    point=mapping[(r['origin'],r['model_a'])]['ap']-mapping[(r['origin'],r['model_b'])]['ap']
    assert math.isclose(point,r['ap_difference'],abs_tol=1e-12)
result={'passed':True,'test_observation_rows':nrows,'score_values':nrows*38,'independently_recomputed_model_metrics':checks,'importance_rows':len(importance),'interval_rows':len(intervals),'max_independent_brier_absolute_error':max(brier_errors),'xgb_brier_float32_tolerance':2e-8,'prediction_coverage_verified':True,'threshold_rules_verified':True,'training_window_coverage_verified':True,'source_config_and_protected_hashes_verified':True}
(OUT/'artifact_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
