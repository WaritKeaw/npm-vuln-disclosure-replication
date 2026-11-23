# Field-level availability and measurement audit

16 October 2026. The availability of a historical event date is not proof that its current record contents were known then. [All-match audit](../experiments/four_step/availability.json) and [training sensitivity results](../supplement/four_step_results.md).

| Field | Event/cutoff rule | Record-vintage evidence | Verified claim / remaining limit |
| --- | --- | --- | --- |
| Git manifest/commit | first-parent commit selected by origin | same frozen commit IDs | content reproducible in cache; historical default-branch/public reachability unverified |
| npm release timestamps | stable releases with time ≤ origin | current frozen registry time map | event-time filter reproducible; timestamp edit/deletion history unverified |
| Inferred reference | highest satisfying stable SemVer at origin | frozen constraint and registry values | not installed resolution; sensitivity checked against same-commit root lockfiles |
| Libyear/transition counts/age | computed from eligible releases | fixed construction source and table hashes | deterministic reconstruction, not an assertion that all metadata was available historically |
| GHSA publication | publication in (origin, window_end] | current cache collected 2026-10-14 | observable database publication; not onset/discovery/first disclosure |
| Reviewed eligibility | any matching record reviewed by fit cutoff proxy | current github_reviewed_at for all matches | 16/10 training-positive rows have no reviewed match by cutoff; current ranges still used |
| Affected ranges/withdrawal | current reviewed/nonwithdrawn records | no complete archived record revisions | historical applicability and negative labels not fully reconstructed |
| Paired membership | eligible instances at all four origins | 250 inherited; 238 retained | retrospective survivor selection, not historical enrollment |
| Lockfile label differences | same commit, recorded versus inferred reference | 32 traces; 64 arm checks | current range-matching consistency; not independent vulnerability validation |
| Label maturity | window_end+30/90d≤fit cutoff | frozen 12-month windows | first test unestimable; later settings share identical older training sets |

No unavailable/uncertain positive was relabeled negative. The review-proxy exclusion is a sensitivity on a selected training subset. The 2021–2024 advisory cache cannot establish absence of pre-2021 advisories, so no first-disclosure/no-prior-known cohort is claimed. No new network collection was performed.
