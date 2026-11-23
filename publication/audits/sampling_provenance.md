# Sampling provenance reconciliation

16 October 2026. Counts below come from the actual protected files, not the legacy data dictionary. Original files were read only. SHA256 values, schemas and set differences are in [machine-readable audit](sampling_provenance.json).

| Stage | Rows | Distinct projects | High / medium / low / niche |
| --- | --- | --- | --- |
| raw_projects | 342 | 342 | 47 / 165 / 91 / 39 |
| legacy_instances | 7883 | 251 | 33 / 132 / 60 / 26 |
| legacy_features | 7693 | 250 | 33 / 131 / 60 / 26 |
| all_available | 30380 | 249 | — / — / — / — |
| paired | 29379 | 238 | — / — / — / — |

The raw selected file contains 342 distinct projects. The original instance file contains 251; 91 raw project IDs are absent. The feature/label file retains 250, losing browserstate/history.js. All 250 feature-file project IDs exactly match the repeated-snapshot frame. The all-available reconstruction contains 249 distinct projects across the four origins; 238 satisfy at least one eligible instance at every origin. Thus 250 denotes an inherited analyzed frame, not the initial collection count or a planned sample-size target. Original row counts for instances are 7,883, not 7,763 in the stale dictionary. No legacy dictionary or raw file was overwritten.

The available selection source seeds random sampling with 42, enumerates a high-star tier and draws from returned search candidates in other tiers. Its docstring allocations differ from current settings (medium 180, low 100, niche 50; high has no target). Observed raw counts also differ from those settings. These are code/config observations, not evidence of which exact revision executed. Search truncation and a high-tier inclusion rule do not establish an ecosystem census or known inclusion probabilities. The source's license filter also allows EvanLi-origin entries without license information; an unconditional nonmissing-license claim is inaccurate.

The files identify attrition sets, but the original candidate search responses, executed collection revision and complete reasons for the 91+1 original losses were not located in the inspected collection/config/data directories. Do not infer that each was excluded for having no pre-cutoff commit. A current query or a new random draw cannot restore the original probabilities. Obtain archived logs if they exist; otherwise report this limit. Current stars must not be reinterpreted as historical predictor values.

## Twelve frame projects excluded from the paired cohort

Each cell reports eligible instance count and recorded snapshot collection status. A cached manifest with zero eligible rows differs from a missing commit/manifest. Error status may reflect collection limitations rather than the repository's true historical nonexistence. Detailed recorded errors remain in the JSON audit.

| Project | 2020 | 2021 | 2022 | 2023 |
| --- | --- | --- | --- | --- |
| Snailclimb/JavaGuide | 0; package_json_unavailable | 3; cached | 0; cached | 7; cached |
| ToolJet/ToolJet | 0; no_commit_at_origin | 15; cached | 4; cached | 4; cached |
| airbnb/javascript | 2; cached | 0; cached | 0; cached | 2; cached |
| automatisch/automatisch | 0; no_commit_at_origin | 1; cached | 7; cached | 7; cached |
| clientIO/joint | 58; cached | 65; cached | 65; cached | 0; cached |
| gatsbyjs/gatsby | 0; package_json_unavailable | 88; ok | 65; ok | 66; ok |
| louislam/uptime-kuma | 0; no_commit_at_origin | 70; cached | 100; cached | 127; cached |
| microsoft/Web-Dev-For-Beginners | 0; package_json_unavailable | 1; cached | 1; cached | 1; cached |
| notionnext-org/NotionNext | 0; no_commit_at_origin | 37; cached | 51; cached | 42; cached |
| philc/vimium | 2; cached | 2; cached | 0; package_json_unavailable | 0; package_json_unavailable |
| pistazie/cdk-dia | 0; no_commit_at_origin | 36; cached | 36; cached | 36; cached |
| videojs/video.js | 0; no_commit_at_origin | 0; no_commit_at_origin | 0; no_commit_at_origin | 0; no_commit_at_origin |

## Size rationale and inference

This study reuses the original analyzed frame to compare definitions and times on a common basis. It does not claim 250 is an a priori powered or representative sample. No posthoc power estimate is used to manufacture a justification. Report intervals, positive-cluster counts and concentration as actual precision evidence; many dependency rows share packages/advisories. Wide or cluster-sensitive intervals remain inconclusive for small practical effects. Inclusion probabilities and candidate frame coverage cannot be recovered from row counts.

Recommendation: describe this as an inherited, stratified collection with observed attrition and uncertain historical selection provenance. This addresses transparent reporting while leaving C2-2 partially unresolved scientifically. A new representative collection would change the dataset and requires a separate scope decision.
