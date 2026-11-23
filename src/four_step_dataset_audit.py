"""Offline field/selection/all-match/label-disagreement audit; no relabeling."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter,defaultdict
import csv,json,hashlib,subprocess,os
R=Path(__file__).resolve().parents[1];P=R/'publication';O=P/'experiments/four_step';O.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00')) if s else None
def cutoff(s):return stamp(s+'T23:59:59.999Z')
def ids(r):return [s for s in r['matched_ghsa_ids'].split(';') if s]
rows=read(R/'robustness/data/date_12_paired.csv');ads=load(R/'cache/ghsa/advisories.json');admap={a['ghsa_id']:a for a in ads};cfg=load(P/'protocol/rq_completion.json')
availability=[];proxy_exclusions={};seen=[]
for origin in cfg['origins'][1:]:
    train=[r for r in rows if r['origin']<origin and r['window_end']<=origin];positive=[r for r in train if int(r['label'])]
    any_late=[];none_ready=[];missing=[]
    for r in positive:
        matches=[admap[a] for a in ids(r)];assert matches
        assert all(cutoff(r['origin'])<stamp(a['published_at'])<=cutoff(r['window_end']) and not a.get('withdrawn_at') for a in matches)
        ready=[a['ghsa_id'] for a in matches if stamp(a.get('github_reviewed_at')) and stamp(a['github_reviewed_at'])<=cutoff(origin)]
        if any(stamp(a.get('github_reviewed_at')) and stamp(a['github_reviewed_at'])>cutoff(origin) for a in matches):any_late.append(r)
        if not ready:none_ready.append(r)
        if any(not a.get('github_reviewed_at') for a in matches):missing.append(r)
    proxy_exclusions[origin]=[{k:r[k] for k in ['origin','project','package','dependency_type','used_version','matched_ghsa_ids']} for r in none_ready]
    availability.append({'test_origin':origin,'train_n':len(train),'training_positives':len(positive),'any_match_late_review':len(any_late),'no_match_reviewed_by_fit_cutoff':len(none_ready),'any_late_but_some_ready':len(any_late)-sum(r in any_late for r in none_ready),'any_missing_review':len(missing)})
    test=[r for r in rows if r['origin']==origin];known={r['package'] for r in train}
    seen.append({'origin':origin,'slices':[{ 'slice':name,'instances':len(group),'packages':len({r['package'] for r in group}),'positive_instances':sum(int(r['label']) for r in group)} for name,group in [('seen',[r for r in test if r['package'] in known]),('unseen',[r for r in test if r['package'] not in known])]]})
save(O/'availability.json',availability);save(O/'late_review_proxy_exclusions.json',proxy_exclusions);save(O/'seen_unseen_coverage.json',seen)
lock=P/'experiments/lockfile_sensitivity';a=read(lock/'inferred_matched.csv');b=read(lock/'recorded.csv')
keys=['origin','project','package','dependency_type'];key=lambda r:tuple(r[k] for k in keys)
assert [key(r) for r in a]==[key(r) for r in b]
lockmap={(r['origin'],r['project']):r for r in load(P/'audits/lockfiles.json')};package_ads=defaultdict(list)
for ad in ads:
    if ad.get('withdrawn_at'):continue
    for v in ad['vulnerabilities']:
        if v['package']['ecosystem']=='npm':package_ads[v['package']['name']].append({'id':ad['ghsa_id'],'range':v['vulnerable_version_range'],'published_at':ad['published_at'],'reviewed_at':ad.get('github_reviewed_at'),'updated_at':ad.get('updated_at')})
traces=[];payload=[]
for x,y in zip(a,b):
    if x['label']==y['label']:continue
    record=lockmap[(x['origin'],x['project'])];case=len(traces)+1
    trace={'case_id':case,**{k:x[k] for k in keys},'window_end':x['window_end'],'commit_sha':x['commit_sha'],'manifest_constraint':x['constraint'],'inferred_version':x['used_version'],'recorded_version':y['used_version'],'inferred_label':int(x['label']),'recorded_label':int(y['label']),'inferred_matched_ids':ids(x),'recorded_matched_ids':ids(y),'root_lockfile':record['lockfile'],'lockfile_sha256':record['lockfile_sha256'],'advisory_evidence':[ad for ad in package_ads[x['package']] if ad['id'] in set(ids(x)+ids(y))]}
    assert x['commit_sha']==y['commit_sha']==record['commit_sha']
    for arm,row in [('inferred',x),('recorded',y)]:payload.append({'case_id':case,'arm':arm,'origin':row['origin'],'window_end':row['window_end'],'version':row['used_version'],'advisories':package_ads[row['package']]})
    traces.append(trace)
runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies';env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(runtime/'node/node_modules')
checked=json.loads(subprocess.check_output([str(runtime/'node/bin/node.exe'),str(R/'src/four_step_range_check.cjs')],input=json.dumps(payload),text=True,encoding='utf-8',env=env))
for row in checked:
    trace=traces[row['case_id']-1];expected=sorted(trace[row['arm']+'_matched_ids'])
    assert not row['invalid_ids'] and row['matched_ids']==expected,(row,expected)
assert len(traces)==32 and len(checked)==64
save(O/'lockfile_label_traces.json',traces)
frame=load(R/'data/cohort/projects.json');allrows=read(R/'data/processed/all_available.csv');paired={r['project'] for r in rows};allprojects={r['project'] for r in allrows}
selection={'frame_strata':dict(Counter(r['stratum'] for r in frame)),'paired_strata':dict(Counter(r['stratum'] for r in frame if r['project'] in paired)),'excluded_strata':dict(Counter(r['stratum'] for r in frame if r['project'] not in paired)),'all_available_projects':len(allprojects),'frame_projects':len(frame),'paired_projects':len(paired),'excluded_projects':[r for r in frame if r['project'] not in paired]}
save(O/'selection.json',selection)
inputs=[R/'robustness/data/date_12_paired.csv',R/'data/processed/all_available.csv',R/'cache/ghsa/advisories.json',lock/'recorded.csv',lock/'inferred_matched.csv',P/'audits/lockfiles.json',P/'protocol/four_step_followup.json',Path(__file__),R/'src/four_step_range_check.cjs']
save(O/'audit_validation.json',{'passed':True,'checked_at':datetime.now(timezone.utc).isoformat(),'all_disagreement_instances':len(traces),'range_checks':len(checked),'trace_method':'automated frozen-record consistency review; same SemVer library as construction; not independent vulnerability adjudication or archived-history verification','inputs':{p.relative_to(R).as_posix():sha(p) for p in inputs}})
print(json.dumps({'availability':availability,'selection':selection,'trace_checks':len(checked)},ensure_ascii=False,indent=2))
