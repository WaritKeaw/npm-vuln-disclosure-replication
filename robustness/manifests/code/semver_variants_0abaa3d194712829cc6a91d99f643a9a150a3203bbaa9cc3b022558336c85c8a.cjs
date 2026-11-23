const fs = require('fs');
const path = require('path');
const semver = require(require.resolve('semver', {paths:[process.env.SNAPSHOT_NODE_MODULES]}));
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = input.rows.map(row => {
  const times = input.times[row.package] || {};
  const origin = Date.parse(row.origin + 'T23:59:59.999Z');
  const end = Date.parse(row.window_end + 'T23:59:59.999Z');
  const versions = Object.entries(times).filter(([v,d]) => semver.valid(v) && !semver.prerelease(v) && Number.isFinite(Date.parse(d)) && Date.parse(d) <= origin);
  const range = typeof row.constraint === 'string' ? semver.validRange(row.constraint) : null;
  if (!range || /^(npm:|git|http|file:|workspace:|link:|portal:)/.test(row.constraint) || ['*','latest','next',''].includes(row.constraint)) return {...row,status:'unsupported_constraint'};
  const used = semver.maxSatisfying(versions.map(x=>x[0]),range);
  if (!used) return {...row,status:'no_matching_version_at_origin'};
  versions.sort((a,b)=>Date.parse(a[1])-Date.parse(b[1]) || semver.compare(a[0],b[0]));
  const latest = input.latest_rule==='highest_semver' ? versions.reduce((a,b)=>semver.gt(b[0],a[0])?b:a) : versions[versions.length-1];
  const usedDate = Date.parse(times[used]);
  let prev=used, major=0,minor=0,patch=0;
  for (const [v,d] of versions.filter(x=>Date.parse(x[1])>usedDate)) {
    const a=semver.parse(prev),b=semver.parse(v);
    if (b.major>a.major) major++;
    else if (b.major===a.major && b.minor>a.minor) minor++;
    else if (b.major===a.major && b.minor===a.minor && b.patch>a.patch) patch++;
    prev=v;
  }
  let invalid=0;
  const matched=[];
  for (const a of input.advisories[row.package] || []) {
    const pub=Date.parse(a.published_at);
    if (!(origin<pub && pub<=end)) continue;
    const r=typeof a.range==='string' ? semver.validRange(a.range.replace(/,/g,' ')) : null;
    if (r===null) {invalid++;continue;}
    if (semver.satisfies(used,r)) matched.push(a);
  }
  const day=86400000, age=Math.floor((origin-Date.parse(versions[0][1]))/day)/30;
  const rawLibyear=Math.floor((Date.parse(latest[1])-usedDate)/day)/365;
  const libyear=input.clamp_negative ? Math.max(0,rawLibyear) : rawLibyear;
  return {...row,status:invalid?'invalid_advisory_range':'ok',used_version:used,used_version_date:times[used],latest_version:latest[0],latest_version_date:latest[1],libyear,raw_libyear:rawLibyear,negative_libyear:Number(rawLibyear<0),major_versions_behind:major,minor_versions_behind:minor,patch_versions_behind:patch,release_frequency:age>0?versions.length/age:0,package_age:age,total_versions:versions.length,days_since_latest_release:Math.floor((origin-Date.parse(latest[1]))/day),is_post_1_0:Number(semver.major(used)>=1),label:invalid?null:Number(matched.length>0),matched_ghsa_ids:[...new Set(matched.map(a=>a.id))].join(';'),matched_advisories_updated_after_origin:matched.filter(a=>Date.parse(a.updated_at)>origin).length};
});
process.stdout.write(JSON.stringify(result));
