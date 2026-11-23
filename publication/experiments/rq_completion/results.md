# RQ completion results

> Corrected rebuild 2026-10-24: versions_behind counting fixed (semver_batch.cjs / semver_variants.cjs advance the reference only on a SemVer increase). Pre-fix outputs: `_archive/2026-10-24_cleanup/00_Final_Exam/snapshot_sensitivity/_pre_fix_backup_2026-10-24/` (project root). Recall at top 10% below uses stable order within ties (models have no ties; libyear rules: see four_step budget_points for tie-aware values).

| Test origin | Algorithm | Prevalence | AP | ROC AUC | Recall at top 10% |
| --- | --- | --- | --- | --- | --- |
| 2021-12-31 | LR | 3.63% | 0.11553 | 0.75781 | 27.99% |
| 2021-12-31 | RF | 3.63% | 0.06841 | 0.66892 | 19.40% |
| 2021-12-31 | XGB | 3.63% | 0.06386 | 0.65203 | 10.45% |
| 2022-12-31 | LR | 1.91% | 0.08793 | 0.80338 | 42.86% |
| 2022-12-31 | RF | 1.91% | 0.04880 | 0.78735 | 15.00% |
| 2022-12-31 | XGB | 1.91% | 0.05029 | 0.77823 | 31.43% |
| 2023-12-31 | LR | 2.89% | 0.11475 | 0.74103 | 35.55% |
| 2023-12-31 | RF | 2.89% | 0.28354 | 0.84975 | 53.55% |
| 2023-12-31 | XGB | 2.89% | 0.11333 | 0.78687 | 36.49% |

## Relative importance

| Test origin | Algorithm | Largest drop-column ΔAP | ΔAP | Libyear rank / 9 | Libyear ΔAP |
| --- | --- | --- | --- | --- | --- |
| 2021-12-31 | LR | package_age | 0.02299 | 4 | 0.01320 |
| 2021-12-31 | RF | libyear | 0.00211 | 1 | 0.00211 |
| 2021-12-31 | XGB | major_versions_behind | 0.00689 | 6 | 0.00006 |
| 2022-12-31 | LR | minor_versions_behind | 0.01850 | 3 | 0.00129 |
| 2022-12-31 | RF | package_age | 0.00055 | 5 | -0.00940 |
| 2022-12-31 | XGB | package_age | 0.01067 | 3 | 0.00542 |
| 2023-12-31 | LR | total_versions | 0.03243 | 3 | -0.00789 |
| 2023-12-31 | RF | package_age | 0.15735 | 5 | -0.00059 |
| 2023-12-31 | XGB | package_age | 0.05546 | 4 | 0.00388 |

| Test origin | Algorithm | ΔAP full − no Libyear | Package 95% interval | Project 95% interval |
| --- | --- | --- | --- | --- |
| 2021-12-31 | LR | 0.01320 | [-0.02203, 0.06385] | [-0.00006, 0.02911] |
| 2021-12-31 | RF | 0.00211 | [-0.02850, 0.04629] | [-0.00436, 0.01076] |
| 2021-12-31 | XGB | 0.00006 | [-0.01065, 0.02873] | [-0.00816, 0.00731] |
| 2022-12-31 | LR | 0.00129 | [-0.01825, 0.01423] | [-0.00527, 0.00697] |
| 2022-12-31 | RF | -0.00940 | [-0.02868, 0.00040] | [-0.01595, -0.00437] |
| 2022-12-31 | XGB | 0.00542 | [-0.00737, 0.03010] | [0.00184, 0.00961] |
| 2023-12-31 | LR | -0.00789 | [-0.07623, 0.00248] | [-0.01479, -0.00292] |
| 2023-12-31 | RF | -0.00059 | [-0.02598, 0.02131] | [-0.01109, 0.00844] |
| 2023-12-31 | XGB | 0.00388 | [-0.00744, 0.01381] | [-0.00055, 0.00836] |

## Threshold rules

| Test origin | Libyear rule | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| 2021-12-31 | 0.25 years | 0.04742 | 0.50000 | 0.08662 |
| 2021-12-31 | 0.5 years | 0.04921 | 0.46269 | 0.08895 |
| 2021-12-31 | 1.0 years | 0.05227 | 0.42164 | 0.09300 |
| 2022-12-31 | 0.25 years | 0.02080 | 0.45000 | 0.03976 |
| 2022-12-31 | 0.5 years | 0.01843 | 0.37143 | 0.03511 |
| 2022-12-31 | 1.0 years | 0.01863 | 0.32143 | 0.03521 |
| 2023-12-31 | 0.25 years | 0.03206 | 0.46919 | 0.06002 |
| 2023-12-31 | 0.5 years | 0.03142 | 0.43602 | 0.05862 |
| 2023-12-31 | 1.0 years | 0.03364 | 0.41706 | 0.06226 |

## Model operating points

| Test origin | Algorithm | Precision at 0.5 | Recall at 0.5 | F1 at 0.5 |
| --- | --- | --- | --- | --- |
| 2021-12-31 | LR | 0.00000 | 0.00000 | 0.00000 |
| 2021-12-31 | RF | 0.00000 | 0.00000 | 0.00000 |
| 2021-12-31 | XGB | 0.21053 | 0.01493 | 0.02787 |
| 2022-12-31 | LR | 0.25000 | 0.02143 | 0.03947 |
| 2022-12-31 | RF | 0.00000 | 0.00000 | 0.00000 |
| 2022-12-31 | XGB | 0.00000 | 0.00000 | 0.00000 |
| 2023-12-31 | LR | 0.37500 | 0.01422 | 0.02740 |
| 2023-12-31 | RF | 0.16667 | 0.00474 | 0.00922 |
| 2023-12-31 | XGB | 0.42857 | 0.01422 | 0.02752 |

All analyses are exploratory. LR/RF baseline AP replication error = 0.0. Independent artifact validation passed (validate_publication_completion.py, 2026-10-24).
