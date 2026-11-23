// Offline consistency check of traced labels using the recorded SemVer engine.
const fs=require('fs');
const semver=require(require.resolve('semver',{paths:[process.env.SNAPSHOT_NODE_MODULES]}));
const rows=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(rows.map(row=>{
  const start=Date.parse(row.origin+'T23:59:59.999Z'),end=Date.parse(row.window_end+'T23:59:59.999Z');
  const matches=[],invalid=[];
  for(const a of row.advisories){
    if(!(start<Date.parse(a.published_at)&&Date.parse(a.published_at)<=end))continue;
    const range=semver.validRange(a.range.replace(/,/g,' '));
    if(range===null){invalid.push(a.id);continue;}
    if(semver.satisfies(row.version,range))matches.push(a.id);
  }
  return {case_id:row.case_id,arm:row.arm,matched_ids:[...new Set(matches)].sort(),invalid_ids:invalid};
})));
