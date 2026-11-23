"""Descriptive review diagnostics on frozen data/predictions; no refitting."""
from pathlib import Path
import csv,json,math,hashlib,collections
R=Path(__file__).resolve().parents[1];P=R/'publication';C=P/'experiments/rq_completion'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
data=R/'robustness/data/date_12_paired.csv';rows=read(data);cfg=load(P/'protocol/rq_completion.json')
result={'status':'exploratory_descriptive_review_of_existing_outputs_not_new_model_validation','inputs':[],'units':[],'budget_rows':[],'brier_skill_rows':[]}
for origin in cfg['origins']:
    sub=[r for r in rows if r['origin']==origin];groups=collections.defaultdict(list)
    for r in sub:groups[(r['package'],r['used_version'])].append(r)
    result['units'].append({'origin':origin,'instances':len(sub),'distinct_package_versions':len(groups),'extra_repeated_instance_rows':len(sub)-len(groups),'groups_with_multiple_feature_vectors':sum(len({tuple(x[f] for f in cfg['features']) for x in group})>1 for group in groups.values()),'groups_with_multiple_labels':sum(len({x['label'] for x in group})>1 for group in groups.values()),'positive_version_groups':sum(any(int(x['label']) for x in group) for group in groups.values())})
metrics=load(C/'metrics.json')
for origin in cfg['origins'][1:]:
    path=C/origin/'predictions_wide.csv';pred=read(path);n=len(pred);pos=sum(int(r['label']) for r in pred);k=math.ceil(n*.1)
    result['inputs'].append({'path':path.relative_to(R).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ['full_'+a for a in ['lr','rf','xgb']]+['drop_libyear_'+a for a in ['lr','rf','xgb']]+['libyear_only_'+a for a in ['lr','rf','xgb']]+['libyear_score','constant_training_rate','libyear_gt_1.0']:
        scored=[(float(r[name]),int(r['label'])) for r in pred];ordered=sorted(scored,key=lambda p:-p[0]);cut=ordered[k-1][0]
        above=[y for s,y in scored if s>cut];tied=[y for s,y in scored if s==cut];slots=k-len(above)
        observed=sum(y for _,y in ordered[:k]);expected=sum(above)+slots*sum(tied)/len(tied)
        recorded=next(r for r in metrics if r['origin']==origin and r['model']==name)
        assert recorded['top_k']==k and recorded['top_k_hits']==observed,(origin,name)
        assert sum(above)+max(0,slots-(len(tied)-sum(tied)))<=expected<=sum(above)+min(slots,sum(tied))
        result['budget_rows'].append({'origin':origin,'model':name,'test_n':n,'positives':pos,'k':k,'stable_order_hits':observed,'stable_order_precision':observed/k,'stable_order_recall':observed/pos,'selected_label_zero':k-observed,'missed_positive_instances':pos-observed,'expected_random_hits':k*pos/n,'stable_order_lift_over_random':observed/(k*pos/n),'cutoff_tie_size':len(tied),'cutoff_tie_slots':slots,'tie_randomized_expected_hits':expected,'tie_min_hits':sum(above)+max(0,slots-(len(tied)-sum(tied))),'tie_max_hits':sum(above)+min(slots,sum(tied))})
    baseline=next(r for r in metrics if r['origin']==origin and r['model']=='constant_training_rate')['brier']
    for name in ['full_lr','full_rf','full_xgb']:
        brier=next(r for r in metrics if r['origin']==origin and r['model']==name)['brier']
        result['brier_skill_rows'].append({'origin':origin,'model':name,'brier':brier,'constant_training_rate_brier':baseline,'brier_skill_vs_training_rate':1-brier/baseline})
result['inputs'].append({'path':data.relative_to(R).as_posix(),'sha256':hashlib.sha256(data.read_bytes()).hexdigest()})
result['interpretation']='Tie min/max are combinatorial bounds, not confidence intervals. Tie expectation assumes uniform selection independent of labels within the tied cutoff. Lift and counts are retrospective label-based ranking summaries, not developer effort or incidents prevented. Brier skill does not isolate calibration.'
result['checks']={'all_36_top_budget_counts_match_saved_metrics':len(result['budget_rows'])==36,'original_input_hashes_recorded':True}
(P/'reviews/four_step_diagnostics.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'units':result['units'],'first_origin_lr_budget':result['budget_rows'][0],'brier_skill_rows':result['brier_skill_rows']},indent=2))
