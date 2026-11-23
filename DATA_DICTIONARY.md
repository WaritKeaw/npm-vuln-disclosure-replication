# Data dictionary

Definitions follow the code that produced the files (`src/pipeline.py`, `src/semver_batch.cjs`, `src/publication_completion.py`) and Table 2 of the article. All dates and times are UTC. A reference date (origin) *o* such as `2021-12-31` means the end of that day (`2021-12-31T23:59:59.999Z`); only data published on or before *o* are used for features.

## `data/processed/paired.csv` (and `paired.parquet`)

Main dataset: 29,379 direct-dependency instances, one row per (project, reference date, dependency) for the 238 projects that have a usable root `package.json` at all four reference dates. The same columns are used in `all_available.csv` (all projects available at each date) and `instance_audit.csv` (all candidate instances, including excluded ones).

| Column | Type | Description |
|---|---|---|
| `project` | string | GitHub repository, `owner/name` |
| `stratum` | string | Popularity stratum by GitHub stars at sampling: `high` (≥ 50,000), `medium` (10,000–49,999), `low` (1,000–9,999), `niche` (< 1,000) |
| `origin` | date | Reference date *o* of the snapshot: `2020-12-31`, `2021-12-31`, `2022-12-31` or `2023-12-31` |
| `window_end` | date | End of the 12-month label window, *o* + 12 months |
| `package` | string | npm package name of the direct dependency |
| `constraint` | string | Version constraint declared in the root `package.json` at *o* (for example `^4.17.0`) |
| `dependency_type` | string | `production` (`dependencies`) or `development` (`devDependencies`) |
| `commit_sha` | string | Commit of the project's default branch whose `package.json` was read (last commit on or before *o*) |
| `status` | string | Version-inference status. `ok` for every row of this file. In `instance_audit.csv` also `unsupported_constraint` (aliases, URLs, Git, file or workspace references, `*`, `latest`, `next`, empty) and `no_matching_version_at_origin` (no stable version published by *o* satisfies the constraint) |
| `used_version` | string | Inferred used version: the highest stable (non-prerelease) version published by *o* that satisfies `constraint` (npm `semver.maxSatisfying`) |
| `used_version_date` | datetime | Publication time of `used_version` in the npm Registry |
| `latest_version` | string | Most recently published stable version by *o* (by publication time) |
| `latest_version_date` | datetime | Publication time of `latest_version` |
| `libyear` | float, years | (`latest_version_date` − `used_version_date`) in whole days / 365 |
| `major_versions_behind` | integer | Number of later stable releases (published after `used_version`, by *o*) that raise the major number, following the path of increasing versions; back-port releases are not counted |
| `minor_versions_behind` | integer | Same, for releases that raise the minor number within the same major |
| `patch_versions_behind` | integer | Same, for releases that raise the patch number within the same minor |
| `release_frequency` | float, versions per month | `total_versions` / `package_age` (0 if `package_age` is 0) |
| `package_age` | float, months | Whole days from the first stable release to *o*, divided by 30 |
| `total_versions` | integer | Number of stable versions published by *o* |
| `days_since_latest_release` | integer, days | Whole days from `latest_version_date` to *o* |
| `is_post_1_0` | 0/1 | 1 if the major number of `used_version` is ≥ 1 |
| `label` | 0/1 | 1 if at least one reviewed, non-withdrawn GHSA advisory for `package` was published in (*o*, `window_end`] and its vulnerable version range contains `used_version` (npm `semver.satisfies`). 0 means no such advisory was found, not that the version is free of vulnerabilities |
| `matched_ghsa_ids` | string | GHSA IDs that made the label positive, separated by `;` (empty when `label` = 0) |
| `matched_advisories_updated_after_origin` | integer | How many of the matched advisories have a last-updated time after *o* (current metadata may differ from what was known at *o*) |

The nine model features are `libyear`, `major_versions_behind`, `minor_versions_behind`, `patch_versions_behind`, `release_frequency`, `package_age`, `total_versions`, `days_since_latest_release` and `is_post_1_0`.

Variants used in the sensitivity analyses (`robustness/data/*.csv`, `publication/experiments/lockfile_sensitivity/*.csv`) have the same columns; the file names give the variant (window length in months, cohort `paired`/`all`, latest-version rule `date`/`semver`, clamped or signed lag, exact versions only, lockfile-recorded or inferred versions).

## `publication/experiments/rq_completion/<origin>/predictions_wide.csv`

Scores for the test set of one origin (7,299–7,373 rows). Training uses all earlier snapshots whose label window had closed by the test origin.

| Column | Description |
|---|---|
| `origin`, `project`, `package`, `dependency_type`, `used_version`, `label` | As in `paired.csv` |
| `full_lr`, `full_rf`, `full_xgb` | Predicted probability from Logistic Regression, Random Forest and XGBoost trained on all nine features |
| `libyear_only_lr`, `libyear_only_rf`, `libyear_only_xgb` | Same algorithm trained on `libyear` only |
| `drop_<feature>_<algorithm>` | Same algorithm trained on the nine features without `<feature>` (drop-column importance; `drop_libyear_*` gives the incremental value of libyear) |
| `libyear_gt_0.25`, `libyear_gt_0.5`, `libyear_gt_1.0` | Rule baselines: 1 if `libyear` exceeds 0.25, 0.5 or 1 year |
| `libyear_score` | Raw `libyear` used as a ranking score |
| `constant_training_rate` | Positive rate of the training set (no-skill reference) |

## Result files

- `publication/experiments/rq_completion/metrics.json`: one record per origin and scorer (`model`) with `ap` (average precision), `roc_auc`, `brier`, the 10% review budget (`top_k` rows, `top_k_hits`, `precision_at_budget`, `recall_at_budget`), confusion counts and `precision`/`recall`/`f1` at threshold 0.5, and set sizes (`train_n`, `test_n`, `positive`, `prevalence`).
- `intervals.json`: paired AP differences `ap_difference` = AP(`model_a`) − AP(`model_b`) with 95% percentile intervals (`ci_low`, `ci_high`) from 1,000 bootstrap resamples of package or project clusters (`cluster_unit`), seed 42.
- `importance.json` (drop-column ΔAP and rank) and `native.json` (standardised LR coefficients, RF impurity and XGB importances).
- JSON outputs under `verification/` store unrounded values; each folder's README describes its fields.
