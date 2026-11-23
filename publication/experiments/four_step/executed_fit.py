"""Fixed secondary comparators, family ablation and declared training sensitivities."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
import hashlib,json,sys
R=Path(__file__).resolve().parents[1];P=R/'publication';O=P/'experiments/four_step';sys.path[:0]=[str(P/'tools/vendor'),str(R/'tools/vendor')]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def run():
    import numpy as np,pandas as pd,sklearn,scipy,xgboost
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
    from xgboost import XGBClassifier
    cfg=load(P/'protocol/rq_completion.json');follow=load(P/'protocol/four_step_followup.json');data=R/'robustness/data/date_12_paired.csv'
    versions={'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__,'scipy':scipy.__version__,'xgboost':xgboost.__version__}
    assert versions==load(P/'experiments/rq_completion/frozen_manifest.json')['versions']
    frozen={'source_sha256':sha(Path(__file__)),'protocol_sha256':sha(P/'protocol/four_step_followup.json'),'primary_data_sha256':sha(data),'completion_config_sha256':sha(P/'protocol/rq_completion.json'),'proxy_exclusions_sha256':sha(O/'late_review_proxy_exclusions.json'),'versions':versions,'started_at':datetime.now(timezone.utc).isoformat()}
    assert not (O/'fit_manifest.json').exists(),'Do not overwrite a frozen run.'
    save(O/'fit_manifest.json',frozen)
    (O/'executed_fit.py').write_bytes(Path(__file__).read_bytes());(O/'executed_protocol.json').write_bytes((P/'protocol/four_step_followup.json').read_bytes())
    frame=pd.read_csv(data,keep_default_na=False);features=cfg['features'];exclusions=load(O/'late_review_proxy_exclusions.json');allmetrics=[];fit_count=0;ledger=[]
    factories={'lr':lambda:LogisticRegression(**cfg['models']['lr']),'rf':lambda:RandomForestClassifier(**cfg['models']['rf']),'xgb':lambda:XGBClassifier(**cfg['models']['xgb'])}
    def fit(train,test,columns,algorithm):
        nonlocal fit_count
        assert train.origin.max()<test.origin.min() and train.window_end.max()<=test.origin.min()
        assert train.label.nunique()==2
        model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),factories[algorithm]());model.fit(train[columns],train.label);fit_count+=1
        return model.predict_proba(test[columns])[:,1]
    def metric(test,s,name,origin,train_n,variant):
        y=test.label.to_numpy(int)
        return {'origin':origin,'variant':variant,'model':name,'train_n':train_n,'test_n':len(test),'positive':int(y.sum()),'ap':float(average_precision_score(y,s)),'roc_auc':float(roc_auc_score(y,s)),'brier':float(brier_score_loss(y,s))}
    for origin in cfg['origins'][1:]:
        test=frame[frame.origin==origin].copy();train=frame[(frame.origin<origin)&(frame.window_end<=origin)].copy()
        reference=pd.read_csv(P/'experiments/rq_completion'/origin/'predictions_wide.csv',keep_default_na=False)
        keys=['origin','project','package','dependency_type','used_version','label'];assert test[keys].reset_index(drop=True).equals(reference[keys])
        scores={}
        for name,columns in [('package_age_only_lr',['package_age']),('recency_only_lr',['days_since_latest_release'])]:scores[name]=fit(train,test,columns,'lr')
        columns=[f for f in features if f not in follow['new_fixed_models']['drop_lag_recency_family']]
        assert columns==['release_frequency','package_age','total_versions','is_post_1_0']
        for algorithm in factories:scores['drop_lag_recency_family_'+algorithm]=fit(train,test,columns,algorithm)
        output=test[keys].copy()
        for name,s in scores.items():output[name]=s;allmetrics.append(metric(test,s,name,origin,len(train),'comparators'))
        (O/'new_scores').mkdir(exist_ok=True);output.to_csv(O/'new_scores'/(origin+'.csv'),index=False)
        cache={}
        for variant in ['lag_30_days','lag_90_days','exclude_no_reviewed_match']:
            if variant.startswith('lag_'):
                lag=int(variant.split('_')[1]);dates=pd.to_datetime(train.window_end)+pd.Timedelta(days=lag);selected=train[dates<=pd.Timestamp(origin)]
            else:
                omit={tuple(r[k] for k in ['origin','project','package','dependency_type','used_version']) for r in exclusions[origin]}
                selected=train[[tuple(getattr(r,k) for k in ['origin','project','package','dependency_type','used_version']) not in omit for r in train.itertuples()]]
            signature=hashlib.sha256(selected[features+['label','origin','project','package','dependency_type']].to_csv(index=False).encode()).hexdigest()
            entry={'origin':origin,'variant':variant,'train_n':len(selected),'removed_training_rows':len(train)-len(selected),'training_signature':signature,'train_origins':sorted(selected.origin.unique().tolist())}
            if selected.empty or selected.label.nunique()<2:
                ledger.append({**entry,'status':'not_estimable','reason':'no eligible two-class historical training set'});continue
            same_as_primary=selected.index.equals(train.index)
            if same_as_primary:
                variant_scores={group+'_'+algorithm:reference[('full_' if group=='full' else 'drop_libyear_')+algorithm].to_numpy() for algorithm in factories for group in ['full','without_libyear']}
                alias='primary_reference_predictions'
            elif signature in cache:variant_scores=cache[signature][1];alias=cache[signature][0]
            else:
                variant_scores={group+'_'+algorithm:fit(selected,test,columns,algorithm) for algorithm in factories for group,columns in [('full',features),('without_libyear',[f for f in features if f!='libyear'])]}
                cache[signature]=(variant,variant_scores);alias=None
            pred=test[keys].copy()
            for name,s in variant_scores.items():pred[name]=s;allmetrics.append(metric(test,s,name,origin,len(selected),variant))
            directory=O/'training_sensitivity'/variant;directory.mkdir(parents=True,exist_ok=True);pred.to_csv(directory/(origin+'.csv'),index=False)
            ledger.append({**entry,'status':'estimable','prediction_alias':alias})
        print('Fit follow-up',origin,'cumulative new fits',fit_count,flush=True)
    save(O/'new_model_metrics.json',allmetrics);save(O/'training_sensitivity_ledger.json',ledger)
    assert sha(data)==frozen['primary_data_sha256'] and sha(Path(__file__))==frozen['source_sha256']
    save(O/'fit_validation.json',{'passed':True,'new_fits':fit_count,'metrics_rows':len(allmetrics),'primary_data_unchanged':True,'source_unchanged':True,'completed_at':datetime.now(timezone.utc).isoformat()})
    print('Completed fixed follow-up fits',fit_count,flush=True)
if __name__=='__main__':run()
