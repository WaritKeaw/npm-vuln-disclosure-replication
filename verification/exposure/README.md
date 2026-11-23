# Exposure covariates check (reviewer finding F-2), exploratory

Status: **exploratory, post hoc**, run 2026-10-24. Single cohort (paired 238 projects); the three test origins from the main analysis are reused; no multiplicity correction; no tuning. Nothing here changes `thesis.md` or the main results.

Question: the outcome (a GHSA advisory disclosed within 12 months after the snapshot) may reflect scrutiny or exposure rather than package properties. After adding point-in-time exposure covariates, (a) do the models still beat the comparators, and (b) do libyear and the lag family still add nothing?

## Files

| File | Content |
|---|---|
| `fetch_exposure.py` | Network stage (run once): npm daily downloads and pre-2021 GHSA advisories; raw responses cached in `cache/` (~236 MB) |
| `exposure_analysis.py` | Offline analysis from the cache; writes `exposure_results.json` (all numbers, unrounded) and `downloads_by_origin_package.csv` |
| `fetch.log`, `analysis.log` | Run logs |

Rerun with the bundled Python 3.12 and the same library versions as rq_completion (numpy 2.5.4, pandas 3.0.1, sklearn 1.9.1, xgboost 3.0.5 vendored):

```
$py = '<runtime>\python\python.exe'
python verification\exposure\fetch_exposure.py all     # only if cache/ is missing; reads parquet, so use system Python 3.13 (pyarrow)
& $py verification\exposure\exposure_analysis.py       # offline
```

## Method

- **Data and protocol** come from `publication/experiments/rq_completion/executed_source.py`:
  - Input is `robustness/data/date_12_paired.csv`, the file rq_completion actually reads. It has the same rows and labels as `data/processed/paired.parquet`; feature values differ only by float round-off (at most 1.4e-14).
  - Training uses origins before the test origin with `window_end <= test origin`.
  - The pipeline is `SimpleImputer(median) → StandardScaler → model`, with LR / RF / XGB on the frozen parameters and seed 42.
  - Recall at the 10 % budget uses `ceil(0.1 n)` rows in stable order, as in the source.
  - Intervals come from a package-cluster paired bootstrap: 1,000 resamples, seed 42, the same RNG sequence as the source `intervals()`. ΔAUC is added on the same resamples.
- **`log_downloads_365d`** is log1p of npm downloads over the 365 days ending at the origin, inclusive (e.g. 2021-01-01..2021-12-31), from `https://api.npmjs.org/downloads/range/...`. Daily series were fetched instead of point totals so that gaps in the API data can be seen.
  - Verified API behaviour:
    - Bulk (comma-separated) queries work for unscoped names, up to 128 per request, and are limited to 365 days (`exceeded max days of 365 for bulk query`). Scoped packages need one request each.
    - A single-package request longer than about 18 months is silently clipped: a 2020-01-01..2021-12-31 request returned start 2020-06-30. So one 365-day request per origin was used.
    - The fetch took 2,331 requests. The API throttled scoped requests (HTTP 429), handled with retry and backoff.
    - Python had to be forced to IPv4 on this machine, because IPv6 connections to api.npmjs.org hang.
  - **Gaps in the API's download history (a data-quality issue).** For some packages that certainly had downloads, the API returns long runs of zero days. For example, `express` shows 0 downloads every day before about 2021-10, including all of 2018–2020; `rx` and `rss` behave the same way. The handling rule was fixed before any model was fitted:
    - Only days after the package's first npm publication count (earliest timestamp in `cache/npm`).
    - On those days, a run of 14 or more consecutive zero days counts as a gap.
    - Downloads are annualised from the observed days (`sum × 365 / observed_days`).
    - With fewer than 30 observed days, the value is **missing**. Missing values go through the pipeline's train-median imputer. No missing indicator is added, so the exposure block stays at 2 covariates.
    - Sensitivity model `full_exp_rawdl` uses the uncorrected raw sum, with not-found set to 0. Its results are almost identical (see the JSON).
- **`prior_advisories`** is the number of non-withdrawn, reviewed npm GHSA advisories that name the package (any version) with `published_at <= origin 23:59:59.999Z`. This is the same boundary the label uses in `semver_batch.cjs`.
  - The project cache `cache/ghsa/advisories.json` covers only advisories published 2021-01-01..2024-12-31. On its own, that would make the count 0 for every 2020 row and undercount later origins. So reviewed npm advisories published up to 2020-12-31 were fetched from the same GitHub endpoint into `cache/ghsa_pre2021/`: 1,653 advisories dated 2017-10-24..2020-12-30, with no overlap with the existing cache. In total there are 3,756 advisories; 110 withdrawn ones are excluded.
  - **Point-in-time caveat:** reviewed/withdrawn status and the affected-package lists are as of the current caches (fetched 2026-10-14 and 2026-10-24), not as they were at each origin. `published_at` is the GHSA publication date. Advisories imported into GHSA from older npm databases carry their GHSA publication date.
- **Dependents count: not used.** npm and GitHub do not provide historical (point-in-time) dependents counts, and current counts would leak future information.
- **Models**, per test origin × algorithm:
  - full9 (reproduction check)
  - full9 + exposure (`full_exp`)
  - full_exp − libyear
  - full_exp − lag family (libyear + 3 versions_behind)
  - exposure only
  - Extras: full9 + each exposure covariate alone, and the raw-downloads sensitivity.
- **Rules** (no training): rank by prior_advisories; rank by log_downloads (missing ranked last); libyear score; libyear > 0.25 / 0.5 / 1.0. Rule scores have many ties, so recall@10 % is also reported as the expected value under random tie-breaking (`recall_at_10pct_expected_ties`).

## Downloads coverage (packages present at each origin)

| Origin | Packages | Not found in API | Packages with gap days | Missing after gap rule (packages / instances) | Positives with missing downloads |
|---|---|---|---|---|---|
| 2020-12-31 | 2,834 | 1 (`vrtest-mui`) | 15 | 8 / 32 | 0 |
| 2021-12-31 | 2,910 | 0 | 9 | 5 / 6 | 0 |
| 2022-12-31 | 2,848 | 0 | 8 | 1 / 2 | 0 |
| 2023-12-31 | 2,864 | 0 | 5 | 1 / 1 | 0 |

## Reproduction check

For all three test origins, AP, ROC-AUC, recall@10 % and Brier of `full_lr/full_rf/full_xgb` match `rq_completion/metrics.json` exactly (maximum absolute difference 0.0); `drop_libyear_*` matches too. The package-cluster CIs for full − drop_libyear match `rq_completion/intervals.json` to within 1e-10, so the bootstrap resamples are the same as in the thesis.

## Results

AP / ROC-AUC / recall@10 % / Brier per test origin. Prevalence is 3.63 % / 1.91 % / 2.89 % (268 / 140 / 211 positives).

| Model | 2021 AP / AUC / R@10 / Brier | 2022 | 2023 |
|---|---|---|---|
| LR full9 (thesis model) | 0.116 / 0.758 / 0.28 / 0.0341 | 0.088 / 0.803 / 0.43 / 0.0205 | 0.115 / 0.741 / 0.36 / 0.0281 |
| LR full9 + exposure | 0.225 / 0.801 / 0.42 / 0.0342 | 0.172 / 0.845 / 0.54 / 0.0246 | 0.113 / 0.781 / 0.46 / 0.0308 |
| LR full9 + exp − libyear | 0.228 / 0.809 / 0.43 / 0.0344 | 0.177 / 0.848 / 0.56 / 0.0234 | 0.113 / 0.790 / 0.46 / 0.0307 |
| LR full9 + exp − lag family | 0.234 / 0.815 / 0.45 / 0.0341 | 0.173 / 0.851 / 0.56 / 0.0237 | 0.127 / 0.840 / 0.45 / 0.0303 |
| LR exposure only | 0.237 / 0.794 / 0.46 / 0.0350 | 0.195 / 0.862 / 0.65 / 0.0236 | 0.095 / 0.795 / 0.44 / 0.0315 |
| LR full9 + prior_advisories | 0.222 / 0.793 / 0.43 / 0.0338 | 0.159 / 0.838 / 0.54 / 0.0249 | 0.110 / 0.764 / 0.46 / 0.0308 |
| LR full9 + log_downloads | 0.109 / 0.759 / 0.27 / 0.0342 | 0.115 / 0.812 / 0.43 / 0.0201 | 0.122 / 0.755 / 0.34 / 0.0281 |
| RF full9 (thesis model) | 0.068 / 0.669 / 0.19 / 0.0365 | 0.049 / 0.787 / 0.15 / 0.0198 | 0.284 / 0.850 / 0.54 / 0.0245 |
| RF full9 + exposure | 0.160 / 0.739 / 0.26 / 0.0338 | 0.114 / 0.848 / 0.38 / 0.0201 | 0.151 / 0.864 / 0.65 / 0.0292 |
| RF full9 + exp − libyear | 0.159 / 0.733 / 0.29 / 0.0339 | 0.110 / 0.856 / 0.45 / 0.0205 | 0.130 / 0.853 / 0.58 / 0.0303 |
| RF full9 + exp − lag family | 0.155 / 0.724 / 0.25 / 0.0339 | 0.134 / 0.860 / 0.29 / 0.0200 | 0.136 / 0.854 / 0.53 / 0.0304 |
| RF exposure only | 0.185 / 0.720 / 0.48 / 0.0352 | 0.113 / 0.863 / 0.30 / 0.0230 | 0.092 / 0.657 / 0.45 / 0.0356 |
| RF full9 + prior_advisories | 0.172 / 0.713 / 0.25 / 0.0334 | 0.092 / 0.812 / 0.26 / 0.0209 | 0.218 / 0.868 / 0.66 / 0.0259 |
| RF full9 + log_downloads | 0.110 / 0.708 / 0.18 / 0.0351 | 0.084 / 0.836 / 0.39 / 0.0193 | 0.152 / 0.832 / 0.51 / 0.0290 |
| XGB full9 (thesis model) | 0.064 / 0.652 / 0.10 / 0.0374 | 0.050 / 0.778 / 0.31 / 0.0227 | 0.113 / 0.787 / 0.36 / 0.0277 |
| XGB full9 + exposure | 0.208 / 0.712 / 0.38 / 0.0322 | 0.101 / 0.767 / 0.27 / 0.0246 | 0.109 / 0.819 / 0.28 / 0.0320 |
| XGB full9 + exp − libyear | 0.197 / 0.694 / 0.28 / 0.0326 | 0.092 / 0.773 / 0.26 / 0.0242 | 0.114 / 0.805 / 0.29 / 0.0315 |
| XGB full9 + exp − lag family | 0.192 / 0.692 / 0.36 / 0.0328 | 0.101 / 0.770 / 0.26 / 0.0240 | 0.086 / 0.800 / 0.29 / 0.0327 |
| XGB exposure only | 0.184 / 0.725 / 0.43 / 0.0344 | 0.128 / 0.771 / 0.28 / 0.0220 | 0.110 / 0.654 / 0.45 / 0.0343 |
| XGB full9 + prior_advisories | 0.141 / 0.719 / 0.29 / 0.0345 | 0.069 / 0.790 / 0.32 / 0.0255 | 0.144 / 0.832 / 0.45 / 0.0275 |
| XGB full9 + log_downloads | 0.092 / 0.656 / 0.23 / 0.0352 | 0.046 / 0.753 / 0.26 / 0.0236 | 0.093 / 0.803 / 0.36 / 0.0326 |
| Rule: rank by prior_advisories | 0.225 / 0.765 / 0.60 (exp. ties 0.61) / – | 0.156 / 0.818 / 0.61 (exp. ties 0.63) / – | 0.070 / 0.682 / 0.38 (exp. ties 0.35) / – |
| Rule: rank by log_downloads | 0.056 / 0.631 / 0.22 (exp. ties 0.22) / – | 0.241 / 0.749 / 0.33 (exp. ties 0.33) / – | 0.056 / 0.728 / 0.12 (exp. ties 0.12) / – |
| Rule: libyear score | 0.056 / 0.579 / 0.16 (exp. ties 0.16) / – | 0.019 / 0.503 / 0.04 (exp. ties 0.04) / – | 0.032 / 0.528 / 0.12 (exp. ties 0.12) / – |
| Rule: libyear > 0.5 | 0.042 / 0.563 / 0.11 (exp. ties 0.14) / – | 0.019 / 0.493 / 0.07 (exp. ties 0.10) / – | 0.030 / 0.518 / 0.11 (exp. ties 0.11) / – |

Package-cluster bootstrap (1,000 paired resamples, seed 42). `*` = 95 % CI excludes 0.

| Contrast: ΔAP [95% CI]; ΔAUC [95% CI] | 2021 | 2022 | 2023 |
|---|---|---|---|
| LR (full+exp) − full9 | +0.109 [-0.013, +0.242]; +0.043 [-0.013, +0.106] | +0.084 [-0.058, +0.290]; +0.041 [-0.013, +0.098] | -0.002 [-0.060, +0.048]; +0.040 [+0.009, +0.089]* |
| RF (full+exp) − full9 | +0.092 [-0.002, +0.226]; +0.070 [+0.033, +0.111]* | +0.065 [+0.008, +0.253]*; +0.060 [+0.018, +0.104]* | -0.133 [-0.323, +0.037]; +0.014 [-0.038, +0.091] |
| XGB (full+exp) − full9 | +0.144 [+0.042, +0.256]*; +0.060 [+0.019, +0.106]* | +0.051 [-0.035, +0.229]; -0.011 [-0.112, +0.115] | -0.004 [-0.127, +0.095]; +0.033 [-0.068, +0.162] |
| LR (full+exp) − (full+exp − libyear) | -0.003 [-0.031, +0.033]; -0.008 [-0.019, +0.004] | -0.005 [-0.023, +0.007]; -0.003 [-0.019, +0.008] | +0.000 [-0.003, +0.005]; -0.009 [-0.021, +0.002] |
| RF (full+exp) − (full+exp − libyear) | +0.001 [-0.019, +0.029]; +0.006 [-0.015, +0.024] | +0.004 [-0.020, +0.027]; -0.009 [-0.030, +0.013] | +0.021 [-0.003, +0.064]; +0.011 [-0.006, +0.026] |
| XGB (full+exp) − (full+exp − libyear) | +0.011 [-0.040, +0.064]; +0.017 [-0.007, +0.038] | +0.009 [-0.032, +0.041]; -0.005 [-0.061, +0.027] | -0.005 [-0.034, +0.008]; +0.014 [-0.016, +0.046] |
| LR (full+exp) − (full+exp − lag family) | -0.009 [-0.040, +0.031]; -0.014 [-0.033, +0.005] | -0.001 [-0.035, +0.018]; -0.006 [-0.065, +0.030] | -0.014 [-0.080, +0.054]; -0.059 [-0.153, +0.018] |
| RF (full+exp) − (full+exp − lag family) | +0.006 [-0.029, +0.059]; +0.015 [-0.006, +0.034] | -0.021 [-0.072, +0.003]; -0.012 [-0.032, +0.004] | +0.014 [-0.007, +0.059]; +0.009 [-0.004, +0.021] |
| XGB (full+exp) − (full+exp − lag family) | +0.016 [-0.065, +0.097]; +0.019 [-0.015, +0.050] | -0.000 [-0.060, +0.018]; -0.002 [-0.014, +0.010] | +0.024 [-0.003, +0.096]; +0.019 [-0.000, +0.036] |
| LR (full+exp) − exposure only | -0.013 [-0.108, +0.061]; +0.007 [-0.076, +0.079] | -0.023 [-0.098, +0.016]; -0.017 [-0.077, +0.035] | +0.018 [-0.024, +0.089]; -0.014 [-0.061, +0.034] |
| RF (full+exp) − exposure only | -0.025 [-0.086, +0.022]; +0.019 [-0.059, +0.106] | +0.001 [-0.044, +0.054]; -0.016 [-0.060, +0.031] | +0.058 [-0.028, +0.177]; +0.206 [+0.005, +0.441]* |
| XGB (full+exp) − exposure only | +0.023 [-0.078, +0.090]; -0.013 [-0.099, +0.068] | -0.027 [-0.137, +0.065]; -0.004 [-0.065, +0.057] | -0.001 [-0.147, +0.094]; +0.166 [-0.003, +0.340] |
| LR (full+exp) − prior-advisory rule | +0.000 [-0.062, +0.054]; +0.036 [-0.052, +0.123] | +0.015 [-0.033, +0.073]; +0.027 [-0.102, +0.153] | +0.043 [-0.007, +0.129]; +0.099 [+0.017, +0.158]* |
| RF (full+exp) − prior-advisory rule | -0.064 [-0.143, +0.021]; -0.026 [-0.102, +0.057] | -0.043 [-0.122, +0.058]; +0.030 [-0.067, +0.170] | +0.081 [-0.006, +0.203]; +0.182 [+0.058, +0.312]* |
| XGB (full+exp) − prior-advisory rule | -0.017 [-0.128, +0.093]; -0.054 [-0.134, +0.029] | -0.056 [-0.154, +0.058]; -0.051 [-0.184, +0.111] | +0.040 [-0.021, +0.139]; +0.137 [+0.036, +0.228]* |
| LR (full+exp) − libyear score | +0.168 [+0.058, +0.315]*; +0.222 [+0.149, +0.295]* | +0.153 [+0.032, +0.343]*; +0.342 [+0.196, +0.423]* | +0.081 [+0.026, +0.224]*; +0.253 [+0.081, +0.445]* |
| RF (full+exp) − libyear score | +0.104 [+0.022, +0.249]*; +0.160 [+0.075, +0.238]* | +0.095 [+0.027, +0.305]*; +0.344 [+0.253, +0.416]* | +0.119 [+0.042, +0.261]*; +0.335 [+0.218, +0.459]* |
| XGB (full+exp) − libyear score | +0.151 [+0.053, +0.265]*; +0.132 [+0.026, +0.234]* | +0.082 [+0.014, +0.251]*; +0.264 [+0.165, +0.365]* | +0.078 [+0.028, +0.206]*; +0.291 [+0.153, +0.449]* |
| LR full9 − prior-advisory rule | -0.109 [-0.260, +0.038]; -0.007 [-0.134, +0.121] | -0.068 [-0.278, +0.091]; -0.014 [-0.162, +0.138] | +0.045 [-0.037, +0.145]; +0.059 [-0.056, +0.136] |
| RF full9 − prior-advisory rule | -0.156 [-0.300, -0.015]*; -0.096 [-0.190, +0.001] | -0.108 [-0.290, -0.005]*; -0.030 [-0.119, +0.089] | +0.214 [-0.025, +0.485]; +0.168 [-0.017, +0.316] |
| XGB full9 − prior-advisory rule | -0.161 [-0.307, -0.035]*; -0.113 [-0.209, -0.020]* | -0.106 [-0.311, +0.005]; -0.040 [-0.178, +0.105] | +0.043 [-0.061, +0.196]; +0.105 [-0.116, +0.283] |
| LR full9 − downloads rule | +0.060 [-0.012, +0.170]; +0.127 [-0.034, +0.265] | -0.153 [-0.391, +0.081]; +0.054 [-0.033, +0.198] | +0.058 [-0.005, +0.178]; +0.014 [-0.075, +0.125] |
| RF full9 − downloads rule | +0.013 [-0.040, +0.117]; +0.038 [-0.112, +0.177] | -0.192 [-0.484, +0.033]; +0.038 [-0.063, +0.228] | +0.227 [+0.011, +0.474]*; +0.122 [+0.014, +0.207]* |
| XGB full9 − downloads rule | +0.008 [-0.041, +0.076]; +0.021 [-0.137, +0.162] | -0.191 [-0.460, +0.013]; +0.029 [-0.085, +0.203] | +0.057 [-0.016, +0.186]; +0.059 [-0.076, +0.170] |

**Correlations** (Spearman on test instances; package level in the JSON). Values are for 2021 / 2022 / 2023.

| log_downloads_365d vs | ρ |
|---|---|
| package_age | 0.26 / 0.23 / 0.22 |
| days_since_latest_release | −0.39 / −0.44 / −0.44 |
| total_versions | 0.49 / 0.49 / 0.52 |
| prior_advisories | 0.22 / 0.22 / 0.24 |

**Where positives sit** (2021 / 2022 / 2023):

| Group | Prevalence in group | Prevalence in the rest | Share of all positives |
|---|---|---|---|
| Top download decile of test rows | 8.1 % / 6.1 % / 3.6 % | 3.1 % / 1.4 % / 2.8 % | 22 % / 33 % / 12 % |
| Rows whose package already had a prior advisory | 22.4 % / 12.3 % / 11.3 % | 1.6 % / 0.6 % / 1.7 % | 60 % / 74 % / 48 % |

## Interpretation

Exploratory: single cohort, test origins reused, no multiplicity correction.

- **"Libyear adds ~nothing" still holds, and so does the same claim for the lag family.** With exposure in the model:
  - Removing libyear changes AP by −0.005 to +0.021.
  - Removing all four lag features changes AP by −0.021 to +0.024.
  - For both contrasts, all 9 ΔAP CIs and all 9 ΔAUC CIs include 0.
  - The libyear rules stay near chance (AUC 0.49–0.58).
- **"Models > libyear rules" still holds.** full9 + exposure beats the libyear score in all 9 cases (ΔAP and ΔAUC CIs exclude 0).
- **The reviewer's concern is partly confirmed: package history is a strong, cheap comparator.**
  - The rule "rank by number of prior advisories" (no model) has AP 0.225 / 0.156 / 0.070 and recall@10 % 0.60 / 0.61 / 0.38.
  - In 2021 and 2022 its AP is above every thesis model (full9). The CI excludes 0 for RF and XGB in 2021 and for RF in 2022.
  - Only in 2023 are the full9 models ahead (RF AP 0.284 vs 0.070, but the CI includes 0).
  - So "the model beats simple comparators" holds against libyear rules, but **not** against a package-history rule in 2 of 3 origins.
- **Adding exposure helps in 2021/2022, not in 2023.**
  - LR AP rises 0.116→0.225 (2021) and 0.088→0.172 (2022).
  - Most of the gain comes from prior_advisories: for LR, full9 + prior_advisories alone ≈ full9 + exposure. Downloads alone add little except in 2022.
  - In 2023 the gain disappears (LR 0.115→0.113). RF AP falls 0.284→0.151 (CI −0.323 to +0.037), although its AUC rises slightly.
  - ΔAP CIs exclude 0 in only 2 of 9 cases (XGB 2021, RF 2022).
- **Once exposure is in the model, the nine snapshot features add no clear AP.**
  - full9 + exposure vs exposure only: all 9 ΔAP CIs include 0.
  - In AUC the features add something only in 2023: RF +0.206 (CI excludes 0) and XGB +0.166 (CI −0.003 to +0.340, just includes 0). Against the prior-advisory rule, the 2023 ΔAUC CIs exclude 0 for all three algorithms.
- **Downloads are only moderately related to the snapshot features** (|ρ| ≤ 0.52, strongest with total_versions and recency), so package_age and the other package features are not just download proxies. Popular packages still hold a disproportionate share of positives (a third in 2022). This fits the thesis finding that a few popular packages, repeated across projects, drive the 2022 results.
- **Implication for wording (a suggestion; not applied to the thesis):**
  - The thesis can keep "libyear/lag adds little" and "models > libyear rules".
  - It should not claim that the model's signal is separate from package identity or exposure. A package-history comparator (prior advisories) matches or beats the nine-feature models in AP in 2 of 3 origins.
  - The 2023 RF result is the only case where the features clearly add ranking value (AUC) beyond history and exposure.
- **Limits:**
  - Downloads include CI, bot and mirror traffic, and the API has history gaps. The gaps were handled by a fixed rule, and the raw-sum sensitivity gives the same picture.
  - prior_advisories uses the current GHSA review/withdrawal status.
  - Positives are few (140–268 per origin) and concentrated in a few packages, so the CIs are wide.
  - This is a robustness check against the reviewer's alternative explanation, not a new confirmatory model.
