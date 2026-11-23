"""Read-only reconciliation of inherited project selection; never import legacy settings."""
from pathlib import Path
import sys,json,csv,hashlib,collections
R=Path(__file__).resolve().parents[1]; W=R.parent; P=R/'publication'
sys.path.insert(0,str(R/'tools/vendor'))
import duckdb
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):
    return list(csv.DictReader(p.open(encoding='utf-8',newline='')))
files={'raw_projects':W/'replicability/data/raw/projects.parquet','legacy_instances':W/'replicability/data/raw/instances.parquet','legacy_features':W/'replicability/data/processed/features_labeled.parquet'}
out={'inputs':{},'tables':{}}
sets={}
for name,p in files.items():
    cursor=duckdb.sql('select * from read_parquet(?)',params=[str(p)])
    columns=cursor.columns
    records=[dict(zip(columns,row)) for row in cursor.fetchall()]
    project_column='project' if 'project' in columns else 'full_name'
    projects={str(row[project_column]) for row in records}; sets[name]=projects
    strata=collections.defaultdict(set)
    for row in records:strata[str(row.get('stratum','unrecorded'))].add(str(row[project_column]))
    out['inputs'][name]={'path':p.relative_to(W).as_posix(),'sha256':sha(p)}
    out['tables'][name]={'rows':len(records),'projects':len(projects),'columns':columns,'unique_projects_by_stratum':{k:len(v) for k,v in strata.items()}}
    if name=='raw_projects':
        out['raw_project_metadata']=[{k:str(v) if v is not None else None for k,v in row.items()} for row in records]
cohort=json.loads((R/'data/cohort/projects.json').read_text(encoding='utf-8'))
sets['snapshot_frame']={r['project'] for r in cohort}
for name,p in [('all_available',R/'data/processed/all_available.csv'),('paired',R/'robustness/data/date_12_paired.csv')]:
    records=read(p);sets[name]={r['project'] for r in records}
    out['tables'][name]={'rows':len(records),'projects':len(sets[name])}
out['differences']={f'{a}_minus_{b}':sorted(sets[a]-sets[b]) for a,b in [('raw_projects','legacy_instances'),('legacy_instances','legacy_features'),('legacy_features','snapshot_frame'),('snapshot_frame','legacy_features'),('snapshot_frame','paired')]}
status=json.loads((R/'manifests/snapshot_collection.json').read_text(encoding='utf-8'))['statuses']
out['excluded_from_paired']=[{'project':p,'collection_records':[r for r in status if r['project']==p],'eligible_instances_by_origin':dict(collections.Counter(r['origin'] for r in read(R/'data/processed/all_available.csv') if r['project']==p))} for p in sorted(sets['snapshot_frame']-sets['paired'])]
out['source_hashes']={p.relative_to(W).as_posix():sha(p) for p in [W/'replicability/src/collection/01_select_projects.py',W/'replicability/config/settings.py']}
out['limits']=['Current selection code is not an archived execution log.','Historical candidate search responses, inclusion probabilities and complete reason-coded original attrition logs have not been located.','250 is the inherited analyzed frame, not a retrospectively justified power target.']
target=P/'audits/sampling_provenance.json';target.write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
print(json.dumps({'tables':out['tables'],'differences':{k:len(v) for k,v in out['differences'].items()}},indent=2))
