"""Exploratory robustness follow-up. Uses frozen caches; never overwrites round one."""
from pathlib import Path
from datetime import date,datetime
import argparse,calendar,csv,hashlib,json,math,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'robustness'
sys.path.insert(0,str(ROOT/'tools/vendor'))
CFG=json.loads((OUT/'config/analysis.json').read_text())
BASE=json.loads((ROOT/'config/experiment.json').read_text());FEATURES=BASE['features']
RUNTIME=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
NODE=RUNTIME/'node/bin/node.exe'
for folder in ['data','results','reports','manifests/code']:(OUT/folder).mkdir(parents=True,exist_ok=True)
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def read_csv(path):
    with Path(path).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def csv_out(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def observation(r):return (r['origin'],r['project'],r['package'],r['dependency_type'])
def window_end(origin,months):
    d=date.fromisoformat(origin);year,month=divmod(d.year*12+d.month-1+months,12);month+=1
    return date(year,month,min(d.day,calendar.monthrange(year,month)[1])).isoformat()
def exact(constraint):return bool(re.fullmatch(r'\s*=?\s*v?\d+\.\d+\.\d+(?:\+[0-9A-Za-z.-]+)?\s*',constraint))
def archive_inputs():
    files=[ROOT/'data/processed/paired.csv',ROOT/'data/processed/all_available.csv',ROOT/'cache/ghsa/advisories.json',ROOT/'cache/ghsa/complete.json',ROOT/'results/temporal_metrics.json',ROOT/'results/associations.json',ROOT/'results/paired_ap_differences.json',ROOT/'results/predictions.csv',ROOT/'manifests/run.json']
    for relative in load(ROOT/'manifests/source_hashes.json'):files.append(ROOT.parent/relative)
    frozen=OUT/'manifests/protected_inputs.json'
    hashes={str(p):digest(p) for p in files}
    if frozen.exists():assert load(frozen)==hashes,'Protected original input changed.'
    else:save(frozen,hashes)
    for p in [Path(__file__),ROOT/'src/semver_variants.cjs',OUT/'config/analysis.json']:
        dest=OUT/'manifests/code'/(p.stem+'_'+digest(p)+p.suffix)
        if not dest.exists():dest.write_bytes(p.read_bytes())
def verify_protected():
    for p,h in load(OUT/'manifests/protected_inputs.json').items():assert digest(p)==h,p

def build():
    complete=load(ROOT/'cache/ghsa/complete.json');assert complete['complete']
    all_rows=read_csv(ROOT/'data/processed/all_available.csv')
    paired_projects={r['project'] for r in read_csv(ROOT/'data/processed/paired.csv')}
    times={}
    for file in (ROOT/'cache/npm').glob('*.json'):
        p=load(file);times[p['package']]=p['times']
    advisories={}
    for a in load(ROOT/'cache/ghsa/advisories.json'):
        if a.get('withdrawn_at'):continue
        for v in a['vulnerabilities']:
            if v['package']['ecosystem']=='npm':advisories.setdefault(v['package']['name'],[]).append({'id':a['ghsa_id'],'range':v['vulnerable_version_range'],'published_at':a['published_at'],'updated_at':a.get('updated_at')})
    summaries=[];datasets={}
    for variant in CFG['variants']:
        selected=[dict(r) for r in all_rows if variant['cohort']=='all_available' or r['project'] in paired_projects]
        if variant.get('constraint_subset'):selected=[r for r in selected if exact(r['constraint'])]
        for r in selected:
            r['window_end']=window_end(r['origin'],variant['horizon_months'])
            assert r['window_end']<=complete['published_end']
        payload={'rows':selected,'times':times,'advisories':advisories,'latest_rule':variant['latest_rule'],'clamp_negative':variant['clamp_negative']}
        env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(RUNTIME/'node/node_modules')
        run=subprocess.run([str(NODE),str(ROOT/'src/semver_variants.cjs')],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,check=True,env=env)
        raw=json.loads(run.stdout);rows=[r for r in raw if r['status']=='ok']
        assert len(rows)==len(selected),'Unknown label or new resolution exclusion; investigate before comparing.'
        assert all(r['used_version']==s['used_version'] for r,s in zip(rows,selected))
        if variant['id']=='date_12_paired':
            for r,s in zip(rows,selected):
                assert int(r['label'])==int(s['label'])
                for f in FEATURES:assert math.isclose(float(r[f]),float(s[f]),rel_tol=1e-12,abs_tol=1e-12),(observation(r),f)
        csv_out(OUT/'data'/(variant['id']+'.csv'),rows);datasets[variant['id']]={observation(r):r for r in rows}
        stats=[]
        for origin in BASE['origins']:
            group=[r for r in rows if r['origin']==origin]
            stats.append({'origin':origin,'projects':len({r['project'] for r in group}),'instances':len(group),'positive':sum(r['label'] for r in group),'negative_libyear_before_clamp':sum(r['negative_libyear'] for r in group)})
        summaries.append({'variant':variant,'summary':stats,'data_sha256':digest(OUT/'data'/(variant['id']+'.csv'))})
        print('Built variant',variant['id'],'rows',len(rows),flush=True)
    for short,long in [('date_6_paired','date_12_paired'),('semver_6_clamped','semver_12_clamped')]:
        assert datasets[short].keys()==datasets[long].keys()
        assert all(r['label']<=datasets[long][k]['label'] for k,r in datasets[short].items())
    save(OUT/'manifests/datasets.json',summaries)

def ap_plan(scores):
    import numpy as np
    levels,inverse=np.unique(scores,return_inverse=True)
    return len(levels)-1-inverse,len(levels)
def fast_ap(y,weights,plan):
    import numpy as np
    groups,n=plan
    positive=np.bincount(groups,weights=weights*y,minlength=n)
    total=np.bincount(groups,weights=weights,minlength=n)
    cum_pos=np.cumsum(positive);cum_total=np.cumsum(total)
    precision=np.divide(cum_pos,cum_total,out=np.zeros(n),where=cum_total>0)
    return float(np.sum(precision*positive)/positive.sum())
def cluster_intervals(frame,scores,unit,seed):
    import numpy as np
    from sklearn.metrics import average_precision_score
    labels=frame.label.to_numpy(dtype=int);x=frame.libyear.to_numpy(dtype=float)
    names,codes=np.unique(frame[unit].to_numpy(),return_inverse=True);rng=np.random.default_rng(seed)
    plans={name:ap_plan(p) for name,p in scores.items()}
    pairings=[(a,b) for a,b in [('full_lr','other_features_lr'),('full_rf','other_features_rf'),('full_lr','libyear_only_lr'),('full_rf','libyear_only_rf')] if a in scores and b in scores]
    samples={a+' minus '+b:[] for a,b in pairings};association=[]
    for _ in range(CFG['bootstrap_repeats']):
        counts=np.bincount(rng.integers(0,len(names),len(names)),minlength=len(names));weights=counts[codes]
        positive=float(weights@labels);negative=float(weights@(1-labels))
        if not positive or not negative:continue
        association.append(float((weights*labels)@x/positive-(weights*(1-labels))@x/negative))
        ap={name:fast_ap(labels,weights,plan) for name,plan in plans.items()}
        for a,b in pairings:samples[a+' minus '+b].append(ap[a]-ap[b])
    def bounds(values):
        if not values:return {'valid_repeats':0,'ci_low':None,'ci_high':None}
        return {'valid_repeats':len(values),'ci_low':float(np.quantile(values,.025)),'ci_high':float(np.quantile(values,.975))}
    effect={'cluster_unit':unit,**bounds(association)}
    differences=[]
    for a,b in pairings:
        comparison=a+' minus '+b;interval=bounds(samples[comparison]);point=float(average_precision_score(labels,scores[a])-average_precision_score(labels,scores[b]))
        contain={str(m):bool(interval['ci_low'] is not None and interval['ci_low']>=-m and interval['ci_high']<=m) for m in CFG['ap_margin_grid']}
        differences.append({'comparison':comparison,'cluster_unit':unit,'ap_difference':point,**interval,'interval_within_margin':contain})
    return effect,differences

def evaluate():
    import numpy as np,pandas as pd
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
    for variant in CFG['variants']:
        v=variant['id'];folder=OUT/'results'/v;folder.mkdir(exist_ok=True)
        complete=folder/'complete.json'
        if complete.exists():
            done=load(complete);assert done['config_sha256']==digest(OUT/'config/analysis.json') and done['data_sha256']==digest(OUT/'data'/(v+'.csv'))
            print('Cached evaluated variant',v,flush=True);continue
        frame=pd.read_csv(OUT/'data'/(v+'.csv'),keep_default_na=False)
        metrics=[];effects=[];differences=[];predictions=[]
        for origin in BASE['origins']:
            test=frame[frame.origin==origin];train=frame[(frame.origin<origin)&(frame.window_end<=origin)]
            if test.empty:continue
            y=test.label.to_numpy(dtype=int);positive=test[test.label==1].libyear;negative=test[test.label==0].libyear
            effect={'variant':v,'origin':origin,'n':len(test),'projects':test.project.nunique(),'positive':int(y.sum()),'positive_rate':float(y.mean()),'mean_difference':float(positive.mean()-negative.mean()) if len(positive) and len(negative) else None,'negative_libyear_before_clamp':int(test.negative_libyear.sum())}
            if train.empty or train.label.nunique()<2 or test.label.nunique()<2:
                # Association can still be assessed at the earliest snapshot.
                if test.label.nunique()==2:
                    for unit in CFG['cluster_units']:
                        e,_=cluster_intervals(test,{},unit,CFG['seed']);effects.append({**effect,**e})
                else:effects.append({**effect,'cluster_unit':'not_estimable','valid_repeats':0,'ci_low':None,'ci_high':None})
                metrics.append({'variant':v,'origin':origin,'status':'insufficient_training_or_test_classes','train_n':len(train),'test_n':len(test)});continue
            assert (train.origin<origin).all() and (train.window_end<=origin).all()
            models={'libyear_only_lr':(['libyear'],LogisticRegression(C=1,max_iter=2000,random_state=42)),'other_features_lr':([f for f in FEATURES if f!='libyear'],LogisticRegression(C=1,max_iter=2000,random_state=42)),'full_lr':(FEATURES,LogisticRegression(C=1,max_iter=2000,random_state=42)),'libyear_only_rf':(['libyear'],RandomForestClassifier(n_estimators=200,max_depth=6,min_samples_leaf=5,n_jobs=2,random_state=42)),'other_features_rf':([f for f in FEATURES if f!='libyear'],RandomForestClassifier(n_estimators=200,max_depth=6,min_samples_leaf=5,n_jobs=2,random_state=42)),'full_rf':(FEATURES,RandomForestClassifier(n_estimators=200,max_depth=6,min_samples_leaf=5,n_jobs=2,random_state=42))}
            scores={'constant_training_rate':np.full(len(test),train.label.mean()),'libyear_score':test.libyear.to_numpy()}
            for name,(features,clf) in models.items():
                pipe=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),clf)
                pipe.fit(train[features],train.label);scores[name]=pipe.predict_proba(test[features])[:,1]
            for name,p in scores.items():
                row={'variant':v,'origin':origin,'model':name,'train_n':len(train),'test_n':len(test),'positive':int(y.sum()),'positive_rate':float(y.mean()),'ap':float(average_precision_score(y,p)),'roc_auc':float(roc_auc_score(y,p))}
                if name!='libyear_score':row['brier']=float(brier_score_loss(y,p))
                metrics.append(row)
                for i,r in enumerate(test.to_dict('records')):predictions.append({'origin':origin,'project':r['project'],'package':r['package'],'dependency_type':r['dependency_type'],'used_version':r['used_version'],'label':int(y[i]),'model':name,'score':float(p[i])})
            for unit in CFG['cluster_units']:
                e,d=cluster_intervals(test,{name:scores[name] for name in models},unit,CFG['seed'])
                effects.append({**effect,**e});differences.extend({'variant':v,'origin':origin,**r} for r in d)
            print('Evaluated',v,origin,'train',len(train),'test',len(test),flush=True)
        save(folder/'metrics.json',metrics);save(folder/'associations.json',effects);save(folder/'ap_differences.json',differences);csv_out(folder/'predictions.csv',predictions)
        save(complete,{'config_sha256':digest(OUT/'config/analysis.json'),'data_sha256':digest(OUT/'data'/(v+'.csv')),'script_sha256':digest(__file__),'semver_sha256':digest(ROOT/'src/semver_variants.cjs'),'bootstrap_repeats':CFG['bootstrap_repeats'],'model_hyperparameters_unchanged':True})
    old=load(ROOT/'results/temporal_metrics.json');new=load(OUT/'results/date_12_paired/metrics.json');comparison=[]
    for r in old:
        if r.get('status')!='ok':continue
        match=next(n for n in new if n.get('model')==r['model'] and n['origin']==r['origin'])
        delta=abs(match['ap']-r['average_precision']);comparison.append({'origin':r['origin'],'model':r['model'],'absolute_ap_difference':delta})
        assert delta<.001,'Baseline replication differs materially; investigate before summarizing robustness.'
    save(OUT/'manifests/baseline_replication.json',comparison)

def checks():
    import numpy as np
    from sklearn.metrics import average_precision_score
    assert window_end('2020-12-31',6)=='2021-06-30' and window_end('2023-12-31',12)=='2024-12-31'
    rng=np.random.default_rng(17)
    for _ in range(30):
        y=rng.integers(0,2,80);score=rng.choice([.1,.2,.5,.9],80);w=rng.integers(0,6,80)
        if not (w@y) or not (w@(1-y)):continue
        assert math.isclose(fast_ap(y,w,ap_plan(score)),average_precision_score(y,score,sample_weight=w),rel_tol=1e-12,abs_tol=1e-12)
        repeated=np.repeat(np.arange(len(y)),w)
        assert math.isclose(fast_ap(y,w,ap_plan(score)),average_precision_score(y[repeated],score[repeated]),rel_tol=1e-12,abs_tol=1e-12)
    assert exact('= 1.2.3') and exact('v1.2.3') and not exact('^1.2.3') and not exact('1.2.3-beta')
    env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(RUNTIME/'node/node_modules')
    row={'project':'p/r','package':'p','constraint':'1.9.0','origin':'2023-12-31','window_end':'2024-06-30'}
    payload={'rows':[row],'times':{'p':{'1.9.0':'2023-05-01T00:00:00Z','2.0.0':'2023-01-01T00:00:00Z','3.0.0':'2024-01-01T00:00:00Z'}},'advisories':{},'latest_rule':'highest_semver','clamp_negative':False}
    def run_input(p):return json.loads(subprocess.check_output([str(NODE),str(ROOT/'src/semver_variants.cjs')],input=json.dumps(p),text=True,env=env))[0]
    signed=run_input(payload);assert signed['latest_version']=='2.0.0' and signed['libyear']<0
    payload['clamp_negative']=True;clamped=run_input(payload);assert clamped['libyear']==0 and clamped['raw_libyear']==signed['libyear']
    payload['latest_rule']='publication_date';dated=run_input(payload);assert dated['latest_version']=='1.9.0' and dated['libyear']==0
    print('Checks passed: calendar horizon, weighted AP/ties/zero weights, exact constraints, backport negative dates, clamp and future-release exclusion.',flush=True)

def report():
    configs=load(OUT/'manifests/datasets.json');all_effects=[];all_diffs=[];all_metrics=[]
    for v in CFG['variants']:
        folder=OUT/'results'/v['id'];assert (folder/'complete.json').exists()
        all_effects+=load(folder/'associations.json');all_diffs+=load(folder/'ap_differences.json');all_metrics+=load(folder/'metrics.json')
    def table(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(str(c) for c in r)+' |' for r in rows])
    def number(x):return 'not estimable' if x is None else f'{x:+.4f}'
    lines=['# ผล robustness ของ Libyear','การวิเคราะห์เพิ่มเติมนี้ออกแบบหลังเห็นผลรอบแรก เป็น exploratory retrospective sensitivity ใช้ cache เดิมและพารามิเตอร์คงที่ ไม่ใช่ independent confirmatory study หรือ prospective validation','## Dataset และการเปลี่ยนนิยาม',table(['Variant','Origin','Projects','Instances','Positive','Raw negative Libyear'],[[c['variant']['id'],s['origin'],s['projects'],s['instances'],s['positive'],s['negative_libyear_before_clamp']] for c in configs for s in c['summary']]),'Highest-SemVer release อาจเผยแพร่ก่อน backport เวอร์ชันที่อ้างอิง ทำให้ระยะห่างวันเป็นลบ Signed variants ใช้ศึกษาความไวของการนิยาม ไม่ถือว่าค่าลบคือความล้าสมัยเชิงอายุ Clamped variants เป็นกฎเพิ่มเติม ไม่ใช่ gold standard การเปลี่ยน latest เปลี่ยน Libyear และ days_since_latest_release ส่วน release-chain counts ยังคงนิยามจาก available releases ณ origin','## Association พร้อม uncertainty',table(['Variant','Origin','Cluster','Mean difference','95% interval'],[[r['variant'],r['origin'],r['cluster_unit'],number(r['mean_difference']),number(r['ci_low'])+' to '+number(r['ci_high'])] for r in all_effects]),'Intervals รวมกลุ่ม package และ project เป็นสอง sensitivity analyses แยกกัน ไม่ใช่ multiway correction ที่แก้ crossed dependence ทั้งหมด ค่า mean difference ไม่เปลี่ยนตาม resampling unit แต่ interval อาจเปลี่ยน','## คุณค่าส่วนเพิ่มของ Libyear ใน LR และ RF',table(['Variant','Origin','Comparison','Cluster','AP difference','95% interval','Inside ±0.01 AP'],[[r['variant'],r['origin'],r['comparison'],r['cluster_unit'],number(r['ap_difference']),number(r['ci_low'])+' to '+number(r['ci_high']),r['interval_within_margin']['0.01']] for r in all_diffs if 'minus other_features' in r['comparison']]),'## Ranking metrics',table(['Variant','Origin','Model','AP','Positive rate'],[[r['variant'],r['origin'],r['model'],f"{r['ap']:.4f}",f"{r['positive_rate']:.4f}"] for r in all_metrics if r.get('model') in ['libyear_only_lr','other_features_lr','full_lr','other_features_rf','full_rf']]),'## ขอบเขตการตีความ','CI ที่คร่อมศูนย์ไม่พิสูจน์ว่าไม่มีผล การอยู่ภายใน margin เป็น posthoc interval-containment sensitivity เท่านั้น ไม่ใช่ TOST equivalence test และไม่ได้ยืนยันว่า margin ±0.005 ±0.01 หรือ ±0.02 AP มีความสำคัญเชิงใช้งานเท่ากันในทุกบริบท','CI เป็น conditional uncertainty ของ test scores ที่ fit แล้ว ไม่ได้รวมความไม่แน่นอนของการเลือกโมเดลหรือการฝึกทุกขั้น ไม่มี multiplicity correction และ origins ใช้โครงการและ package ร่วม จึงไม่ใช่ independent replications','Exact-constraint subset ลดความคลุมเครือของ resolution แต่ยังไม่ยืนยัน installed version ด้วย lockfile ขนาด cohort ของ subset ต่างจาก paired cohort ต้องอ่าน sample counts และ class balance ก่อนเทียบ','Data/cache เดิมมี GHSA ranges และ npm timestamps ที่อาจแก้ย้อนหลัง ผลรอบนี้ไม่ยืนยัน historical availability การตรวจ literature และ novelty ต้องดำเนินการแยกจากการเพิ่มจำนวน models']
    (OUT/'reports/robustness_results.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    save(OUT/'results/all_associations.json',all_effects);save(OUT/'results/all_ap_differences.json',all_diffs);save(OUT/'results/all_metrics.json',all_metrics)
    verify_protected();save(OUT/'manifests/validation.json',{'passed':True,'protected_inputs_unchanged':True,'variants':len(CFG['variants']),'baseline_features_labels_reproduced':True,'baseline_metrics_reproduced_within_0_001_ap':True,'analysis_status':CFG['design_status'],'no_network_collection':True})
    print('Reported all robustness variants; original inputs unchanged.',flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['check','build','evaluate','report','all']);args=parser.parse_args()
    if args.stage=='check':checks();return
    archive_inputs()
    if args.stage in ['build','all']:build()
    if args.stage in ['evaluate','all']:evaluate()
    if args.stage in ['report','all']:report()
    verify_protected()
if __name__=='__main__':main()
