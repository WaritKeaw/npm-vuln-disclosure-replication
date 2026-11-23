# Top-K ranking: models vs. the prior-advisory rule (ISWA plan, advisor item 5)

Status: **exploratory, post hoc**, run 2026-11-04. No model fitted, nothing in `thesis.md` changed. Purpose: the Top-K (Precision@K / Recall@K) comparison planned for the ISWA manuscript (Fig. 4), using existing outputs only.

## Files

| File | Content |
|---|---|
| `topk_prior_advisory.py` | Computes the prior-advisory rule at K = 1/5/10/20 % and the model − rule intervals |
| `topk_results.json` | All numbers, unrounded: `rule_points` (both views × 4 budgets × 3 origins), `intervals_model_minus_rule`, `rule_profile`, `reproduction` |

Rerun (bundled Python 3.12, offline, ~35 s):

```
$py = '<runtime>\python\python.exe'
& $py verification\topk\topk_prior_advisory.py
```

## Method

- **Model and libyear points** are the existing `publication/experiments/four_step/budget_points.json` (unchanged). The script recomputes 144 of them (full LR/RF/XGB, libyear score, libyear > 1 y, libyear-only LR; both views; 4 budgets; 3 origins) with the copied `stats()` function: maximum absolute difference **0.0**. So the rule is evaluated on exactly the same rows, budgets and tie policy.
- **Rule score:** number of non-withdrawn, reviewed npm GHSA advisories naming the package with `published_at <= origin` (definition and caches from `verification/exposure/`). Same point-in-time caveat as there (current review/withdrawal status).
- **K:** `ceil(n × budget)` rows, budgets 1/5/10/20 % (four_step protocol). **Ties:** uniform selection within the cutoff tie, evaluated analytically (four_step tie policy). This matters for the rule: only 723 / 848 / 902 of ~7,300 test rows have a prior advisory, so at K ≥ 10 % (2021) or K = 20 % (all origins) the cutoff falls in the large zero-count block and the remainder is filled at random.
- **Views:** instance (primary) and unique package–version per origin (each pair counted once).
- **Intervals:** package-cluster paired bootstrap, 1,000 resamples, seed 42 (four_step unit and seed), now at all four budgets. 72 intervals per view, no multiplicity correction.
- **Reproduction:** rule AP 0.225 / 0.156 / 0.070 and recall@10 % 0.605 / 0.627 / 0.353 equal the expected-ties values in `verification/exposure/README.md` (0.61 / 0.63 / 0.35).

## Results (instance view)

Precision / Recall at K. Positives 268 / 140 / 211; prevalence 3.63 % / 1.91 % / 2.89 %. Bold = highest recall at that K.

| Origin | K | LR | RF | XGB | libyear score | Prior-advisory rule |
|---|---|---|---|---|---|---|
| 2021 | 1 % | 0.243 / 0.067 | 0.189 / 0.052 | 0.054 / 0.015 | 0.189 / 0.052 | 0.359 / **0.099** |
| 2021 | 5 % | 0.117 / 0.160 | 0.070 / 0.097 | 0.051 / 0.071 | 0.060 / 0.082 | 0.235 / **0.324** |
| 2021 | 10 % | 0.102 / 0.280 | 0.070 / 0.194 | 0.038 / 0.104 | 0.057 / 0.157 | 0.220 / **0.605** |
| 2021 | 20 % | 0.097 / 0.534 | 0.056 / 0.310 | 0.066 / 0.366 | 0.048 / 0.265 | 0.118 / **0.649** |
| 2022 | 1 % | 0.054 / 0.029 | 0.014 / 0.007 | 0.000 / 0.000 | 0.041 / 0.021 | 0.139 / **0.074** |
| 2022 | 5 % | 0.090 / 0.236 | 0.046 / 0.121 | 0.035 / 0.093 | 0.011 / 0.029 | 0.111 / **0.291** |
| 2022 | 10 % | 0.082 / 0.429 | 0.029 / 0.150 | 0.060 / 0.314 | 0.007 / 0.036 | 0.120 / **0.627** |
| 2022 | 20 % | 0.062 / 0.650 | 0.047 / 0.493 | 0.054 / 0.564 | 0.016 / 0.171 | 0.073 / **0.767** |
| 2023 | 1 % | 0.288 / 0.100 | 0.575 / **0.199** | 0.123 / 0.043 | 0.041 / 0.014 | 0.054 / 0.019 |
| 2023 | 5 % | 0.164 / 0.284 | 0.263 / **0.455** | 0.148 / 0.256 | 0.047 / 0.081 | 0.100 / 0.172 |
| 2023 | 10 % | 0.103 / 0.355 | 0.155 / **0.536** | 0.105 / 0.365 | 0.034 / 0.118 | 0.102 / 0.353 |
| 2023 | 20 % | 0.072 / 0.498 | 0.095 / **0.654** | 0.082 / 0.569 | 0.034 / 0.237 | 0.076 / 0.528 |

ΔRecall@K, model − rule, package-cluster 95 % CI (instance view). `*` = CI excludes 0.

| Origin | K | LR | RF | XGB |
|---|---|---|---|---|
| 2021 | 1 % | −0.032 [−0.189, +0.085] | −0.047 [−0.210, +0.061] | −0.084 [−0.210, +0.018] |
| 2021 | 5 % | −0.164 [−0.320, −0.006]* | −0.227 [−0.440, −0.054]* | −0.253 [−0.451, −0.085]* |
| 2021 | 10 % | −0.326 [−0.501, −0.096]* | −0.411 [−0.581, −0.202]* | −0.501 [−0.656, −0.288]* |
| 2021 | 20 % | −0.116 [−0.336, +0.134] | −0.340 [−0.518, −0.132]* | −0.284 [−0.536, −0.118]* |
| 2022 | 1 % | −0.045 [−0.246, +0.065] | −0.066 [−0.257, +0.022] | −0.074 [−0.267, +0.000] |
| 2022 | 5 % | −0.055 [−0.475, +0.408] | −0.170 [−0.408, +0.002] | −0.198 [−0.524, +0.154] |
| 2022 | 10 % | −0.199 [−0.648, +0.262] | −0.477 [−0.668, −0.197]* | −0.313 [−0.650, +0.040] |
| 2022 | 20 % | −0.117 [−0.524, +0.210] | −0.275 [−0.500, −0.056]* | −0.203 [−0.584, +0.190] |
| 2023 | 1 % | +0.081 [−0.070, +0.157] | +0.180 [−0.032, +0.291] | +0.024 [−0.094, +0.064] |
| 2023 | 5 % | +0.112 [−0.216, +0.345] | +0.283 [−0.182, +0.530] | +0.084 [−0.265, +0.330] |
| 2023 | 10 % | +0.002 [−0.267, +0.254] | +0.182 [−0.289, +0.504] | +0.012 [−0.393, +0.341] |
| 2023 | 20 % | −0.031 [−0.229, +0.146] | +0.126 [−0.251, +0.420] | +0.040 [−0.403, +0.387] |

Unique package–version view: same direction. In 2021–2022 the rule has the highest recall at every K except 2021 K = 20 % (LR 0.631 vs rule 0.587). 12 of 24 model − rule recall CIs exclude 0, all negative. 2023 is mixed, and no CI excludes 0. All numbers are in the JSON.

**Rule profile** (rows with ≥ 1 prior advisory / rows; positives among them / positives): 2021 723 / 7,373, 162 / 268 (60 %) · 2022 848 / 7,330, 104 / 140 (74 %) · 2023 902 / 7,299, 102 / 211 (48 %).

## Interpretation

- **Top-K confirms the AP finding at every budget.** In 2021 and 2022 the prior-advisory rule has the highest precision and recall at all four K; in 2021 the gap is clear (CI excludes 0 for all three models at K = 5 % and 10 %). In 2022 it is clear only for RF at K = 10 % and 20 %; LR and XGB lean the same way, with wide CIs.
- **2023 is the only origin where models lead**, mostly RF (recall@5 % 0.455 vs 0.172), but no model − rule CI excludes 0. This is the origin whose RF result depends on three packages (thesis 5.6.5: AP 0.284 → 0.044 without them).
- **The rule has a ceiling.** It can only rank the ~10–12 % of rows whose package already had an advisory; those rows hold 60 / 74 / 48 % of positives. Beyond that, the rule ranks at random, so its recall gain from K = 10 % to 20 % is small (2021 0.605 → 0.649). Positives in packages with no advisory history (40 / 26 / 52 %) are the part the rule cannot see.
- **Libyear score** has lower recall than LR and lower recall than the rule at every K and origin. At small K it is not always below RF / XGB (for example 2022 K = 1 %, where all are near 0).
- For the manuscript: report as "a simple advisory-history rule matched or beat the models at every review budget in two of three periods"; do not claim that models beat the history baseline. No new model is implied. A rule-then-model hybrid would be a new experiment and is not run here.
- Limits: as in `verification/exposure/` (current GHSA status, few clustered positives, wide CIs, no multiplicity correction; test origins reused).
