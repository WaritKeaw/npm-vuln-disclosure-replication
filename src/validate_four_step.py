"""Independent standard-library checks of follow-up predictions and result arithmetic."""
from pathlib import Path
from collections import defaultdict
import csv,json,hashlib,math
R=Path(__file__).resolve().parents[1];P=R/'publication';O=P/'experiments/four_step'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def close(a,b,tol=1e-10):assert a is b if a is None or b is None else abs(a-b)<=tol,(a,b)
def independent(records,name,q):
    levels=defaultdict(lambda:[0,0]);positive=0
    for r in records:
        y=int(r['label']);levels[float(r[name])][0]+=1;levels[float(r[name])][1]+=y;positive+=y
    n=len(records);k=math.ceil(n*q-1e-10);cp=ct=0;ap=0.;hits=None;win=0.;neg=0
    for s,(count,pos) in sorted(levels.items(),reverse=True):
        cp+=pos;ct+=count
        if positive:ap+=pos*cp/ct/positive
        if hits is None and ct>=k:hits=cp-pos+(k-(ct-count))*pos/count
    for s,(count,pos) in sorted(levels.items()):win+=pos*(neg+(count-pos)*.5);neg+=count-pos
    return {'n':n,'positive':positive,'budget_n':k,'hits':hits,'precision':hits/k,'recall':hits/positive if positive else None,'ap':ap if positive else None,'roc_auc':win/(positive*(n-positive)) if 0<positive<n else None,'brier':sum((float(r[name])-int(r['label']))**2 for r in records)/n}
cfg=load(P/'protocol/four_step_followup.json');base=load(P/'protocol/rq_completion.json');fit=load(O/'fit_manifest.json');ev=load(O/'evaluation_manifest.json')
assert sha(R/'src/four_step_fit.py')==fit['source_sha256']==sha(O/'executed_fit.py')
assert sha(R/'src/four_step_evaluate.py')==ev['source_sha256']==sha(O/'executed_evaluate.py')
assert sha(P/'protocol/four_step_followup.json')==fit['protocol_sha256']==ev['protocol_sha256']
assert sha(R/'robustness/data/date_12_paired.csv')==fit['primary_data_sha256']
for relative,h in ev['inputs'].items():assert sha(R/relative)==h
for relative,h in load(O/'audit_validation.json')['inputs'].items():assert sha(R/relative)==h
byorigin={};points=load(O/'budget_points.json');cache={};coverage=0;metric_checks=0
for origin in base['origins'][1:]:
    original=read(P/'experiments/rq_completion'/origin/'predictions_wide.csv');extra=read(O/'new_scores'/(origin+'.csv'))
    keys=['origin','project','package','dependency_type','used_version','label']
    assert [tuple(r[k] for k in keys) for r in original]==[tuple(r[k] for k in keys) for r in extra]
    records=[{**a,**b} for a,b in zip(original,extra)];byorigin[origin]=records;coverage+=len(records)
    unique={}
    for r in records:unique.setdefault((r['package'],r['used_version']),r)
    for row in [r for r in points if r['origin']==origin]:
        selected=records if row['view']=='instance' else list(unique.values())
        stat=independent(selected,row['model'],row['budget_fraction']);cache[(origin,row['view'],row['model'],row['budget_fraction'])]=stat
        for key in ['n','positive','budget_n','hits','precision','recall','ap']:close(row[key],stat[key])
        metric_checks+=1
for row in load(O/'new_model_metrics.json'):
    path=O/('new_scores/'+row['origin']+'.csv' if row['variant']=='comparators' else 'training_sensitivity/'+row['variant']+'/'+row['origin']+'.csv')
    records=read(path);stat=independent(records,row['model'],.1)
    for key in ['ap','roc_auc','brier']:close(row[key],stat[key],2e-8 if key=='brier' and row['model'].endswith('_xgb') else 1e-10)
    assert len(records)==row['test_n'] and stat['positive']==row['positive'];metric_checks+=1
details=read(O/'project_budget_details.csv');macros=load(O/'project_budget_summary.json');macrocache={}
project_records={}
for origin,records in byorigin.items():
    grouped=defaultdict(list)
    for row in records:grouped[row['project']].append(row)
    for project,group in grouped.items():project_records[(origin,project)]=group
for row in details:
    expected=independent(project_records[(row['origin'],row['project'])],row['model'],float(row['budget_fraction']))
    for key in ['n','positive','budget_n','hits','precision','recall','ap']:
        actual=None if row[key]=='' else float(row[key]);close(actual,expected[key])
for row in macros:
    selected=[r for r in details if r['origin']==row['origin'] and r['model']==row['model'] and float(r['budget_fraction'])==row['budget_fraction']]
    values={key:[float(r[key]) for r in selected if r[key]!=''] for key in ['ap','hits','precision','recall']}
    assert len(selected)==row['projects'] and len(values['recall'])==row['positive_projects']
    means={k:sum(v)/len(v) for k,v in values.items()}
    for key,field in [('ap','mean_ap_positive_projects'),('hits','mean_hits_per_project'),('precision','mean_precision'),('recall','mean_recall_positive_projects')]:close(means[key],row[field])
    macrocache[(row['origin'],row['model'],row['budget_fraction'])]=means
for interval in load(O/'budget_intervals.json'):
    origin=interval['origin'];view=interval['view'];q=interval['budget_fraction'];a=interval['model_a'];b=interval['model_b'];measure=interval['measure'].replace('delta_','')
    if view=='macro_project':left=macrocache[(origin,a,q)];right=macrocache[(origin,b,q)]
    else:left=cache[(origin,view,a,q)];right=cache[(origin,view,b,q)]
    close(interval['point'],left[measure]-right[measure])
    assert math.isfinite(interval['ci_low']) and interval['ci_low']<=interval['ci_high'] and interval['valid_repeats']>=900
ledger=load(O/'training_sensitivity_ledger.json');sensitivity=load(O/'new_model_metrics.json')
assert len(ledger)==9 and sum(r['status']=='not_estimable' for r in ledger)==2
for origin in base['origins'][2:]:
    a=next(r for r in ledger if r['origin']==origin and r['variant']=='lag_30_days');b=next(r for r in ledger if r['origin']==origin and r['variant']=='lag_90_days')
    assert a['training_signature']==b['training_signature'] and b['prediction_alias']=='lag_30_days'
traces=load(O/'lockfile_label_traces.json');assert len(traces)==32 and all(r['inferred_label']!=r['recorded_label'] for r in traces)
for path,h in load(R/'robustness/manifests/protected_inputs.json').items():assert sha(Path(path))==h,path
assert load(O/'fit_validation.json')['new_fits']==39
result={'passed':True,'protected_inputs_and_executed_source_hashes_unchanged':True,'new_fit_count':39,'test_observations_checked':coverage,'point_and_new_model_metric_entries_checked':metric_checks,'project_detail_rows_independently_checked':len(details),'macro_summaries_checked':len(macros),'interval_point_differences_checked':len(load(O/'budget_intervals.json')),'label_disagreement_traces_checked':32,'lag_aliases_and_not_estimable_tests_reported':True,'limits':'Checks result arithmetic, ordered coverage and provenance. Does not prove bootstrap coverage, archived metadata or independent vulnerability adjudication.'}
(O/'artifact_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
