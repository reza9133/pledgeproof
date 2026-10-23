# Debug log

The loop was: audit, reproduce with a probe, fix, add a regression test, run
everything again, repeat until a full round (static audit, 700-history
reference-model fuzz, 12-mutant mutation run) found nothing new.

## Round 1 (found by audit + probes)

| # | Severity | Bug | Fix |
|---|---|---|---|
| 1 | High | A proof submitted shortly before the due date and judged "unclear" (or struck) *after* the due date could never be fixed, and anyone could call `declare_default` immediately and slash the bond. This contradicted "resubmit for free". A bystander could trigger it 1 h after submission. | New `cure_until` window: a review that pays nothing grants a fresh 3-day window, for the first 3 reviews of a milestone (`MAX_CURED_REVIEWS`). Cleared on payout. |
| 2 | Medium | The creator could `cancel_campaign` after the deadline or once the cap was reached, even with the goal met, and get the bond back untouched. | Cancel is allowed only while the window is open and the cap not reached. |
| 3 | Medium | Proof-URL validator accepted parser-differential hosts: `https://localhost\.example.com`, hex/octal numeric endings like `1.0x7f`, non-ASCII look-alikes, underscores, one-letter TLDs, port 0. | Strict ASCII-only host rules, alphabetic last label, no backslashes, valid ports only. |
| 4 | Medium | A quote made of tiny fragments joined by `...` (`the ... the ... the ... the`) counted as "verbatim on the page". | Every fragment of an elided quote must be at least 6 characters. |
| 5 | Low | Deeply nested JSON raised `RecursionError` (not a clean contract error) in plan and verdict parsing; a non-string milestone description (dict, list, int) was silently stringified. | Caught and reported cleanly; descriptions must be text; plan length capped at 10,000 characters. |
| 6 | Low | `required_bond(0)` raised a raw `ValueError`. | Clean `[EXPECTED]` error. |
| 7 | Medium | Bidirectional overrides / control characters in titles, pitches and milestone descriptions ("Trojan Source": what a person reads differs from what validators read). | Rejected at launch; stripped from page and model text. |
| 8 | Medium | Prompt policy: telling the model to answer `not_met` whenever the page contains instructions let a third party who can comment on a proof page force strikes on an honest creator. | The model is told to disregard such text, never let it push toward "met", and not to answer "not_met" merely because it is present. |

## Round 2 (found while hardening round 1)

| # | Severity | Bug | Fix |
|---|---|---|---|
| 9 | Medium | Validators compared only the *effect* of the leader's verdict. A modified leader could return a malformed result or a forged quote that would be stored and shown to backers. | Validators check the leader's shape (`verdict_is_wellformed`) and that an approval's quote is on their own copy of the page. |
| 10 | Low | A failure inside the model call itself was not mapped to `[LLM_ERROR]`. | `exec_prompt` is wrapped; validators never agree on it (the leader rotates). |
| 11 | Low | Timestamps with nanoseconds, typographic hyphens (U+2010..U+2015) in the proof token were not tolerated. | Parser and folding made tolerant. |

## Round 3 and later

Differential fuzz of the real contract against an independent reference model
(700 random histories), randomised solvency invariants, boundary tests to the
second, and a 12-mutant mutation run: no new bugs. One model mismatch turned out
to be a wrong assumption in the model (`backer_count` is not reduced by refund
claims), not a contract bug.

## Environment finding (not a contract bug)

GitHub's "latest" GenVM release can lack `genvm-universal.tar.xz`, which breaks
`gltest` direct mode with a 404. `scripts/codespaces_live.sh` pre-seeds the
cache with v0.2.16.

## Not verified here

The live Studionet run could not be executed from the build sandbox (no network
route to the RPC). The live script's scenario code, its receipt parsing and its
`genlayer-py` plumbing are covered offline (`tests/test_live_script_selfcheck.py`),
but the first real run is the first time it meets real validators and a real
model.
