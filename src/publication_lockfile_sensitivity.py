"""Matched-observation lockfile reference sensitivity, separate from primary data."""
from pathlib import Path
from datetime import datetime,timezone
import json,sys,csv,subprocess,os,hashlib,math
ROOT=Path(__file__).resolve().parents[1];PUB=ROOT/'publication';OUT=PUB/'experiments/lockfile_sensitivity'
sys.path[:0]=[str(PUB/'tools/vendor'),str(ROOT/'tools/vendor'),str(ROOT/'src')]
from publication_completion import load,digest,save,intervals
from publication_audit import locked_version,GIT
RUNTIME=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
def readcsv(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def key(r):return tuple(r[x] for x in ['origin','project','package','dependency_type'])
def outputcsv(p,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with p.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def run():
    import pandas as pd,numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
    from xgboost import XGBClassifier
    OUT.mkdir(parents=True,exist_ok=True)
    cfg=load(PUB/'protocol/rq_completion.json');sensitivity=PUB/'protocol/lockfile_sensitivity.json'
    protected=load(ROOT/'robustness/manifests/protected_inputs.json')
    inputs=[ROOT/'robustness/data/date_12_paired.csv',PUB/'audits/lockfiles.json',PUB/'protocol/rq_completion.json',sensitivity,ROOT/'src/semver_variants.cjs']
    protected.update({str(p):digest(p) for p in inputs})
    frozen={'script_sha256':digest(Path(__file__)),'inputs':protected,'started_at':datetime.now(timezone.utc).isoformat(),'status':load(sensitivity)['status']}
    if (OUT/'manifest.json').exists():
        old=load(OUT/'manifest.json');assert old['script_sha256']==frozen['script_sha256'] and old['inputs']==frozen['inputs']
    else:save(OUT/'manifest.json',frozen);(OUT/'executed_source.py').write_bytes(Path(__file__).read_bytes())
    original=readcsv(inputs[0]);source_rows={key(r):r for r in original};bycell={}
    for r in original:bycell.setdefault((r['origin'],r['project']),[]).append(r)
    snapshot_ids={}
    for p in (ROOT/'cache/snapshots').glob('*/*.json'):
        snap=load(p);snapshot_ids[(p.parent.name,snap.get('project'))]=p.stem
    selected=[];missing=0
    for record in load(PUB/'audits/lockfiles.json'):
        if record['parse_status']!='ok':continue
        repo=ROOT/'cache/git'/snapshot_ids[(record['origin'],record['project'])]
        env=os.environ.copy();env['GIT_NO_LAZY_FETCH']='1'
        blob=subprocess.run([str(GIT),'-C',str(repo),'show',record['commit_sha']+':'+record['lockfile']],capture_output=True,timeout=20,env=env,check=True).stdout
        assert hashlib.sha256(blob).hexdigest()==record['lockfile_sha256']
        lock=json.loads(blob.decode('utf-8-sig'))
        for row in bycell[(record['origin'],record['project'])]:
            version=locked_version(lock,row['package'])
            if not version:missing+=1;continue
            selected.append({**row,'manifest_constraint':row['constraint'],'constraint':version,'recorded_lockfile_version':version})
    times={}
    for p in (ROOT/'cache/npm').glob('*.json'):
        item=load(p);times[item['package']]=item['times']
    advisory_map={}
    for a in load(ROOT/'cache/ghsa/advisories.json'):
        if a.get('withdrawn_at'):continue
        for v in a['vulnerabilities']:
            if v['package']['ecosystem']=='npm':advisory_map.setdefault(v['package']['name'],[]).append({'id':a['ghsa_id'],'range':v['vulnerable_version_range'],'published_at':a['published_at'],'updated_at':a.get('updated_at')})
    payload={'rows':selected,'times':times,'advisories':advisory_map,'latest_rule':'publication_date','clamp_negative':False}
    env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(RUNTIME/'node/node_modules')
    batch=subprocess.run([str(RUNTIME/'node/bin/node.exe'),str(ROOT/'src/semver_variants.cjs')],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',check=True,env=env)
    raw=json.loads(batch.stdout);locked=[r for r in raw if r['status']=='ok' and r['used_version']==r['recorded_lockfile_version']]
    excluded=[{'origin':r['origin'],'project':r['project'],'package':r['package'],'recorded_version':r['recorded_lockfile_version'],'status':r['status']} for r in raw if r['status']!='ok' or r.get('used_version')!=r['recorded_lockfile_version']]
    inferred=[source_rows[key(r)] for r in locked]
    assert len(locked)==len(inferred) and len({key(r) for r in locked})==len(locked)
    outputcsv(OUT/'recorded.csv',locked);outputcsv(OUT/'inferred_matched.csv',inferred);save(OUT/'exclusions.json',excluded)
    dataset_summary=[]
    for origin in cfg['origins']:
        a=[r for r in inferred if r['origin']==origin];b=[r for r in locked if r['origin']==origin]
        dataset_summary.append({'origin':origin,'instances':len(a),'projects':len({r['project'] for r in a}),'inferred_positive':sum(int(r['label']) for r in a),'recorded_positive':sum(int(r['label']) for r in b),'label_disagreements':sum(int(x['label'])!=int(y['label']) for x,y in zip(a,b)),'version_disagreements':sum(x['used_version']!=y['used_version'] for x,y in zip(a,b))})
    metrics=[];cis=[];predictions=[]
    factories={'lr':lambda:LogisticRegression(**cfg['models']['lr']),'rf':lambda:RandomForestClassifier(**cfg['models']['rf']),'xgb':lambda:XGBClassifier(**cfg['models']['xgb'])}
    for arm,records in [('inferred_matched',inferred),('recorded',locked)]:
        frame=pd.DataFrame(records)
        for f in cfg['features']+['label']:frame[f]=pd.to_numeric(frame[f])
        for origin in cfg['origins'][1:]:
            test=frame[frame.origin==origin];train=frame[(frame.origin<origin)&(frame.window_end<=origin)]
            assert train.label.nunique()==test.label.nunique()==2
            scores={}
            for algorithm,factory in factories.items():
                for group,features in [('full',cfg['features']),('without_libyear',[f for f in cfg['features'] if f!='libyear']),('libyear_only',['libyear'])]:
                    name=group+'_'+algorithm;model=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),factory());model.fit(train[features],train.label);s=model.predict_proba(test[features])[:,1];scores[name]=s
                    y=test.label.to_numpy(int);metrics.append({'arm':arm,'origin':origin,'model':name,'train_n':len(train),'test_n':len(test),'positive':int(y.sum()),'prevalence':float(y.mean()),'ap':float(average_precision_score(y,s)),'roc_auc':float(roc_auc_score(y,s)),'brier':float(brier_score_loss(y,s))})
            pairs=[('full_'+a,b+'_'+a) for a in factories for b in ['without_libyear','libyear_only']]
            points={r['model']:r['ap'] for r in metrics if r['arm']==arm and r['origin']==origin}
            for unit in cfg['cluster_units']:
                cis.extend({'arm':arm,'origin':origin,'ap_difference':points[r['model_a']]-points[r['model_b']],**r} for r in intervals(test,scores,pairs,unit,cfg))
            pred=test[['origin','project','package','dependency_type','used_version','label']].copy()
            for name,s in scores.items():pred[name]=s
            pred.to_csv(OUT/(arm+'_'+origin+'_predictions.csv'),index=False)
            print('Lockfile sensitivity',arm,origin,'n',len(test),flush=True)
    save(OUT/'metrics.json',metrics);save(OUT/'intervals.json',cis);save(OUT/'dataset_summary.json',dataset_summary)
    for p,h in protected.items():assert digest(Path(p))==h,p
    save(OUT/'validation.json',{'passed':True,'matched_keys_equal':True,'candidate_instances':len(selected),'unresolved_root_lockfile_instances':missing,'excluded_recorded_version_instances':len(excluded),'matched_eligible_instances':len(locked),'metrics_rows':len(metrics),'interval_rows':len(cis),'original_inputs_unchanged':True,'minimum_valid_bootstrap_repeats':min(r['valid_repeats'] for r in cis),'completed_at':datetime.now(timezone.utc).isoformat()})
if __name__=='__main__':run()
