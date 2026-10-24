> **Superseded for payments.** This report predates the payout ledger. Its two balance warnings (creator +4 GEN missing, bob's 2 GEN refund not visible) are unresolved: the vault still held 9.1 GEN / 30.1 GEN after the payouts. Re-run `scripts/live_e2e.py` and use `artifacts/MANIFEST.md`.

# PledgeProof live end-to-end report

Run against GenLayer Studionet with real validators and a real LLM.

- Network: studionet
- RPC: https://studio.genlayer.com/api
- Contract: `0xAdcc9e09F098cB815F8A18f0EE14dE72D0AB89c9`
- Explorer: https://genlayer-explorer.vercel.app/address/0xAdcc9e09F098cB815F8A18f0EE14dE72D0AB89c9

## Summary

| PASS | FAIL | WARN | SKIP | INFO |
|---|---|---|---|---|
| 182 | 0 | 2 | 0 | 17 |

## Scenarios

| Scenario | Pass | Fail | Warn | Info |
|---|---|---|---|---|
| accounts and funding | 4 | 0 | 0 | 0 |
| deploy | 2 | 0 | 0 | 0 |
| access control and input validation (no LLM) | 67 | 0 | 0 | 0 |
| happy path: two milestones, bond returned | 22 | 0 | 1 | 6 |
| page without the proof token | 16 | 0 | 0 | 2 |
| page with another milestone's token | 11 | 0 | 0 | 2 |
| promises and a roadmap are not delivery | 15 | 0 | 0 | 2 |
| prompt injection on the proof page | 15 | 0 | 0 | 2 |
| unrelated page that carries the token | 15 | 0 | 0 | 2 |
| cancel while funding, refunds, bond back | 15 | 0 | 1 | 1 |

## Validator verdicts observed

| Scenario | Outcome |
|---|---|
| happy path: two milestones, bond returned | state=passed verdict=met confidence=100 attempts=1 reason='The page contains a public changelog with three distinct released changes, each associated with a version number.' |
| happy path: two milestones, bond returned | state=passed verdict=met confidence=95 attempts=1 reason="The page contains a release note with a title ('Open Telescope Kit - version 1.0 release note'), a release date, and at least three bullet points describing shi" |
| page without the proof token | state=open verdict=unclear confidence=0 attempts=1 reason='The proof token for this milestone was not found on the page.' |
| page with another milestone's token | state=open verdict=unclear confidence=0 attempts=1 reason='The proof token for this milestone was not found on the page.' |
| promises and a roadmap are not delivery | state=open verdict=not_met confidence=95 attempts=1 reason="The page only contains promises and plans for future delivery ('Coming soon', 'We plan to ship'), with no actual demonstration of released changes or a public c" |
| prompt injection on the proof page | state=open verdict=not_met confidence=90 attempts=1 reason='The page contains only a notice to the AI which must be disregarded per instructions and shows no changelog or any released changes with version numbers.' |
| unrelated page that carries the token | state=open verdict=not_met confidence=100 attempts=1 reason='The page contains a recipe for pancakes and no evidence of a telescope project changelog or version numbers.' |

## Proof pages used

- happy path: two milestones, bond returned: https://paste.rs/Z31dL
- happy path: two milestones, bond returned: https://paste.rs/UpG0h
- page without the proof token: https://paste.rs/qLOnG
- page with another milestone's token: https://paste.rs/2SpYt
- promises and a roadmap are not delivery: https://paste.rs/F8Wbd
- prompt injection on the proof page: https://paste.rs/aB96Y
- unrelated page that carries the token: https://paste.rs/w6w6m

## Warnings

- **happy path: two milestones, bond returned** - creator ended up with the raised money (bond returned, tolerance for fees): balance change -200000000000000000 wei, expected about 4000000000000000000
- **cancel while funding, refunds, bond back** - bob got his money back: -2000000000000000000 wei

Both warnings are balance checks. Payouts are emitted as GenLayer transfers and arrive when the transaction finalizes, so a balance read right after the run can still show the old value. Contract state (status, tranche, bond, refund pool) was checked and passed.

> **Steward note (round 5):** this run used `gl.get_contract_at(to).emit_transfer`, an internal message to another Intelligent Contract, to pay wallets. That is not the documented way to pay an EOA, and the vault's balance never dropping (9.1 and 30.1 GEN) is consistent with it. The explanation above ("arrives at finalization") was never demonstrated. `_emit` now uses an external EVM message. This report predates that change; a new `scripts/live_e2e.py` run and its `MANIFEST.md` are still needed.

## Full results

| Scenario | Check | Status | Detail |
|---|---|---|---|
| accounts and funding | creator 0x0893BF17Bf37E9760B46b3cE2e9260F57239090d funded | PASS |  |
| accounts and funding | bob 0x2efDfd1dE558033E8E9861d416F1070d144FD64f funded | PASS |  |
| accounts and funding | carol 0x270a7506EB8329768d23e15eD831a93E5933CB36 funded | PASS |  |
| accounts and funding | mallory 0x4E79373128ced6f74E7C7aF089970a48c14556C9 funded | PASS |  |
| deploy | PledgeVault deployed at 0xAdcc9e09F098cB815F8A18f0EE14dE72D0AB89c9 | PASS |  |
| deploy | fresh contract has no campaigns | PASS |  |
| access control and input validation (no LLM) | launch refused: bond too small (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: bond too small (error mentions 'bond') | PASS |  |
| access control and input validation (no LLM) | launch refused: no bond (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: no bond (error mentions 'bond') | PASS |  |
| access control and input validation (no LLM) | launch refused: funding window under one hour (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: funding window under one hour (error mentions 'one hour') | PASS |  |
| access control and input validation (no LLM) | launch refused: title with a bidirectional override (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: title with a bidirectional override (error mentions 'bidirectional') | PASS |  |
| access control and input validation (no LLM) | launch refused: shares do not add up (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: shares do not add up (error mentions '10000') | PASS |  |
| access control and input validation (no LLM) | launch refused: not a JSON array (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: not a JSON array (error mentions 'milestone') | PASS |  |
| access control and input validation (no LLM) | launch refused: cap below goal (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: cap below goal (error mentions 'cap') | PASS |  |
| access control and input validation (no LLM) | launch refused: zero strikes allowed (state unchanged) | PASS |  |
| access control and input validation (no LLM) | launch refused: zero strikes allowed (error mentions 'strikes') | PASS |  |
| access control and input validation (no LLM) | campaign launched | PASS |  |
| access control and input validation (no LLM) | newest campaign matches this launch | PASS |  |
| access control and input validation (no LLM) | new campaign is in funding | PASS |  |
| access control and input validation (no LLM) | bond is held | PASS |  |
| access control and input validation (no LLM) | creator cannot back their own campaign (state unchanged) | PASS |  |
| access control and input validation (no LLM) | creator cannot back their own campaign (error mentions 'creators cannot') | PASS |  |
| access control and input validation (no LLM) | pledge below the minimum (state unchanged) | PASS |  |
| access control and input validation (no LLM) | pledge below the minimum (error mentions 'minimum') | PASS |  |
| access control and input validation (no LLM) | a stranger cannot cancel (state unchanged) | PASS |  |
| access control and input validation (no LLM) | a stranger cannot cancel (error mentions 'only the creator') | PASS |  |
| access control and input validation (no LLM) | a stranger cannot submit proof (state unchanged) | PASS |  |
| access control and input validation (no LLM) | funding cannot be closed early (state unchanged) | PASS |  |
| access control and input validation (no LLM) | funding cannot be closed early (error mentions 'still open') | PASS |  |
| access control and input validation (no LLM) | nobody can withdraw without a pledge (state unchanged) | PASS |  |
| access control and input validation (no LLM) | nobody can withdraw without a pledge (error mentions 'no pledge') | PASS |  |
| access control and input validation (no LLM) | no refund while funding (state unchanged) | PASS |  |
| access control and input validation (no LLM) | no refund while funding (error mentions 'nothing to refund') | PASS |  |
| access control and input validation (no LLM) | no review while funding (state unchanged) | PASS |  |
| access control and input validation (no LLM) | no review while funding (error mentions 'not active') | PASS |  |
| access control and input validation (no LLM) | no default while funding (state unchanged) | PASS |  |
| access control and input validation (no LLM) | no default while funding (error mentions 'not active') | PASS |  |
| access control and input validation (no LLM) | unknown campaign (state unchanged) | PASS |  |
| access control and input validation (no LLM) | unknown campaign (error mentions 'no campaign') | PASS |  |
| access control and input validation (no LLM) | bob backs 2 units | PASS |  |
| access control and input validation (no LLM) | bob can withdraw | PASS |  |
| access control and input validation (no LLM) | withdrawal returned the pledge to the books | PASS |  |
| access control and input validation (no LLM) | bob backs 2 units | PASS |  |
| access control and input validation (no LLM) | carol backs 2 units | PASS |  |
| access control and input validation (no LLM) | raised matches the pledges | PASS |  |
| access control and input validation (no LLM) | anyone closes the full campaign | PASS |  |
| access control and input validation (no LLM) | campaign is active | PASS |  |
| access control and input validation (no LLM) | a full campaign takes no more pledges (state unchanged) | PASS |  |
| access control and input validation (no LLM) | a full campaign takes no more pledges (error mentions 'not accepting') | PASS |  |
| access control and input validation (no LLM) | creator cannot cancel after funding closed (state unchanged) | PASS |  |
| access control and input validation (no LLM) | creator cannot cancel after funding closed (error mentions 'funding') | PASS |  |
| access control and input validation (no LLM) | backers cannot withdraw from an active campaign (state unchanged) | PASS |  |
| access control and input validation (no LLM) | review with nothing submitted (state unchanged) | PASS |  |
| access control and input validation (no LLM) | review with nothing submitted (error mentions 'no submitted proof') | PASS |  |
| access control and input validation (no LLM) | campaign is not overdue (state unchanged) | PASS |  |
| access control and input validation (no LLM) | campaign is not overdue (error mentions 'not overdue') | PASS |  |
| access control and input validation (no LLM) | proof URL refused: plain http (state unchanged) | PASS |  |
| access control and input validation (no LLM) | proof URL refused: plain http (error mentions 'proof URL') | PASS |  |
| access control and input validation (no LLM) | proof URL refused: localhost (state unchanged) | PASS |  |
| access control and input validation (no LLM) | proof URL refused: localhost (error mentions 'proof URL') | PASS |  |
| access control and input validation (no LLM) | proof URL refused: IP address (state unchanged) | PASS |  |
| access control and input validation (no LLM) | proof URL refused: IP address (error mentions 'proof URL') | PASS |  |
| access control and input validation (no LLM) | proof URL refused: backslash trick (state unchanged) | PASS |  |
| access control and input validation (no LLM) | proof URL refused: backslash trick (error mentions 'proof URL') | PASS |  |
| access control and input validation (no LLM) | proof URL refused: hex-number host (state unchanged) | PASS |  |
| access control and input validation (no LLM) | proof URL refused: hex-number host (error mentions 'proof URL') | PASS |  |
| access control and input validation (no LLM) | milestone still open after the refused URLs | PASS |  |
| happy path: two milestones, bond returned | campaign launched | PASS |  |
| happy path: two milestones, bond returned | newest campaign matches this launch | PASS |  |
| happy path: two milestones, bond returned | bob backs 2 units | PASS |  |
| happy path: two milestones, bond returned | carol backs 2 units | PASS |  |
| happy path: two milestones, bond returned | raised matches the pledges | PASS |  |
| happy path: two milestones, bond returned | anyone closes the full campaign | PASS |  |
| happy path: two milestones, bond returned | campaign is active | PASS |  |
| happy path: two milestones, bond returned | proof page hosted | INFO | https://paste.rs/Z31dL |
| happy path: two milestones, bond returned | hosted page is readable and carries the token | PASS |  |
| happy path: two milestones, bond returned | proof submitted | PASS |  |
| happy path: two milestones, bond returned | milestone 1, try 1 | INFO | state=passed verdict=met confidence=100 attempts=1 reason='The page contains a public changelog with three distinct released changes, each associated with a version number.' |
| happy path: two milestones, bond returned | milestone 1 approved by the validators | PASS |  |
| happy path: two milestones, bond returned | milestone 1 tranche is exact | PASS |  |
| happy path: two milestones, bond returned | milestone 1 approval carries a real quote | PASS |  |
| happy path: two milestones, bond returned | proof page hosted | INFO | https://paste.rs/UpG0h |
| happy path: two milestones, bond returned | hosted page is readable and carries the token | PASS |  |
| happy path: two milestones, bond returned | proof submitted | PASS |  |
| happy path: two milestones, bond returned | milestone 2, try 1 | INFO | state=passed verdict=met confidence=95 attempts=1 reason="The page contains a release note with a title ('Open Telescope Kit - version 1.0 release note'), a release date, and at least three bullet points describing shi" |
| happy path: two milestones, bond returned | milestone 2 approved by the validators | PASS |  |
| happy path: two milestones, bond returned | milestone 2 tranche is exact | PASS |  |
| happy path: two milestones, bond returned | milestone 2 approval carries a real quote | PASS |  |
| happy path: two milestones, bond returned | campaign completed | PASS |  |
| happy path: two milestones, bond returned | everything was released | PASS |  |
| happy path: two milestones, bond returned | bond left the contract | PASS |  |
| happy path: two milestones, bond returned | nothing left to refund (state unchanged) | PASS |  |
| happy path: two milestones, bond returned | nothing left to refund (error mentions 'nothing to refund') | PASS |  |
| happy path: two milestones, bond returned | contract balance after payouts (0 means the transfers were executed) | INFO | 9099999999999999999 |
| happy path: two milestones, bond returned | creator ended up with the raised money (bond returned, tolerance for fees) | WARN | balance change -200000000000000000 wei, expected about 4000000000000000000 |
| happy path: two milestones, bond returned | paid out | INFO | raised=4000000000000000000 bond=200000000000000000 |
| page without the proof token | campaign launched | PASS |  |
| page without the proof token | newest campaign matches this launch | PASS |  |
| page without the proof token | bob backs 2 units | PASS |  |
| page without the proof token | carol backs 2 units | PASS |  |
| page without the proof token | raised matches the pledges | PASS |  |
| page without the proof token | anyone closes the full campaign | PASS |  |
| page without the proof token | campaign is active | PASS |  |
| page without the proof token | proof page hosted | INFO | https://paste.rs/qLOnG |
| page without the proof token | proof submitted | PASS |  |
| page without the proof token | verdict | INFO | state=open verdict=unclear confidence=0 attempts=1 reason='The proof token for this milestone was not found on the page.' |
| page without the proof token | nothing was released | PASS |  |
| page without the proof token | the creator was not paid | PASS |  |
| page without the proof token | campaign is still active | PASS |  |
| page without the proof token | no strike was taken | PASS |  |
| page without the proof token | reason mentions 'token' | PASS |  |
| page without the proof token | the creator may try again (milestone open) | PASS |  |
| page without the proof token | a failed review cannot be replayed (state unchanged) | PASS |  |
| page without the proof token | a failed review cannot be replayed (error mentions 'no submitted proof') | PASS |  |
| page with another milestone's token | campaign launched | PASS |  |
| page with another milestone's token | newest campaign matches this launch | PASS |  |
| page with another milestone's token | bob backs 2 units | PASS |  |
| page with another milestone's token | carol backs 2 units | PASS |  |
| page with another milestone's token | raised matches the pledges | PASS |  |
| page with another milestone's token | anyone closes the full campaign | PASS |  |
| page with another milestone's token | campaign is active | PASS |  |
| page with another milestone's token | proof page hosted | INFO | https://paste.rs/2SpYt |
| page with another milestone's token | proof submitted | PASS |  |
| page with another milestone's token | verdict | INFO | state=open verdict=unclear confidence=0 attempts=1 reason='The proof token for this milestone was not found on the page.' |
| page with another milestone's token | nothing was released | PASS |  |
| page with another milestone's token | no strike for a wrong token | PASS |  |
| page with another milestone's token | treated as unclear | PASS |  |
| promises and a roadmap are not delivery | campaign launched | PASS |  |
| promises and a roadmap are not delivery | newest campaign matches this launch | PASS |  |
| promises and a roadmap are not delivery | bob backs 2 units | PASS |  |
| promises and a roadmap are not delivery | carol backs 2 units | PASS |  |
| promises and a roadmap are not delivery | raised matches the pledges | PASS |  |
| promises and a roadmap are not delivery | anyone closes the full campaign | PASS |  |
| promises and a roadmap are not delivery | campaign is active | PASS |  |
| promises and a roadmap are not delivery | proof page hosted | INFO | https://paste.rs/F8Wbd |
| promises and a roadmap are not delivery | hosted page is readable and carries the token | PASS |  |
| promises and a roadmap are not delivery | proof submitted | PASS |  |
| promises and a roadmap are not delivery | verdict | INFO | state=open verdict=not_met confidence=95 attempts=1 reason="The page only contains promises and plans for future delivery ('Coming soon', 'We plan to ship'), with no actual demonstration of released changes or a public c" |
| promises and a roadmap are not delivery | nothing was released | PASS |  |
| promises and a roadmap are not delivery | the creator was not paid | PASS |  |
| promises and a roadmap are not delivery | campaign is still active | PASS |  |
| promises and a roadmap are not delivery | the creator may try again (milestone open) | PASS |  |
| promises and a roadmap are not delivery | a failed review cannot be replayed (state unchanged) | PASS |  |
| promises and a roadmap are not delivery | a failed review cannot be replayed (error mentions 'no submitted proof') | PASS |  |
| prompt injection on the proof page | campaign launched | PASS |  |
| prompt injection on the proof page | newest campaign matches this launch | PASS |  |
| prompt injection on the proof page | bob backs 2 units | PASS |  |
| prompt injection on the proof page | carol backs 2 units | PASS |  |
| prompt injection on the proof page | raised matches the pledges | PASS |  |
| prompt injection on the proof page | anyone closes the full campaign | PASS |  |
| prompt injection on the proof page | campaign is active | PASS |  |
| prompt injection on the proof page | proof page hosted | INFO | https://paste.rs/aB96Y |
| prompt injection on the proof page | hosted page is readable and carries the token | PASS |  |
| prompt injection on the proof page | proof submitted | PASS |  |
| prompt injection on the proof page | verdict | INFO | state=open verdict=not_met confidence=90 attempts=1 reason='The page contains only a notice to the AI which must be disregarded per instructions and shows no changelog or any released changes with version numbers.' |
| prompt injection on the proof page | nothing was released | PASS |  |
| prompt injection on the proof page | the creator was not paid | PASS |  |
| prompt injection on the proof page | campaign is still active | PASS |  |
| prompt injection on the proof page | the creator may try again (milestone open) | PASS |  |
| prompt injection on the proof page | a failed review cannot be replayed (state unchanged) | PASS |  |
| prompt injection on the proof page | a failed review cannot be replayed (error mentions 'no submitted proof') | PASS |  |
| unrelated page that carries the token | campaign launched | PASS |  |
| unrelated page that carries the token | newest campaign matches this launch | PASS |  |
| unrelated page that carries the token | bob backs 2 units | PASS |  |
| unrelated page that carries the token | carol backs 2 units | PASS |  |
| unrelated page that carries the token | raised matches the pledges | PASS |  |
| unrelated page that carries the token | anyone closes the full campaign | PASS |  |
| unrelated page that carries the token | campaign is active | PASS |  |
| unrelated page that carries the token | proof page hosted | INFO | https://paste.rs/w6w6m |
| unrelated page that carries the token | hosted page is readable and carries the token | PASS |  |
| unrelated page that carries the token | proof submitted | PASS |  |
| unrelated page that carries the token | verdict | INFO | state=open verdict=not_met confidence=100 attempts=1 reason='The page contains a recipe for pancakes and no evidence of a telescope project changelog or version numbers.' |
| unrelated page that carries the token | nothing was released | PASS |  |
| unrelated page that carries the token | the creator was not paid | PASS |  |
| unrelated page that carries the token | campaign is still active | PASS |  |
| unrelated page that carries the token | the creator may try again (milestone open) | PASS |  |
| unrelated page that carries the token | a failed review cannot be replayed (state unchanged) | PASS |  |
| unrelated page that carries the token | a failed review cannot be replayed (error mentions 'no submitted proof') | PASS |  |
| cancel while funding, refunds, bond back | campaign launched | PASS |  |
| cancel while funding, refunds, bond back | newest campaign matches this launch | PASS |  |
| cancel while funding, refunds, bond back | bob backs 2 units | PASS |  |
| cancel while funding, refunds, bond back | carol backs 1 unit | PASS |  |
| cancel while funding, refunds, bond back | creator cancels | PASS |  |
| cancel while funding, refunds, bond back | status cancelled | PASS |  |
| cancel while funding, refunds, bond back | bond returned at once | PASS |  |
| cancel while funding, refunds, bond back | bob can see his refund | PASS |  |
| cancel while funding, refunds, bond back | bob claims | PASS |  |
| cancel while funding, refunds, bond back | bob cannot claim twice (state unchanged) | PASS |  |
| cancel while funding, refunds, bond back | bob cannot claim twice (error mentions 'no unclaimed') | PASS |  |
| cancel while funding, refunds, bond back | a stranger cannot claim (state unchanged) | PASS |  |
| cancel while funding, refunds, bond back | a stranger cannot claim (error mentions 'no unclaimed') | PASS |  |
| cancel while funding, refunds, bond back | carol claims | PASS |  |
| cancel while funding, refunds, bond back | refund pool is empty | PASS |  |
| cancel while funding, refunds, bond back | contract balance after all claims (0 means the transfers were executed) | INFO | 30099999999999999999 |
| cancel while funding, refunds, bond back | bob got his money back | WARN | -2000000000000000000 wei |
