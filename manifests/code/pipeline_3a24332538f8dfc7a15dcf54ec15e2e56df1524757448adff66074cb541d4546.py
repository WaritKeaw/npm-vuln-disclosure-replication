"""Isolated reproducible snapshot sensitivity and retrospective temporal backtest.

No import of legacy settings and no writes to legacy replicability data.
Network collection uses public Git repositories, npm and the public GHSA API.
"""
from pathlib import Path
import argparse,base64,csv,hashlib,json,os,re,subprocess,sys,time,urllib.request,urllib.parse,urllib.error
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor,as_completed

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/vendor'))
WORK=ROOT.parent
RUNTIME=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies'
GIT=RUNTIME/'native/git/cmd/git.exe'
NODE=RUNTIME/'node/bin/node.exe'
CFG=json.loads((ROOT/'config/experiment.json').read_text())
assert CFG['horizon_months']==12,'This implementation supports a fixed 12-month calendar horizon.'
FEATURES=CFG['features']
for d in ['data/cohort','data/processed','cache/git','cache/snapshots','cache/npm','cache/ghsa','manifests','results','reports','tests']:
    (ROOT/d).mkdir(parents=True,exist_ok=True)

def now():return datetime.now(timezone.utc).isoformat()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    # Windows readers can temporarily deny delete-sharing during atomic replace.
    for attempt in range(20):
        try:tmp.replace(p);return
        except PermissionError:
            if attempt==19:raise
            time.sleep(.15)
def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write_csv(path,rows):
    if not rows:return
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def key(s):return hashlib.sha256(s.encode()).hexdigest()[:24]
def end_date(origin):
    d=datetime.fromisoformat(origin)
    return d.replace(year=d.year+1).date().isoformat()
def origin_time(origin):return datetime.fromisoformat(origin+'T23:59:59.999+00:00')
def get_json(url):
    headers={'User-Agent':'ThesisSnapshotSensitivity/1.0','Accept':'application/json'}
    if urllib.parse.urlparse(url).hostname=='api.github.com':
        headers['Accept']='application/vnd.github+json'
        token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        if token:headers['Authorization']='Bearer '+token
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=45) as r:
                return json.load(r),dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code in [401,403,404,422,429]:raise RuntimeError('HTTP '+str(e.code)+' from '+urllib.parse.urlparse(url).hostname) from None
            if attempt==2:raise
        except (urllib.error.URLError,TimeoutError):
            if attempt==2:raise
        time.sleep(2**attempt)
def git(args,timeout=180):
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0';env['GCM_INTERACTIVE']='Never'
    r=subprocess.run([str(GIT),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,env=env)
    if r.returncode:raise RuntimeError('Git operation failed: '+r.stderr[-350:])
    return r.stdout.strip()

def initialize():
    import duckdb
    source=WORK/'replicability/data/processed/features_labeled.parquet'
    rows=duckdb.sql('select distinct project,stratum from read_parquet(?) order by project',params=[str(source)]).fetchall()
    projects=[{'project':p,'stratum':s} for p,s in rows]
    assert len(projects)==250 and len({p['project'] for p in projects})==250
    for p in projects:assert re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',p['project'])
    save(ROOT/'data/cohort/projects.json',projects)
    files=[source,WORK/'replicability/data/raw/projects.parquet',WORK/'replicability/data/raw/instances.parquet',WORK/'replicability/data/raw/ghsa_advisories.parquet']
    save(ROOT/'manifests/source_hashes.json',{str(p.relative_to(WORK)):sha(p) for p in files})
    import importlib.metadata as metadata
    versions={x:metadata.version(x) for x in ['duckdb','scikit-learn','scipy','numpy','pandas','joblib']}
    versions['node_semver']=subprocess.check_output([str(NODE),'-e','console.log(require(process.argv[1]+"/semver/package.json").version)',str(RUNTIME/'node/node_modules')],text=True).strip()
    save(ROOT/'manifests/environment.json',{'python':sys.version,'packages':versions,'initialized_at':now(),'config_sha256':sha(ROOT/'config/experiment.json')})
    print('Frozen original analyzed cohort:',len(projects),flush=True)

def collect_project(project):
    name=project['project'];repo=ROOT/'cache/git'/key(name)
    needed=[o for o in CFG['origins'] if not (ROOT/'cache/snapshots'/o/(key(name)+'.json')).exists()]
    statuses=[{'project':name,'origin':o,'status':'cached'} for o in CFG['origins'] if o not in needed]
    if not needed:return statuses
    try:
        if not (repo/'HEAD').exists():
            git(['clone','--bare','--filter=blob:none','--single-branch','https://github.com/'+name+'.git',str(repo)],timeout=300)
        head=git(['--git-dir',str(repo),'rev-parse','HEAD'])
        # First-parent history of the frozen current default branch. Commit dates can
        # be backdated; this reconstructs history, not historical information access.
        history=git(['--git-dir',str(repo),'log','--first-parent','--format=%H %cI']).splitlines()
        for origin in needed:
            selected=next(((line.split(' ',1)) for line in history if datetime.fromisoformat(line.split(' ',1)[1])<=origin_time(origin)),None)
            if selected is None:
                statuses.append({'project':name,'origin':origin,'status':'no_commit_at_origin'});continue
            commit,date=selected
            try:
                raw=git(['--git-dir',str(repo),'show',commit+':package.json'])
                pkg=json.loads(raw)
                record={'project':name,'stratum':project['stratum'],'origin':origin,'commit_sha':commit,'commit_date':date,'frozen_branch_head':head,'collected_at':now(),'package_json_sha256':hashlib.sha256(raw.encode()).hexdigest(),'package_json':pkg}
                save(ROOT/'cache/snapshots'/origin/(key(name)+'.json'),record)
                statuses.append({'project':name,'origin':origin,'status':'ok'})
            except Exception as e:
                statuses.append({'project':name,'origin':origin,'status':'package_json_unavailable','error':type(e).__name__+': '+str(e)[:350]})
    except Exception as e:
        statuses.extend({'project':name,'origin':o,'status':'repository_failed','error':type(e).__name__+': '+str(e)[:350]} for o in needed)
    return statuses

def collect_snapshots(limit=0):
    projects=load(ROOT/'data/cohort/projects.json');projects=projects[:limit] if limit else projects
    records=[]
    with ThreadPoolExecutor(max_workers=CFG['workers']) as pool:
        futures=[pool.submit(collect_project,p) for p in projects]
        for count,future in enumerate(as_completed(futures),1):
            records.extend(future.result())
            save(ROOT/'manifests/snapshot_collection_progress.json',{'completed_projects':count,'requested_projects':len(projects),'updated_at':now(),'statuses':records})
            if count%5==0 or count==len(projects):print('Snapshot projects',count,'/',len(projects),flush=True)
    save(ROOT/'manifests/snapshot_collection.json',{'requested_projects':len(projects),'finished_at':now(),'statuses':records})

def collect_advisories():
    complete=ROOT/'cache/ghsa/complete.json'
    if complete.exists():return
    start=str(int(CFG['origins'][0][:4])+1)+'-01-01'
    end=end_date(CFG['origins'][-1])
    first='https://api.github.com/advisories?'+urllib.parse.urlencode({'ecosystem':'npm','type':'reviewed','published':start+'..'+end,'per_page':100,'sort':'published','direction':'asc'})
    url=first;page=1;all_rows=[];pages=[];visited=set()
    while url:
        assert urllib.parse.urlparse(url).hostname=='api.github.com' and url not in visited
        visited.add(url);cache=ROOT/'cache/ghsa'/('page-'+str(page)+'.json')
        if cache.exists():record=load(cache)
        else:
            rows,headers=get_json(url)
            record={'url':url,'collected_at':now(),'link':headers.get('Link') or headers.get('link',''),'rows':rows}
            save(cache,record)
        assert record['url']==url
        all_rows.extend(record['rows']);pages.append({'file':cache.name,'sha256':sha(cache),'collected_at':record['collected_at']})
        match=re.search(r'<([^>]+)>;\s*rel="next"',record['link'])
        url=match.group(1) if match else None
        print('GHSA page',page,'records',len(all_rows),flush=True);page+=1
    assert len({a['ghsa_id'] for a in all_rows})==len(all_rows),'GHSA pagination duplicate; recollect snapshot'
    save(ROOT/'cache/ghsa/advisories.json',all_rows)
    save(complete,{'complete':True,'query':first,'published_start':start,'published_end':end,'completed_at':now(),'advisories':len(all_rows),'pages':pages,'history_is_current_metadata':True})

def dependency_rows():
    rows=[]
    for origin in CFG['origins']:
        for file in sorted((ROOT/'cache/snapshots'/origin).glob('*.json')):
            s=load(file)
            for field,kind in [('dependencies','production'),('devDependencies','development')]:
                deps=s['package_json'].get(field,{})
                if not isinstance(deps,dict):continue
                for package,constraint in deps.items():
                    if not isinstance(constraint,str):continue
                    rows.append({'project':s['project'],'stratum':s['stratum'],'origin':origin,'window_end':end_date(origin),'package':package,'constraint':constraint,'dependency_type':kind,'commit_sha':s['commit_sha']})
    return rows

def collect_npm():
    names=sorted({r['package'] for r in dependency_rows()});errors=[]
    def one(name):
        path=ROOT/'cache/npm'/(key(name)+'.json')
        if path.exists():return None
        try:
            obj,_=get_json('https://registry.npmjs.org/'+urllib.parse.quote(name,safe=''))
            times={k:v for k,v in obj.get('time',{}).items() if k not in ['created','modified']}
            if not times:raise ValueError('no version publication dates')
            save(path,{'package':name,'collected_at':now(),'times':times})
        except Exception as e:return {'package':name,'error':type(e).__name__+': '+str(e)[:200]}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for count,result in enumerate(pool.map(one,names),1):
            if result:errors.append(result)
            if count%100==0 or count==len(names):print('npm packages',count,'/',len(names),'errors',len(errors),flush=True)
    save(ROOT/'manifests/npm_collection.json',{'requested_packages':len(names),'errors':errors,'finished_at':now()})

def build():
    import duckdb,pandas as pd
    assert (ROOT/'cache/ghsa/complete.json').exists(),'Cannot create negative labels without a complete GHSA collection.'
    times={}
    for f in (ROOT/'cache/npm').glob('*.json'):
        p=load(f);times[p['package']]=p['times']
    adv={}
    for a in load(ROOT/'cache/ghsa/advisories.json'):
        if a.get('withdrawn_at'):continue
        for v in a.get('vulnerabilities',[]):
            if v['package']['ecosystem']!='npm':continue
            adv.setdefault(v['package']['name'],[]).append({'id':a['ghsa_id'],'published_at':a['published_at'],'updated_at':a.get('updated_at'),'range':v['vulnerable_version_range']})
    payload={'rows':dependency_rows(),'times':times,'advisories':adv}
    env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(RUNTIME/'node/node_modules')
    run=subprocess.run([str(NODE),str(ROOT/'src/semver_batch.cjs')],input=json.dumps(payload),text=True,encoding='utf-8',capture_output=True,env=env,check=True)
    rows=json.loads(run.stdout)
    assert rows,'No dependency snapshots available.'
    write_csv(ROOT/'data/processed/instance_audit.csv',rows)
    ok=[r for r in rows if r['status']=='ok']
    projects=[{r['project'] for r in ok if r['origin']==o} for o in CFG['origins']]
    paired=set.intersection(*projects)
    paired_rows=[r for r in ok if r['project'] in paired]
    df=pd.DataFrame(ok);df_paired=pd.DataFrame(paired_rows)
    for name,data in [('all_available',df),('paired',df_paired)]:
        if data.empty:continue
        write_csv(ROOT/'data/processed'/(name+'.csv'),data.to_dict('records'))
        duckdb.sql('select * from data').write_parquet(str(ROOT/'data/processed'/(name+'.parquet')))
    summary={o:{'projects':len({r['project'] for r in ok if r['origin']==o}),'instances':sum(r['origin']==o for r in ok),'positive_instances':sum(r['origin']==o and r['label']==1 for r in ok),'paired_instances':sum(r['origin']==o for r in paired_rows)} for o in CFG['origins']}
    save(ROOT/'manifests/dataset.json',{'created_at':now(),'paired_projects':len(paired),'summary':summary,'status_counts':{str(k):int(v) for k,v in pd.Series([r['status'] for r in rows]).value_counts().items()},'data_sha256':{p.name:sha(p) for p in (ROOT/'data/processed').glob('*.parquet')},'source_advisories_sha256':sha(ROOT/'cache/ghsa/advisories.json')})
    print('Built paired projects:',len(paired),'instances:',len(paired_rows),flush=True)

def metrics(y,p,probability=True):
    import numpy as np
    from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss
    y=np.asarray(y);p=np.asarray(p)
    if len(np.unique(y))<2:return {'status':'single_class','n':len(y),'positive':int(y.sum())}
    budget=max(1,int(np.ceil(len(y)*.1)));order=np.argsort(-p,kind='stable')[:budget]
    result={'status':'ok','n':len(y),'positive':int(y.sum()),'positive_rate':float(y.mean()),'roc_auc':float(roc_auc_score(y,p)),'average_precision':float(average_precision_score(y,p)),'precision_top_10pct':float(y[order].mean()),'recall_top_10pct':float(y[order].sum()/y.sum())}
    if probability:result['brier']=float(brier_score_loss(y,p))
    return result

def evaluate():
    import numpy as np,pandas as pd
    from scipy.stats import mannwhitneyu
    from sklearn.pipeline import make_pipeline
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score
    data=ROOT/'data/processed/paired.csv'
    assert data.exists(),'No paired dataset available.'
    # npm package names such as "nan" and "null" are valid identifiers,
    # not pandas missing-value sentinels. Keep identifiers verbatim.
    df=pd.read_csv(data,keep_default_na=False); results=[];assoc=[];predictions=[];diffs=[]
    for origin in CFG['origins']:
        test=df[df.origin==origin]
        if test.empty:continue
        pos=test[test.label==1].libyear;neg=test[test.label==0].libyear
        pooled=np.sqrt(((len(pos)-1)*pos.var()+(len(neg)-1)*neg.var())/(len(pos)+len(neg)-2)) if min(len(pos),len(neg))>1 else np.nan
        assoc.append({'origin':origin,'instances':len(test),'positive':int(test.label.sum()),'positive_rate':float(test.label.mean()),'libyear_mean':float(test.libyear.mean()),'mean_difference':float(pos.mean()-neg.mean()) if len(pos) and len(neg) else None,'cohens_d':float((pos.mean()-neg.mean())/pooled) if np.isfinite(pooled) and pooled>0 else None,'mann_whitney_p_unadjusted':float(mannwhitneyu(pos,neg).pvalue) if len(pos) and len(neg) else None,'inference_note':'descriptive association; unadjusted p assumes independent rows and is not confirmatory'})
        train=df[(df.origin<origin)&(df.window_end<=origin)]
        if train.empty or train.label.nunique()<2:
            results.append({'origin':origin,'status':'insufficient_training_classes'});continue
        assert (train.window_end<=origin).all()
        models={'libyear_only_lr':(['libyear'],LogisticRegression(C=1,max_iter=2000,random_state=42)),'other_features_lr':([f for f in FEATURES if f!='libyear'],LogisticRegression(C=1,max_iter=2000,random_state=42)),'full_lr':(FEATURES,LogisticRegression(C=1,max_iter=2000,random_state=42)),'full_rf':(FEATURES,RandomForestClassifier(n_estimators=200,max_depth=6,min_samples_leaf=5,n_jobs=2,random_state=42))}
        scores={'constant_training_rate':np.full(len(test),train.label.mean()),'libyear_score':test.libyear.to_numpy()}
        for name,(features,clf) in models.items():
            pipe=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),clf)
            pipe.fit(train[features],train.label)
            scores[name]=pipe.predict_proba(test[features])[:,1]
        for name,p in scores.items():
            results.append({'origin':origin,'model':name,'training_origins':';'.join(sorted(train.origin.unique())),'train_instances':len(train),**metrics(test.label,p,name!='libyear_score')})
            for j,row in enumerate(test.to_dict('records')):predictions.append({'origin':origin,'project':row['project'],'package':row['package'],'used_version':row['used_version'],'dependency_type':row['dependency_type'],'label':int(row['label']),'model':name,'score':float(p[j])})
        if test.label.nunique()==2:
            groups={p:np.flatnonzero(test.package.to_numpy()==p) for p in sorted(test.package.unique())};names=list(groups);rng=np.random.default_rng(CFG['seed'])
            for a,b in [('full_lr','other_features_lr'),('full_lr','libyear_only_lr'),('full_rf','libyear_only_lr')]:
                samples=[]
                for _ in range(CFG['bootstrap_repeats']):
                    idx=np.concatenate([groups[names[i]] for i in rng.integers(0,len(names),len(names))]);y=test.label.to_numpy()[idx]
                    if len(np.unique(y))<2:continue
                    samples.append(average_precision_score(y,scores[a][idx])-average_precision_score(y,scores[b][idx]))
                delta=float(average_precision_score(test.label,scores[a])-average_precision_score(test.label,scores[b]))
                diffs.append({'origin':origin,'comparison':a+' minus '+b,'ap_difference':delta,'ci_2_5':float(np.quantile(samples,.025)) if samples else None,'ci_97_5':float(np.quantile(samples,.975)) if samples else None,'valid_bootstrap_repeats':len(samples)})
        print('Evaluated origin',origin,'train',len(train),'test',len(test),flush=True)
    save(ROOT/'results/temporal_metrics.json',results);save(ROOT/'results/associations.json',assoc);save(ROOT/'results/paired_ap_differences.json',diffs)
    write_csv(ROOT/'results/predictions.csv',predictions)
    save(ROOT/'manifests/run.json',{'completed_at':now(),'config_sha256':sha(ROOT/'config/experiment.json'),'script_sha256':sha(__file__),'semver_script_sha256':sha(ROOT/'src/semver_batch.cjs'),'dataset_sha256':sha(data),'evaluation':'retrospective backtest; historical metadata availability not fully verified','fixed_hyperparameters':True,'models':['libyear_only_lr','other_features_lr','full_lr','full_rf'],'xgboost_included':False})

def report():
    m=load(ROOT/'manifests/dataset.json');assoc=load(ROOT/'results/associations.json');results=load(ROOT/'results/temporal_metrics.json');diffs=load(ROOT/'results/paired_ap_differences.json')
    lines=['# ผล Snapshot sensitivity และ retrospective temporal backtest','ผลจาก pipeline ใหม่ ไม่ใช่ผลการทดสอบ prospective จริง ข้อมูล npm และ GHSA reconstruct จาก metadata ปัจจุบัน และ cohort ยึดโครงการที่ผ่านการคัดเลือกในข้อมูลเดิม','## ขนาดข้อมูล',f"Paired projects: {m['paired_projects']}",'| Origin | Projects | Instances | Positive | Paired instances |','| --- | --- | --- | --- | --- |']
    lines += [f"| {o} | {s['projects']} | {s['instances']} | {s['positive_instances']} | {s['paired_instances']} |" for o,s in m['summary'].items()]
    lines+=['## ทิศทางความสัมพันธ์ของ Libyear','| Origin | Positive rate | Mean difference | Cohen d |','| --- | --- | --- | --- |']
    lines += [f"| {r['origin']} | {r['positive_rate']:.4f} | {r['mean_difference']} | {r['cohens_d']} |" for r in assoc]
    lines+=['## ผล temporal backtest','| Test origin | Model | AP | ROC AUC | Positive rate |','| --- | --- | --- | --- | --- |']
    for r in results:
        if r.get('status')=='ok':lines.append(f"| {r['origin']} | {r['model']} | {r['average_precision']:.4f} | {r['roc_auc']:.4f} | {r['positive_rate']:.4f} |")
        else:lines.append(f"| {r['origin']} | {r.get('model','not fitted')} | {r['status']} | — | — |")
    lines+=['## คุณค่าส่วนเพิ่มและ uncertainty','| Origin | Comparison | AP difference | Package bootstrap 95% interval |','| --- | --- | --- | --- |']
    lines += [f"| {r['origin']} | {r['comparison']} | {r['ap_difference']:.4f} | {r['ci_2_5']} to {r['ci_97_5']} |" for r in diffs]
    lines+=['## ขอบเขตการตีความ','ไม่เลือกเฉพาะ snapshot ที่ให้ผลสนับสนุน รายงานทิศทางและขนาดผลทุกช่วง AP ขึ้นกับความชุกของ label ต้องอ่านร่วมกับ positive rate ไม่ตีความ effect size หรือ feature ablation เป็น causal effect','Paired cohort ลดการเปลี่ยนองค์ประกอบโครงการ แต่มี survivorship และ selection bias เวอร์ชันอ้างอิงอนุมานจาก root package.json ไม่ยืนยันการติดตั้งจริง กฎ latest อ้างวันเผยแพร่ ไม่จำเป็นต้องเป็น SemVer สูงสุด','GHSA collection กรอง reviewed advisories และไม่ใช้ withdrawn records metadata อาจเปลี่ยนย้อนหลัง โดยเฉพาะ affected range ผลจึงไม่ยืนยันว่า label ทุกตัวพร้อมใช้ในอดีต แม้หน้าต่าง training จะสิ้นสุดก่อน test origin','Bootstrap รวมกลุ่มตาม package ไม่ครอบคลุม crossed project-package dependence ทั้งหมด Mann Whitney p ในไฟล์ JSON เป็น exploratory ไม่ใช่หลักฐานยืนยัน significance จากแถวอิสระ','พารามิเตอร์โมเดลกำหนดไว้ก่อน test ไม่ปรับ threshold และไม่ได้ใช้ GroupKFold ไม่มี XGBoost ในรอบนี้']
    (ROOT/'reports/results.md').write_text('\n\n'.join(lines).replace('|\n\n|','|\n|')+'\n',encoding='utf-8')

def verify_sources():
    for p,h in load(ROOT/'manifests/source_hashes.json').items():assert sha(WORK/p)==h,p

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['init','collect','build','evaluate','report','all']);parser.add_argument('--limit-projects',type=int,default=0);args=parser.parse_args()
    if args.stage in ['init','all']:initialize()
    if args.stage in ['collect','all']:
        collect_advisories();collect_snapshots(args.limit_projects);collect_npm()
    if args.stage in ['build','all']:build()
    if args.stage in ['evaluate','all']:evaluate()
    if args.stage in ['report','all']:report()
    verify_sources()
    print('Stage completed:',args.stage,'legacy hashes unchanged',flush=True)

if __name__=='__main__':main()
