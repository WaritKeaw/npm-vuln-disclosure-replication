"""Offline paired budget/weighting/calibration evaluation of fixed predictions."""
from pathlib import Path
from datetime import datetime,timezone
import csv,json,sys,hashlib,math
R=Path(__file__).resolve().parents[1];P=R/'publication';O=P/'experiments/four_step';sys.path[:0]=[str(P/'tools/vendor'),str(R/'tools/vendor')]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def csvwrite(p,rows):
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)
def run():
    import numpy as np,pandas as pd
    from scipy.stats import spearmanr
    from sklearn.metrics import average_precision_score
    cfg=load(P/'protocol/four_step_followup.json');base=load(P/'protocol/rq_completion.json')
    assert load(O/'fit_validation.json')['passed'] and load(O/'audit_validation.json')['passed']
    frozen={'source_sha256':sha(Path(__file__)),'protocol_sha256':sha(P/'protocol/four_step_followup.json'),'inputs':{},'started_at':datetime.now(timezone.utc).isoformat()}
    assert not (O/'evaluation_manifest.json').exists(),'Do not overwrite a frozen evaluation.'
    inputs=[O/'fit_manifest.json',O/'new_model_metrics.json',R/'robustness/data/date_12_paired.csv']
    for origin in base['origins'][1:]:inputs += [P/'experiments/rq_completion'/origin/'predictions_wide.csv',O/'new_scores'/(origin+'.csv')]
    frozen['inputs']={p.relative_to(R).as_posix():sha(p) for p in inputs};save(O/'evaluation_manifest.json',frozen);(O/'executed_evaluate.py').write_bytes(Path(__file__).read_bytes())
    names=['full_'+a for a in ['lr','rf','xgb']]+['drop_libyear_'+a for a in ['lr','rf','xgb']]+['libyear_only_'+a for a in ['lr','rf','xgb']]+['libyear_score','constant_training_rate']+['libyear_gt_'+str(t) for t in base['threshold_baseline_years']]+['package_age_only_lr','recency_only_lr']+['drop_lag_recency_family_'+a for a in ['lr','rf','xgb']]
    pairs=[('full_'+a,b+'_'+a) for a in ['lr','rf','xgb'] for b in ['drop_libyear','libyear_only','drop_lag_recency_family']]+[('full_lr',b) for b in ['package_age_only_lr','recency_only_lr']]
    def plan(s):
        levels,codes=np.unique(s,return_inverse=True);return len(levels)-1-codes,len(levels)
    def stats(y,w,pl,budget):
        codes,n=pl;pos=np.bincount(codes,weights=w*y,minlength=n);counts=np.bincount(codes,weights=w,minlength=n);cp=np.cumsum(pos);ct=np.cumsum(counts);total=counts.sum();positive=pos.sum()
        if total==0:return None
        ap=float((np.divide(cp,ct,out=np.zeros(n),where=ct>0)*pos).sum()/positive) if positive else None
        k=min(int(round(total)),max(1,math.ceil(total*budget-1e-10)));index=int(np.searchsorted(ct,k,side='left'));before=ct[index-1] if index else 0.;ph=cp[index-1] if index else 0.
        assert counts[index]>0
        hits=float(ph+(k-before)*pos[index]/counts[index]);assert -1e-8<=hits<=k+1e-8
        return {'ap':ap,'n':float(total),'positive':float(positive),'budget_n':k,'hits':hits,'precision':hits/k,'recall':hits/positive if positive else None,'lift':hits/(k*positive/total) if positive else None,'selected_label_zero':k-hits,'missed_positives':positive-hits,'cutoff_tie_weight':float(counts[index]),'cutoff_slots':float(k-before)}
    # Weighted AP and cutoff ties checked against a separate implementation and hand case.
    rng=np.random.default_rng(19)
    for _ in range(12):
        y=rng.integers(0,2,50);s=rng.choice([.1,.2,.7],50);w=rng.integers(0,4,50)
        if w@y:assert abs(stats(y,w,plan(s),.1)['ap']-average_precision_score(y,s,sample_weight=w))<1e-12
    hand=stats(np.array([1,0,1,0]),np.ones(4),plan(np.ones(4)),.5);assert hand['hits']==1 and hand['precision']==.5
    allpoints=[];allintervals=[];allmacro=[];projectrows=[];calibration=[];brier=[];slices=[];correlations=[];primary= pd.read_csv(R/'robustness/data/date_12_paired.csv',keep_default_na=False)
    for origin in base['origins'][1:]:
        frame=primary[primary.origin==origin].reset_index(drop=True)
        pred=pd.read_csv(P/'experiments/rq_completion'/origin/'predictions_wide.csv',keep_default_na=False);extra=pd.read_csv(O/'new_scores'/(origin+'.csv'),keep_default_na=False)
        keys=['origin','project','package','dependency_type','used_version','label'];assert frame[keys].equals(pred[keys]) and frame[keys].equals(extra[keys])
        for name in names:frame[name]=(extra if name in extra else pred)[name]
        y=frame.label.to_numpy(int);scores={name:frame[name].to_numpy(float) for name in names};plans={name:plan(s) for name,s in scores.items()}
        unique=(~frame.duplicated(['package','used_version'])).to_numpy(float)
        assert all(frame.groupby(['package','used_version'])[name].nunique().max()==1 for name in names)
        pn,pc=np.unique(frame.package,return_inverse=True);jn,jc=np.unique(frame.project,return_inverse=True)
        pointmap={}
        for view,weights in [('instance',np.ones(len(frame))),('unique_package_version_origin',unique)]:
            for name in names:
                for q in cfg['budgets']:
                    row={'origin':origin,'view':view,'model':name,'budget_fraction':q,**stats(y,weights,plans[name],q)};allpoints.append(row)
                    if q==cfg['focal_budget']:pointmap[(view,name)]=row
        train=primary[(primary.origin<origin)&(primary.window_end<=origin)];seen=set(train.package)
        for subset,weights in [('seen',frame.package.isin(seen).to_numpy(float)),('unseen',(~frame.package.isin(seen)).to_numpy(float))]:
            for name in names:
                point=stats(y,weights,plans[name],cfg['focal_budget'])
                if point:slices.append({'origin':origin,'slice':subset,'model':name,**point})
        # Project-specific budgets: report all-project precision/hits and positive-project recall/AP.
        perproject={name:{key:[] for key in ['ap','hits','precision','recall']} for name in names}
        for project in jn:
            mask=frame.project.to_numpy()==project;local_y=y[mask]
            for name in names:
                local=plan(scores[name][mask])
                for q in cfg['budgets']:
                    stat=stats(local_y,np.ones(mask.sum()),local,q);projectrows.append({'origin':origin,'project':str(project),'model':name,'budget_fraction':q,**stat})
                    if q==cfg['focal_budget']:
                        for key in perproject[name]:perproject[name][key].append(stat[key])
        for name in names:
            selected=[r for r in projectrows if r['origin']==origin and r['model']==name]
            for q in cfg['budgets']:
                selected_q=[r for r in selected if r['budget_fraction']==q]
                valid=lambda key:[r[key] for r in selected_q if r[key] is not None]
                allmacro.append({'origin':origin,'view':'macro_project','model':name,'budget_fraction':q,'projects':len(selected_q),'positive_projects':len(valid('recall')),'total_selected':sum(r['budget_n'] for r in selected_q),'mean_ap_positive_projects':float(np.mean(valid('ap'))),'mean_hits_per_project':float(np.mean(valid('hits'))),'mean_precision':float(np.mean(valid('precision'))),'mean_recall_positive_projects':float(np.mean(valid('recall')))})
        for view,unit in [('instance','package'),('instance','project'),('instance','package_times_project_pigeonhole'),('unique_package_version_origin','package')]:
            rng=np.random.default_rng(cfg['seed']);draws={(a,b):{k:[] for k in ['ap','hits','precision','recall']} for a,b in pairs}
            for _ in range(cfg['bootstrap_repeats']):
                if unit=='project':w=np.bincount(rng.integers(0,len(jn),len(jn)),minlength=len(jn))[jc]
                else:
                    w=np.bincount(rng.integers(0,len(pn),len(pn)),minlength=len(pn))[pc]
                    if unit=='package_times_project_pigeonhole':w=w*np.bincount(rng.integers(0,len(jn),len(jn)),minlength=len(jn))[jc]
                if view=='unique_package_version_origin':w=w*unique
                if not(w@y) or not(w@(1-y)):continue
                values={name:stats(y,w,plans[name],cfg['focal_budget']) for name in names}
                for a,b in pairs:
                    for k in draws[(a,b)]:draws[(a,b)][k].append(values[a][k]-values[b][k])
            for (a,b),measures in draws.items():
                for key,values in measures.items():
                    assert len(values)>=cfg['bootstrap_repeats']*.9
                    allintervals.append({'origin':origin,'view':view,'cluster_unit':unit,'model_a':a,'model_b':b,'measure':'delta_'+key,'point':pointmap[(view,a)][key]-pointmap[(view,b)][key],'ci_low':float(np.quantile(values,.025)),'ci_high':float(np.quantile(values,.975)),'valid_repeats':len(values),'budget_fraction':cfg['focal_budget']})
            print('Budget bootstrap',origin,view,unit,flush=True)
        rng=np.random.default_rng(cfg['seed']);macrodraws={(a,b,k):[] for a,b in pairs for k in ['ap','hits','precision','recall']}
        vectors={name:{key:np.array([np.nan if v is None else v for v in values]) for key,values in measure.items()} for name,measure in perproject.items()}
        for _ in range(cfg['bootstrap_repeats']):
            counts=np.bincount(rng.integers(0,len(jn),len(jn)),minlength=len(jn))
            for (a,b,key),values in macrodraws.items():
                delta=vectors[a][key]-vectors[b][key];valid=np.isfinite(delta)
                if counts[valid].sum():values.append(float(np.average(delta[valid],weights=counts[valid])))
        for (a,b,key),values in macrodraws.items():
            delta=vectors[a][key]-vectors[b][key];assert len(values)>=900
            allintervals.append({'origin':origin,'view':'macro_project','cluster_unit':'project','model_a':a,'model_b':b,'measure':'delta_'+key,'point':float(np.nanmean(delta)),'ci_low':float(np.quantile(values,.025)),'ci_high':float(np.quantile(values,.975)),'valid_repeats':len(values),'budget_fraction':cfg['focal_budget'],'positive_projects_only':key in ['ap','recall']})
        # Score-probability summaries; deterministic binary rules and raw Libyear excluded.
        baseline=float(np.mean((scores['constant_training_rate']-y)**2));edges=np.array([0,.01,.02,.05,.1,.2,.5,1.])
        for name,s in scores.items():
            if name=='libyear_score' or name.startswith('libyear_gt_'):continue
            loss=float(np.mean((s-y)**2));brier.append({'origin':origin,'model':name,'brier':loss,'constant_training_rate_brier':baseline,'brier_skill':1-loss/baseline})
            bins=np.clip(np.searchsorted(edges,s,side='right')-1,0,len(edges)-2)
            for i in range(len(edges)-1):
                selected=bins==i
                calibration.append({'origin':origin,'model':name,'bin_low':float(edges[i]),'bin_high':float(edges[i+1]),'n':int(selected.sum()),'positive':int(y[selected].sum()),'mean_score':float(s[selected].mean()) if selected.any() else None,'observed_rate':float(y[selected].mean()) if selected.any() else None})
        corr=spearmanr(frame[base['features']].to_numpy(float),axis=0).statistic
        correlations.append({'origin':origin,'features':base['features'],'spearman':[[float(v) if np.isfinite(v) else None for v in row] for row in corr]})
    for name,value in [('budget_points',allpoints),('budget_intervals',allintervals),('project_budget_summary',allmacro),('seen_unseen_metrics',slices),('calibration_bins',calibration),('brier_skill',brier),('feature_correlations',correlations)]:save(O/(name+'.json'),value)
    csvwrite(O/'project_budget_details.csv',projectrows)
    for relative,h in frozen['inputs'].items():assert sha(R/relative)==h,relative
    assert sha(Path(__file__))==frozen['source_sha256']
    save(O/'evaluation_validation.json',{'passed':True,'budget_point_rows':len(allpoints),'interval_rows':len(allintervals),'macro_project_rows':len(allmacro),'project_detail_rows':len(projectrows),'minimum_valid_repeats':min(r['valid_repeats'] for r in allintervals),'weighted_ap_and_tie_checks_passed':True,'inputs_and_source_unchanged':True,'completed_at':datetime.now(timezone.utc).isoformat()})
    print('Completed paired budget/unit/calibration evaluation',flush=True)
if __name__=='__main__':run()
