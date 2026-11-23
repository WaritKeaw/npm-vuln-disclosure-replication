"""Preserve executed source, reconcile cached collection cells and explain results."""
from pathlib import Path
import hashlib,json,shutil,re
ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
run=load(ROOT/'manifests/run.json');archive=ROOT/'manifests/code';archive.mkdir(exist_ok=True)
for field,file in [('script_sha256',ROOT/'src/pipeline.py'),('semver_script_sha256',ROOT/'src/semver_batch.cjs')]:
    target=archive/(file.stem+'_'+run[field]+file.suffix)
    if not target.exists():
        assert digest(file)==run[field],file
        shutil.copy2(file,target)
    assert digest(target)==run[field]
    run['archived_'+field]=str(target.relative_to(ROOT))
save(ROOT/'manifests/run.json',run)
old=load(ROOT/'manifests/snapshot_collection.json')
backup=ROOT/'manifests/snapshot_collection_before_reconcile.json'
if not backup.exists():shutil.copy2(ROOT/'manifests/snapshot_collection.json',backup)
lookup={(r['project'],r['origin']):r for r in old['statuses']}
projects=load(ROOT/'data/cohort/projects.json');cfg=load(ROOT/'config/experiment.json');rows=[]
for project in projects:
    name=project['project'];key=hashlib.sha256(name.encode()).hexdigest()[:24]
    for origin in cfg['origins']:
        file=ROOT/'cache/snapshots'/origin/(key+'.json')
        if file.exists():
            snap=load(file);assert snap['project']==name and snap['origin']==origin
            r={**lookup.get((name,origin),{'project':name,'origin':origin,'status':'cached'}),'snapshot_file':str(file.relative_to(ROOT)),'snapshot_sha256':digest(file),'commit_sha':snap['commit_sha']}
        else:
            assert (name,origin) in lookup,'unrecorded missing snapshot'
            r=lookup[(name,origin)]
        rows.append(r)
assert len(rows)==1000 and len({(r['project'],r['origin']) for r in rows})==1000
save(ROOT/'manifests/snapshot_collection.json',{**old,'statuses':rows,'cache_status_reconciled':True})
report=ROOT/'reports/results.md';text=report.read_text(encoding='utf-8')
summary='''## ข้อค้นพบสำคัญ

ทิศทางของ Libyear ไม่คงทนทุก snapshot โดย mean difference ระหว่างกลุ่มที่มีและไม่พบรายงานเข้าเงื่อนไขเป็น +0.458, +0.473, -0.173 และ +0.166 ปี ตาม origins 2020, 2021, 2022 และ 2023 การกลับทิศในปี 2022 ไม่ใช่ข้อยืนยันว่าความล้าสมัยช่วยป้องกันช่องโหว่ แต่จำกัด claim ว่าความสัมพันธ์เป็นบวกสม่ำเสมอ

การเพิ่ม Libyear เข้า LR ที่มี features อื่นแล้วให้ AP difference +0.00350, -0.00498 และ -0.00080 ใน test origins 2021, 2022 และ 2023 ช่วง package-cluster bootstrap คร่อมศูนย์ทั้งสามช่วง จึงยังไม่มีหลักฐานที่คงทนของคุณค่าส่วนเพิ่มภายใต้ชุด features นี้ ไม่ใช่การพิสูจน์ว่า Libyear ไม่มีประโยชน์ในทุกบริบท

Full LR และ Full RF ให้ AP สูงกว่า Libyear-only LR ในทั้งสาม test origins และช่วง bootstrap ของส่วนต่างที่รายงานเป็นบวก แต่ข้อสรุปจำกัดที่ paired cohort นี้ ภายใต้ retrospective metadata และการรวมกลุ่มตาม package

'''
if '## ข้อค้นพบสำคัญ' not in text:text=text.replace('## ขนาดข้อมูล',summary+'## ขนาดข้อมูล',1)
text=re.sub(r'^Paired projects: 238.*$','Paired projects: 238 จาก source cohort 250 โครงการ ตารางขนาดข้อมูลด้านล่างใช้ all-available ต่อ origin ส่วน associations และ temporal metrics ใช้ paired cohort เท่านั้น',text,flags=re.MULTILINE)
section='';pretty=[]
for line in text.splitlines():
    if line.startswith('## '):section=line
    if line.startswith('| 20') and section in ['## ทิศทางความสัมพันธ์ของ Libyear','## คุณค่าส่วนเพิ่มและ uncertainty']:
        cells=[c.strip() for c in line.strip('|').split('|')]
        if section=='## ทิศทางความสัมพันธ์ของ Libyear':
            for i in [2,3]:cells[i]=f'{float(cells[i]):.4f}'
        else:
            cells[2]=f'{float(cells[2]):.4f}'
            cells[3]=' to '.join(f'{float(c):.4f}' for c in cells[3].split(' to '))
        line='| '+' | '.join(cells)+' |'
    pretty.append(line)
text='\n'.join(pretty)+'\n'
verification='''

## การตรวจสอบก่อนส่งผล

Boundary และ partial-cache resume tests ผ่าน 11 ข้อ ตรวจข้อมูลจริงผ่านทั้ง feature publication cutoff, fixed horizon, paired-cohort identity, training-window maturity, prediction coverage และ source hashes เดิม มี predictions 132,012 แถวจาก 6 scores/models ใน 3 ช่วงทดสอบ

Collection ledger ถูกตรวจครบ 1,000 project-origin cells ข้อมูลที่ไม่พบ commit หรือ root package.json แยกเป็น missing ไม่สร้างแถวเทียม npm 77 package ตอบ 404 และถูกบันทึกไว้ใน manifests/npm_collection.json

Executed source เก็บตาม hash ใน manifests/code และอ้างผ่าน manifests/run.json เพื่อคงเวอร์ชันที่ใช้ได้ แม้จะปรับโค้ดการเก็บข้อมูลภายหลัง ผล pilot แยกไว้ใน reports/pilot และไม่ใช้สรุปผลนี้
'''
if '## การตรวจสอบก่อนส่งผล' in text:text=text.split('## การตรวจสอบก่อนส่งผล')[0].rstrip()
text+=verification
report.write_text(text,encoding='utf-8')
interpretation='''# ถ้อยคำเสนอสำหรับปรับบทผลและอภิปราย

## ผล sensitivity ที่ควรรายงาน

เมื่อใช้ paired cohort 238 โครงการ สร้าง features ณ สิ้นปี 2020–2023 และใช้ outcome การเผยแพร่ GHSA ใน 12 เดือนถัดไป พบว่าทิศทางความสัมพันธ์ของ Libyear แตกต่างตาม origin Mean difference เป็นบวกในปี 2020 2021 และ 2023 แต่เป็นลบในปี 2022 จึงไม่สรุปว่าลิบเยียร์สูงสัมพันธ์กับ outcome มากขึ้นอย่างสม่ำเสมอในทุกช่วงที่ศึกษา

## คุณค่าการทำนายส่วนเพิ่ม

การเพิ่ม Libyear เข้า Logistic Regression ที่มีคุณลักษณะอื่นแล้วไม่ได้ให้ผลเพิ่ม AP ที่คงทนข้ามช่วง โดยผลต่างมีทั้งบวกและลบ และช่วง package-cluster bootstrap คร่อมศูนย์ทุกช่วงทดสอบ ข้อมูลนี้จึงยังไม่สนับสนุนคุณค่าส่วนเพิ่มที่ชัดเจนของ Libyear ภายใต้ feature set และ cohort ที่ศึกษา แม้โมเดลหลาย features ให้ผลเหนือ Libyear-only LR

## Contribution ที่ตรงกับผล

งานนี้แสดงว่าข้อค้นพบจาก snapshot เดียวอาจเปลี่ยนตามวันอ้างอิงและหน้าต่างการเผยแพร่รายงาน และประเมินข้อจำกัดของ Libyear ในฐานะสัญญาณเดี่ยวเทียบกับคุณลักษณะแพ็กเกจหลายตัว ไม่จำเป็นต้องพบว่า Libyear ดีขึ้นทุกช่วงเพื่อให้งานมีคุณค่า แต่ต้องรายงานผลทุกช่วงตาม protocol

## ขอบเขตข้อสรุป

ผลเป็น retrospective reconstruction ของโครงการที่คัดเลือกและข้อมูล npm กับ GHSA ปัจจุบัน ไม่ยืนยันการไม่มีช่องโหว่ในคลาสลบ วันเริ่มมีช่องโหว่ หรือความพร้อมของ metadata ทั้งหมดในอดีต ไม่ตีความผล association หรือ ablation เป็น causal effect และไม่ขยายผลสู่ npm ทั้งระบบนิเวศ

การคงประสิทธิภาพตามเวลาต้องอภิปรายโดยอ้างคะแนนแต่ละช่วงคู่กับ positive rate ไม่ใช้เฉพาะ AP ที่สูงกว่าเพื่อยืนยันความคงทนระหว่างช่วงซึ่งมีความชุกและ dependency ต่างกัน

## ส่วนที่ยังไม่ทดลอง

รอบนี้รัน LR RF และ baseline พร้อม Libyear ablation ยังไม่ได้รัน XGBoost ไม่ได้ทดสอบ horizon 6 เดือน และยังไม่มี archived as-of advisory records สำหรับยืนยัน historical availability แบบสมบูรณ์
'''
(ROOT/'docs/04_result_interpretation.md').write_text(interpretation,encoding='utf-8')
print('Archived executed sources; reconciled 1,000 cells; finalized interpretation.')
