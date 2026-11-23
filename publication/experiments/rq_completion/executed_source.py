"""Complete original RQ3/4 on the unchanged reference dataset. No tuning."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,csv,hashlib,json,sys,math
ROOT=Path(__file__).resolve().parents[1];PUB=ROOT/'publication';OUT=PUB/'experiments/rq_completion'
sys.path[:0]=[str(PUB/'tools/vendor'),str(ROOT/'tools/vendor')]
CONFIG=PUB/'protocol/rq_completion.json'
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def csvwrite(p,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',encoding='utf-8',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=fields);w.writeheader();w.writerows(rows)
def score_plan(scores):
    import numpy as np
    levels,codes=np.unique(scores,return_inverse=True)
    return len(levels)-1-codes,len(levels)
def fast_ap(y,w,plan):
    import numpy as np
    codes,n=plan;pos=np.bincount(codes,weights=w*y,minlength=n);total=np.bincount(codes,weights=w,minlength=n)
    cp=np.cumsum(pos);ct=np.cumsum(total)
    return float((np.divide(cp,ct,out=np.zeros(n),where=ct>0)*pos).sum()/pos.sum())
def checks():
    import numpy as np
    from sklearn.metrics import average_precision_score
    import xgboost,sklearn,scipy,pandas
    rng=np.random.default_rng(47)
    for _ in range(15):
        y=rng.integers(0,2,50);s=rng.choice([.1,.3,.8],50);w=rng.integers(0,5,50)
        if w@y and w@(1-y):assert math.isclose(fast_ap(y,w,score_plan(s)),average_precision_score(y,s,sample_weight=w),abs_tol=1e-12)
    assert [int(x>.25) for x in [.249,.25,.251]]==[0,0,1]
    assert xgboost.__version__=='3.0.5'
    print('Checks passed; XGB',xgboost.__version__,'sklearn',sklearn.__version__,flush=True)
def intervals(frame,scores,pairs,unit,cfg):
    import numpy as np
    y=frame.label.to_numpy(int);names,codes=np.unique(frame[unit],return_inverse=True)
    rng=np.random.default_rng(cfg['seed']);plans={name:score_plan(score) for name,score in scores.items()}
    samples={pair:[] for pair in pairs}
    for _ in range(cfg['bootstrap_repeats']):
        counts=np.bincount(rng.integers(0,len(names),len(names)),minlength=len(names));w=counts[codes]
        if not(w@y) or not(w@(1-y)):continue
        ap={name:fast_ap(y,w,plan) for name,plan in plans.items()}
        for pair in pairs:samples[pair].append(ap[pair[0]]-ap[pair[1]])
    result=[]
    for (a,b),values in samples.items():
        assert len(values)>=cfg['bootstrap_repeats']*.9
        result.append({'model_a':a,'model_b':b,'cluster_unit':unit,'valid_repeats':len(values),'ci_low':float(np.quantile(values,.025)),'ci_high':float(np.quantile(values,.975))})
    return result
def run():
    import numpy as np,pandas as pd,sklearn,xgboost,scipy
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss,confusion_matrix
    from xgboost import XGBClassifier
    cfg=load(CONFIG);data=ROOT/'robustness/data/date_12_paired.csv';features=cfg['features']
    OUT.mkdir(parents=True,exist_ok=True)
    protected=load(ROOT/'robustness/manifests/protected_inputs.json')
    protected[str(data)]=digest(data);protected[str(ROOT/'robustness/config/analysis.json')]=digest(ROOT/'robustness/config/analysis.json')
    frozen={'config_sha256':digest(CONFIG),'script_sha256':digest(__file__),'dataset_sha256':digest(data),'protected_inputs':protected,'versions':{'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'scipy':scipy.__version__,'xgboost':xgboost.__version__},'started_at':datetime.now(timezone.utc).isoformat(),'status':'exploratory_after_prior_results'}
    manifest=OUT/'frozen_manifest.json'
    if manifest.exists():
        prior=load(manifest)
        for k in ['config_sha256','script_sha256','dataset_sha256']:assert prior[k]==frozen[k],k
    else:
        save(manifest,frozen)
        (OUT/'executed_source.py').write_bytes(Path(__file__).read_bytes())
        (OUT/'executed_config.json').write_bytes(CONFIG.read_bytes())
    frame=pd.read_csv(data,keep_default_na=False)
    baseline=load(ROOT/'robustness/results/date_12_paired/metrics.json')
    allmetrics=[];allimportance=[];allintervals=[];allnative=[];replication=[]
    for origin in cfg['origins'][1:]:
        folder=OUT/origin;folder.mkdir(exist_ok=True)
        done=folder/'complete.json'
        if done.exists():
            marker=load(done);assert marker['config_sha256']==digest(CONFIG) and marker['script_sha256']==digest(__file__)
            for name,target in [('metrics',allmetrics),('importance',allimportance),('intervals',allintervals),('native',allnative),('replication',replication)]:target.extend(load(folder/(name+'.json')))
            print('Resume completed origin',origin,flush=True);continue
        test=frame[frame.origin==origin].copy();train=frame[(frame.origin<origin)&(frame.window_end<=origin)].copy();y=test.label.to_numpy(int)
        assert train.origin.max()<origin and train.window_end.max()<=origin
        scores={};native=[];metrics=[];importance=[];reproduce=[]
        factories={'lr':lambda:LogisticRegression(**cfg['models']['lr']),'rf':lambda:RandomForestClassifier(**cfg['models']['rf']),'xgb':lambda:XGBClassifier(**cfg['models']['xgb'])}
        for algorithm,factory in factories.items():
            specs=[('full_'+algorithm,features),('libyear_only_'+algorithm,['libyear'])]+[('drop_'+feature+'_'+algorithm,[f for f in features if f!=feature]) for feature in features]
            for name,columns in specs:
                model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),factory())
                model.fit(train[columns],train.label)
                scores[name]=model.predict_proba(test[columns])[:,1]
                if name=='full_'+algorithm:
                    clf=model.steps[-1][1]
                    values=clf.coef_[0] if algorithm=='lr' else clf.feature_importances_
                    for f,value in zip(columns,values):native.append({'origin':origin,'algorithm':algorithm,'feature':f,'native_type':'standardized_coefficient' if algorithm=='lr' else ('impurity_importance' if algorithm=='rf' else 'normalized_gain'),'value':float(value)})
                print('Fit',origin,name,flush=True)
        for threshold in cfg['threshold_baseline_years']:scores['libyear_gt_'+str(threshold)]=(test.libyear.to_numpy()>threshold).astype(float)
        scores['libyear_score']=test.libyear.to_numpy(float)
        scores['constant_training_rate']=np.full(len(test),train.label.mean())
        for name,s in scores.items():
            predicted=(s>.5).astype(int) if name=='libyear_score' else (s>=cfg['model_operating_threshold']).astype(int)
            # The raw Libyear score has no probability interpretation or implicit threshold.
            tn,fp,fn,tp=map(int,confusion_matrix(y,predicted,labels=[0,1]).ravel())
            k=math.ceil(len(test)*cfg['inspection_budget_fraction']);top=np.argsort(-s,kind='stable')[:k];hits=int(y[top].sum())
            row={'origin':origin,'model':name,'train_n':len(train),'test_n':len(test),'positive':int(y.sum()),'prevalence':float(y.mean()),'ap':float(average_precision_score(y,s)),'roc_auc':float(roc_auc_score(y,s)),'top_k':k,'top_k_hits':hits,'precision_at_budget':hits/k,'recall_at_budget':hits/int(y.sum())}
            if name!='libyear_score':row.update({'brier':float(brier_score_loss(y,s)),'threshold':cfg['model_operating_threshold'],'tn':tn,'fp':fp,'fn':fn,'tp':tp,'precision':tp/(tp+fp) if tp+fp else 0.,'recall':tp/(tp+fn),'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.})
            metrics.append(row)
        ap={r['model']:r['ap'] for r in metrics}
        for algorithm in factories:
            for feature in features:importance.append({'origin':origin,'algorithm':algorithm,'feature':feature,'delta_ap':ap['full_'+algorithm]-ap['drop_'+feature+'_'+algorithm]})
            ranked=sorted([r for r in importance if r['algorithm']==algorithm],key=lambda r:-r['delta_ap'])
            for rank,r in enumerate(ranked,1):r['rank']=rank
        pairs=[]
        for algorithm in factories:
            pairs += [('full_'+algorithm,'drop_'+f+'_'+algorithm) for f in features]
            pairs += [('full_'+algorithm,'libyear_only_'+algorithm)]
            pairs += [('full_'+algorithm,'libyear_gt_'+str(t)) for t in cfg['threshold_baseline_years']]
        ci=[]
        for unit in cfg['cluster_units']:
            ci.extend({'origin':origin,'ap_difference':ap[a]-ap[b],**r} for r in intervals(test,scores,pairs,unit,cfg) for a,b in [(r['model_a'],r['model_b'])])
            print('Bootstrap',origin,unit,'complete',flush=True)
        for algorithm in ['lr','rf']:
            for name,oldname in [('full_'+algorithm,'full_'+algorithm),('libyear_only_'+algorithm,'libyear_only_'+algorithm),('drop_libyear_'+algorithm,'other_features_'+algorithm)]:
                old=next(r for r in baseline if r.get('model')==oldname and r['origin']==origin)
                difference=abs(ap[name]-old['ap']);assert difference<1e-10,(origin,name,difference)
                reproduce.append({'origin':origin,'model':name,'absolute_ap_difference':difference})
        pred=test[['origin','project','package','dependency_type','used_version','label']].copy()
        for name,s in scores.items():pred[name]=s
        pred.to_csv(folder/'predictions_wide.csv',index=False)
        for name,obj in [('metrics',metrics),('importance',importance),('intervals',ci),('native',native),('replication',reproduce)]:save(folder/(name+'.json'),obj)
        save(done,{'config_sha256':digest(CONFIG),'script_sha256':digest(__file__),'prediction_sha256':digest(folder/'predictions_wide.csv'),'train_n':len(train),'test_n':len(test),'models_and_scores':len(scores),'completed_at':datetime.now(timezone.utc).isoformat()})
        allmetrics.extend(metrics);allimportance.extend(importance);allintervals.extend(ci);allnative.extend(native);replication.extend(reproduce)
    for name,obj in [('metrics',allmetrics),('importance',allimportance),('intervals',allintervals),('native',allnative),('replication',replication)]:save(OUT/(name+'.json'),obj)
    for p,h in protected.items():assert digest(p)==h,p
    save(OUT/'validation.json',{'passed':True,'protected_inputs_unchanged':True,'lr_rf_baseline_replication_max_ap_error':max(r['absolute_ap_difference'] for r in replication),'origins':len(cfg['origins'])-1,'importance_rows':len(allimportance),'metrics_rows':len(allmetrics),'interval_rows':len(allintervals),'minimum_valid_bootstrap_repeats':min(r['valid_repeats'] for r in allintervals),'completed_at':datetime.now(timezone.utc).isoformat()})
    print('Completed original RQ coverage; protected inputs unchanged.',flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['check','run']);args=parser.parse_args()
    checks()
    if args.stage=='run':run()
