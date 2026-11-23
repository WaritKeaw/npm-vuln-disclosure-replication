"""Meaningful checks for SemVer resolution, unknown labels and time boundaries."""
import importlib.util,json,os,subprocess,unittest,tempfile
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('snapshot_pipeline',ROOT/'src/pipeline.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class Boundaries(unittest.TestCase):
    def run_row(self,constraint='^0.2.3',advisories=None):
        row={'project':'owner/repo','package':'sample','constraint':constraint,'origin':'2021-12-31','window_end':'2022-12-31'}
        times={'0.2.3':'2021-01-01T00:00:00Z','0.2.9':'2021-02-01T00:00:00Z','0.3.0':'2021-03-01T00:00:00Z','0.2.10':'2022-01-01T00:00:00Z','0.2.11-beta.1':'2021-06-01T00:00:00Z'}
        data={'rows':[row],'times':{'sample':times},'advisories':{'sample':advisories or []}}
        env=os.environ.copy();env['SNAPSHOT_NODE_MODULES']=str(p.RUNTIME/'node/node_modules')
        r=subprocess.run([str(p.NODE),str(ROOT/'src/semver_batch.cjs')],input=json.dumps(data),capture_output=True,text=True,encoding='utf-8',env=env,check=True)
        return json.loads(r.stdout)[0]
    def advisory(self,published,range='>= 0.2.0, < 0.3.0'):
        return {'id':'GHSA-test','published_at':published,'updated_at':'2026-01-01T00:00:00Z','range':range}
    def test_zero_major_caret_does_not_cross_minor(self):
        r=self.run_row();self.assertEqual(r['used_version'],'0.2.9');self.assertEqual(r['total_versions'],3)
    def test_comparison_range_has_no_highest_version_fallback(self):
        self.assertEqual(self.run_row('>=0.2.3 <0.2.9')['used_version'],'0.2.3')
    def test_alias_is_excluded(self):self.assertEqual(self.run_row('npm:other@1.0.0')['status'],'unsupported_constraint')
    def test_publication_at_origin_is_not_future_label(self):
        self.assertEqual(self.run_row(advisories=[self.advisory('2021-12-31T23:59:59.999Z')])['label'],0)
    def test_next_day_and_end_of_horizon_are_positive(self):
        for date in ['2022-01-01T00:00:00Z','2022-12-31T23:59:59.999Z']:
            self.assertEqual(self.run_row(advisories=[self.advisory(date)])['label'],1)
    def test_after_horizon_is_not_label(self):
        self.assertEqual(self.run_row(advisories=[self.advisory('2023-01-01T00:00:00Z')])['label'],0)
    def test_invalid_affected_range_is_unknown_not_negative(self):
        r=self.run_row(advisories=[self.advisory('2022-01-01T00:00:00Z','unparseable range')]);self.assertIsNone(r['label']);self.assertEqual(r['status'],'invalid_advisory_range')
    def test_calendar_horizon(self):self.assertEqual(p.end_date('2020-12-31'),'2021-12-31')
    def test_missing_affected_range_is_unknown(self):
        r=self.run_row(advisories=[self.advisory('2022-01-01T00:00:00Z',None)]);self.assertIsNone(r['label'])
    def test_future_only_version_is_not_used(self):
        self.assertEqual(self.run_row('0.2.10')['status'],'no_matching_version_at_origin')
    def test_partial_cache_resume_keeps_all_origin_statuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);repo=root/'cache/git'/p.key('owner/repo');repo.mkdir(parents=True);(repo/'HEAD').write_text('ref: refs/heads/main')
            for origin in p.CFG['origins'][1:]:
                file=root/'cache/snapshots'/origin/(p.key('owner/repo')+'.json');file.parent.mkdir(parents=True);file.write_text('{}')
            def fake_git(args,timeout=180):
                if 'rev-parse' in args:return 'a'*40
                if 'log' in args:return 'a'*40+' 2021-01-01T00:00:00+00:00'
                raise AssertionError('unexpected network operation')
            with patch.object(p,'ROOT',root),patch.object(p,'git',side_effect=fake_git):result=p.collect_project({'project':'owner/repo','stratum':'low'})
            self.assertEqual(len(result),4);self.assertEqual({r['origin'] for r in result},set(p.CFG['origins']))

if __name__=='__main__':unittest.main()
