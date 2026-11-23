"""Audit frozen cache chronology, dependence, and same-commit root lockfiles."""
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter,defaultdict
import csv,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'publication/audits';OUT.mkdir(parents=True,exist_ok=True)
GIT=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8',newline='') as stream:return list(csv.DictReader(stream))
def csvwrite(p,records):
    keys=list(dict.fromkeys(k for r in records for k in r))
    with p.open('w',encoding='utf-8',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=keys);w.writeheader();w.writerows(records)
def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00')) if value else None
def cutoff(origin):return stamp(origin+'T23:59:59.999Z')
def locked_version(lock,name):
    if isinstance(lock.get('packages'),dict):return lock['packages'].get('node_modules/'+name,{}).get('version')
    return lock.get('dependencies',{}).get(name,{}).get('version')
def run():
    data=ROOT/'robustness/data/date_12_paired.csv';frame=rows(data);advisories=load(ROOT/'cache/ghsa/advisories.json');admap={a['ghsa_id']:a for a in advisories}
    protected=load(ROOT/'robustness/manifests/protected_inputs.json')
    for p,h in protected.items():assert digest(Path(p))==h,p
    complete=load(ROOT/'cache/ghsa/complete.json')
    for page in complete['pages']:assert digest(ROOT/'cache/ghsa'/page['file'])==page['sha256']
    expected_pages=[]
    timeline=[]
    for a in advisories:
        published=stamp(a['published_at']);reviewed=stamp(a.get('github_reviewed_at'));updated=stamp(a.get('updated_at'))
        timeline.append({'ghsa_id':a['ghsa_id'],'published_at':a['published_at'],'github_reviewed_at':a.get('github_reviewed_at'),'updated_at':a.get('updated_at'),'review_delay_days':(reviewed-published).total_seconds()/86400 if reviewed else None,'withdrawn':bool(a.get('withdrawn_at'))})
    csvwrite(OUT/'advisory_timeline.csv',timeline)
    dependence=[];training=[];coverage=[]
    bysnapshot=defaultdict(list)
    for r in frame:bysnapshot[(r['origin'],r['project'])].append(r)
    for origin in sorted({r['origin'] for r in frame}):
        test=[r for r in frame if r['origin']==origin];positive=[r for r in test if r['label']=='1'];pc=Counter(r['package'] for r in positive)
        ids=Counter(a for r in positive for a in r['matched_ghsa_ids'].split(';') if a)
        sizes=Counter(r['package'] for r in test)
        dependence.append({'origin':origin,'instances':len(test),'projects':len({r['project'] for r in test}),'packages':len(sizes),'package_version_pairs':len({(r['package'],r['used_version']) for r in test}),'positive_instances':len(positive),'positive_packages':len(pc),'positive_package_versions':len({(r['package'],r['used_version']) for r in positive}),'unique_matched_advisories':len(ids),'max_instances_per_package':max(sizes.values()),'top_5_positive_packages_share':sum(v for _,v in pc.most_common(5))/len(positive),'top_5_positive_packages':pc.most_common(5),'top_5_matching_advisories':ids.most_common(5)})
        if origin==min(x['origin'] for x in frame):continue
        train=[r for r in frame if r['origin']<origin and r['window_end']<=origin];pos=[r for r in train if r['label']=='1'];after_review=[];after_update=[];missing=[]
        for r in pos:
            matched=[admap[a] for a in r['matched_ghsa_ids'].split(';') if a]
            if any(stamp(a.get('github_reviewed_at')) and stamp(a['github_reviewed_at'])>cutoff(origin) for a in matched):after_review.append(r)
            if any(stamp(a.get('updated_at')) and stamp(a['updated_at'])>cutoff(origin) for a in matched):after_update.append(r)
            if any(not a.get('github_reviewed_at') for a in matched):missing.append(r)
        training.append({'test_origin':origin,'train_instances':len(train),'positive_training_instances':len(pos),'positive_instances_any_matching_review_after_test_origin':len(after_review),'positive_instances_any_matching_update_after_test_origin':len(after_update),'positive_instances_missing_review_time':len(missing),'interpretation':'updated_at after cutoff flags a newer metadata vintage; it does not prove affected range changed. Late review establishes reviewed status was not yet reached for that matched record, not necessarily that all matching information was unavailable.'})
        coverage.append({'test_origin':origin,'test_packages_seen_in_training':len({r['package'] for r in test}&{r['package'] for r in train}),'test_packages_total':len({r['package'] for r in test}),'test_projects_seen_in_training':len({r['project'] for r in test}&{r['project'] for r in train})})
    save(OUT/'dependence.json',dependence);save(OUT/'training_availability.json',training);save(OUT/'train_test_overlap.json',coverage)
    # Same-commit lockfile presence and recorded top-level resolutions; no cohort/label change.
    locks=[];snapshot_files=list((ROOT/'cache/snapshots').glob('*/*.json'))
    for i,path in enumerate(snapshot_files):
        snapshot=load(path);key=(path.parent.name,snapshot.get('project'))
        if key not in bysnapshot:continue
        commit=snapshot.get('commit_sha');repo=ROOT/'cache/git'/path.stem
        if not commit:continue
        command=[str(GIT),'-C',str(repo),'ls-tree','--name-only',commit,'--','package-lock.json','npm-shrinkwrap.json','yarn.lock','pnpm-lock.yaml']
        checked=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
        entry={'origin':key[0],'project':key[1],'commit_sha':commit,'instances':len(bysnapshot[key]),'tree_read_ok':checked.returncode==0,'lockfiles':checked.stdout.strip().splitlines() if checked.returncode==0 else [],'parse_status':'no_supported_npm_lockfile','compared_instances':0,'matching_reference_instances':0,'different_reference_instances':0,'missing_root_resolution_instances':0}
        preferred=next((name for name in ['npm-shrinkwrap.json','package-lock.json'] if name in entry['lockfiles']),None)
        if preferred:
            blob=subprocess.run([str(GIT),'-C',str(repo),'show',commit+':'+preferred],capture_output=True)
            try:
                lock=json.loads(blob.stdout.decode('utf-8-sig'));entry.update({'lockfile':preferred,'lockfile_version':lock.get('lockfileVersion'),'lockfile_sha256':hashlib.sha256(blob.stdout).hexdigest(),'parse_status':'ok'})
                for r in bysnapshot[key]:
                    version=locked_version(lock,r['package'])
                    if version is None:entry['missing_root_resolution_instances']+=1;continue
                    entry['compared_instances']+=1
                    entry['matching_reference_instances' if version==r['used_version'] else 'different_reference_instances']+=1
            except (UnicodeDecodeError,json.JSONDecodeError,AttributeError) as error:entry['parse_status']='parse_error';entry['error']=type(error).__name__
        locks.append(entry)
        if (i+1)%100==0:print('Audited snapshot files',i+1,flush=True)
    save(OUT/'lockfiles.json',locks)
    assert len(locks)==len(bysnapshot),(len(locks),len(bysnapshot))
    summary={'status':'completed_cache_and_same_commit_lockfile_audit','advisory_count':len(advisories),'advisories_missing_review_time':sum(not a.get('github_reviewed_at') for a in advisories),'advisories_reviewed_after_publication':sum(stamp(a.get('github_reviewed_at')) and stamp(a['github_reviewed_at'])>stamp(a['published_at']) for a in advisories),'snapshot_project_cells':len(locks),'cells_with_any_root_lockfile':sum(bool(r['lockfiles']) for r in locks),'cells_with_supported_parsed_npm_lockfile':sum(r['parse_status']=='ok' for r in locks),'tree_read_failures':sum(not r['tree_read_ok'] for r in locks),'lockfile_compared_instances':sum(r['compared_instances'] for r in locks),'lockfile_matching_reference_instances':sum(r['matching_reference_instances'] for r in locks),'lockfile_different_reference_instances':sum(r['different_reference_instances'] for r in locks),'missing_root_resolution_instances':sum(r['missing_root_resolution_instances'] for r in locks),'collected_cache_at':complete['completed_at'],'publication_coverage':[complete['published_start'],complete['published_end']],'historical_record_versions_verified':False,'npm_timestamp_history_verified':False,'source_data_sha256':digest(data),'completed_at':datetime.now(timezone.utc).isoformat()}
    save(OUT/'summary.json',summary)
    for p,h in protected.items():assert digest(Path(p))==h,p
    save(OUT/'validation.json',{'passed':True,'protected_inputs_unchanged':True,'ghsa_pagination_page_hashes_verified':len(complete['pages']),'all_paired_project_origins_audited':len(locks),'lockfile_counts_reconcile':summary['lockfile_compared_instances']==summary['lockfile_matching_reference_instances']+summary['lockfile_different_reference_instances'],'audit_source_sha256':digest(Path(__file__))})
    print('Audit complete',summary,flush=True)
if __name__=='__main__':run()
