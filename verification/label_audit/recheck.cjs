// Independent re-check of label logic: for each row, label should be 1 iff some in-window advisory range is satisfied.
const fs=require('fs');const semver=require(require.resolve('semver',{paths:[process.env.NM]}));
const rows=JSON.parse(fs.readFileSync(0,'utf8'));let agree=0,dis=[],invalid=0;
for(const r of rows){let hit=false;for(const a of r.adv){const rg=semver.validRange(String(a.range).replace(/,/g,' '));if(rg===null){invalid++;continue}if(semver.satisfies(r.used_version,rg))hit=true}
 if((hit?1:0)===r.label)agree++;else dis.push(r)}
console.log(JSON.stringify({checked:rows.length,agree,disagree:dis.length,invalid_ranges:invalid,examples:dis.slice(0,5)}));
