# PledgeProof

**Milestone crowdfunding where GenLayer consensus releases the money.**

A creator pitches a project with a plan of milestones and locks a bond. Backers
pledge GEN. The money stays in the vault and is released **one tranche at a
time**, only when validators independently read the creator's public proof page
and agree that the milestone was really delivered. If the creator does not
deliver, backers get the unreleased money back **plus the creator's bond**.

No platform decides who delivered. No backer vote can be bought. The judgment
is made by the validator set, on evidence anyone can open in a browser.

Built for **GenLayer Studionet**.

---

## Why this needs an Intelligent Contract

"Did the creator ship the audited release?" is not a number a price feed can
report. It is a judgment about a web page. A normal smart contract cannot fetch
the page, and cannot read it. An Intelligent Contract can do both, and the
Equivalence Principle lets independent validators reach the same decision
without trusting one party.

## Lifecycle

```
launch_campaign (+ bond)
      |
   funding  --(back / withdraw_pledge)-->  close_funding
      |                                        |
      | goal missed / cancelled                | goal met
      v                                        v
   refunds  <---------- failed <------------ active: milestone 1 .. N
 (pro rata)       strikes or missed deadline        |
                                                    | all milestones approved
                                                    v
                                                completed (bond returned)
```

1. **`launch_campaign`** – title, pitch, goal, cap, minimum pledge, funding
   deadline, strike limit, and a JSON milestone plan. The call carries the
   **creator bond** (at least 5% of the goal).
2. **`back` / `withdraw_pledge`** – anyone except the creator pledges while
   funding is open. Pledges can be withdrawn until the deadline.
3. **`close_funding`** – after the deadline (or once the cap is hit) anyone
   closes funding. Goal met: the campaign becomes `active`. Goal missed:
   everyone is refunded in full and the bond goes back to the creator.
4. **`submit_proof`** – the creator submits a public `https://` page for the
   current milestone, and puts that milestone's **proof token**
   (`get_proof_token`) on the page.
5. **`review`** – validators render the page, check the token, and judge it
   against the milestone's acceptance criteria.
   * confident **met** with a verifiable quote → the tranche is paid to the creator
   * confident **not met** → the creator takes a **strike**
   * anything else → **nothing happens**; the creator may resubmit for free
6. The last approved milestone **completes** the campaign and returns the bond.
7. **`declare_default`** – anyone can fail a campaign whose current milestone
   is overdue. **`claim_refund`** – each backer pulls their own share.

### Milestone plan format

`milestones_json` is a JSON array of 1 to 6 objects:

```json
[
  {"description": "Publish a working alpha with a public changelog", "bps": 3000, "due": 1802000000},
  {"description": "Publish the independent security audit report",  "bps": 3000, "due": 1804000000},
  {"description": "Ship version 1.0 and publish the release notes",  "bps": 4000, "due": 1807000000}
]
```

* `bps` – share of the raised amount in basis points; all shares sum to exactly `10000`.
* `due` – unix seconds; strictly increasing and later than the funding deadline.
* `description` – 12 to 500 characters. These are the acceptance criteria the
  validators judge against. Backers read them *before* pledging.

## How the consensus design works

The risky part of any AI-judged escrow is the judgment itself. PledgeProof
splits it into checks the contract can make **deterministically** and a
narrow slice that genuinely needs an LLM.

| Layer | What it does | Where it runs |
|---|---|---|
| Proof token | The page must contain a token bound to this contract, campaign, milestone and creator. A creator cannot point a milestone at somebody else's impressive page. | Inside every validator's own fetch |
| Quote grounding | A "met" verdict must include a quote, and the quote must appear verbatim on the page (case, whitespace and typographic quotes ignored). A hallucinated approval is downgraded to "unclear". | Inside every validator |
| LLM judgment | Does the page demonstrate the acceptance criteria? Page text is fenced as untrusted data; promises and roadmaps are explicitly not delivery. | Every validator, independently |
| Effect-level agreement | Validators compare the **on-chain effect** of the verdict (release / strike / nothing) and require confidence within 20 points. Wording is never compared. | Validator function |
| Leader checks | A validator first checks the **shape** of the leader's answer (exact keys, a known verdict, an integer confidence 0-100, bounded text) and, for an approval, that the leader's quote is on **its own copy** of the page. A modified leader cannot smuggle in a forged quote. | Validator function |
| Confidence gates | Release needs `met` at 70+. A strike needs `not_met` at 65+. Everything in between is free for both sides. | Contract |

Errors follow GenLayer's recommended prefixes: `[EXPECTED]`, `[EXTERNAL]`,
`[TRANSIENT]` and `[LLM_ERROR]`. A temporarily unreachable page reverts the
review (no strike, no payment) and anyone can retry. A misbehaving model never
reaches agreement, which forces a validator rotation instead of a bad verdict.

## Money rules

* **Tranches** use cumulative rounding, so they always add up to exactly the
  raised amount. The last milestone absorbs any dust.
* **Refunds** are pull-based, so the number of backers is unbounded and one
  bad recipient cannot block anyone else. Shares use a running pool/weight pair
  (`share = pledge * pool_left // weight_left`, then both shrink), which makes
  the payouts add up to the pool **exactly**.
* **Failure pool** = money not yet released + the creator's bond, split in
  proportion to pledges. A failed creator therefore pays backers a penalty.
* The vault is always exactly solvent. The test-suite checks
  `balance == what is owed` after every transaction of randomised histories.

### Fairness rules for the creator

* A review by anyone other than the creator waits **1 hour** after the
  submission, so a bystander cannot trigger a verdict while the page is still
  being finished. Resubmitting restarts the delay.
* Every milestone gets at least **3 days** of working time from the moment it
  becomes current, even if its stated due date is earlier (for example because
  nobody called `close_funding` on time).
* A submitted proof gets a full **3-day** review window before anyone may call
  a default over it.
* A review that pays nothing (an unclear verdict, or a strike that does not end
  the campaign) gives the creator a **fresh 3-day window** to fix the page and
  resubmit, for the first **3 reviews** of a milestone. Without this, a proof
  submitted shortly before the due date and judged late could never be fixed.
* An unreachable page, an unclear verdict or a missing token never cost a strike.
* A creator can cancel only **while the funding window is open and the cap is
  not reached**. Once funding is decided, only `close_funding` applies, so a
  funded creator cannot walk away with the bond intact.

### Input hardening

* Titles, pitches and milestone descriptions are rejected if they contain
  bidirectional overrides or control characters (text that looks different to a
  person than to a machine). Zero-width characters are silently removed.
* The milestone plan is capped at 10,000 characters and must be plain text
  descriptions; deeply nested or oversized JSON is refused with a clear error.
* Proof URLs must be plain ASCII `https://` URLs on a real domain name whose
  last label is letters: no backslashes, percent-encoded hosts, IP addresses
  (in any spelling such as `0x7f.1`), `localhost`/private suffixes, or invalid
  ports.

## Contract API

Writes: `launch_campaign` (payable, the value is the bond), `back` (payable),
`withdraw_pledge`, `cancel_campaign`, `close_funding`, `submit_proof`,
`review`, `declare_default`, `claim_refund`.

Views: `get_campaign` (includes `cure_until`, the end of any deadline
extension earned by a review that paid nothing), `get_milestone`,
`get_proof_token`, `get_position`, `list_campaign_ids`, `campaign_count`,
`required_bond`.

Amounts and timestamps are returned as decimal strings so JavaScript clients
never lose precision on wei values.

## Repository layout

```
contracts/pledge_vault.py   the Intelligent Contract (PledgeVault)
pledgeproof.py              GenVM oracle: web render + LLM + validator consensus
pledgeproof_pure.py         pure helpers (money math, parsing, verdict rules, prompt)
scripts/bundle.py           flattens the three files into one deployable contract
scripts/live_e2e.py         live end-to-end test against Studionet (real validators, real LLM)
scripts/codespaces_live.sh  one-command setup + gate + live run for GitHub Codespaces
dist/pledge_vault.bundle.py the file you deploy (generated, checked in for convenience)
tests/                      unit tests, direct-mode contract tests, adversarial tests,
                            reference-model fuzzing, self-check of the live script
DEBUG_LOG.md                every bug found in the debug loop and how it was fixed
```

GenLayer's default deploy path takes one Python file per contract, so
`scripts/bundle.py` inlines the two library modules into the contract. It
refuses to write a bundle whose header, imports or names are broken. **Always
deploy `dist/pledge_vault.bundle.py`.**

## Deploying to Studionet

1. Install the CLI and bundle the contract:

   ```bash
   npm install -g genlayer
   python scripts/bundle.py
   ```

2. Point the CLI at Studionet and fund your account from the faucet
   (the faucet button in [Studio](https://studio.genlayer.com)'s account selector):

   ```bash
   genlayer network set studionet
   genlayer network info
   ```

3. Deploy (the constructor takes no arguments):

   ```bash
   genlayer deploy --contract dist/pledge_vault.bundle.py
   ```

   Prefer a browser? Open Studio, choose **Add From File**, select
   `dist/pledge_vault.bundle.py` and press **Deploy**.

4. Try it. Replace `<addr>` and the unix timestamps (`date +%s` plus offsets):

   ```bash
   # 1. launch (bond = 5% of the goal; goal here is 100 GEN so the bond is 5 GEN)
   genlayer write <addr> launch_campaign \
     --args "Open Telescope Kit" "A community-built open hardware telescope with public designs." \
            100000000000000000000 200000000000000000000 1000000000000000000 \
            <funding_deadline> 2 \
            '[{"description":"Publish a working alpha with a public changelog","bps":4000,"due":<due_1>},{"description":"Ship version 1.0 and publish the release notes","bps":6000,"due":<due_2>}]' \
     --value 5gen

   # 2. back it from another account
   genlayer write <addr> back --args 0 --value 10gen

   # 3. after the funding deadline
   genlayer write <addr> close_funding --args 0

   # 4. put the token on a public page, then submit and review it
   genlayer call  <addr> get_proof_token --args 0 0
   genlayer write <addr> submit_proof --args 0 "https://example.com/my-launch-notes"
   genlayer write <addr> review --args 0

   # 5. inspect
   genlayer call <addr> get_campaign --args 0
   ```

   Use a funding window of at least one hour. Studio's account switcher is
   the easiest way to act as creator and backer from one browser.

The contract header pins the `py-genlayer` runner version that the GenVM linter
and the direct-mode tests in this repository were validated against.

## Testing

```bash
pip install -r requirements-dev.txt

pytest tests/test_pure_logic.py tests/test_pure_adversarial.py -v   # plain pytest, no GenVM needed
genvm-lint check dist/pledge_vault.bundle.py
pytest tests -v                                                      # everything, in direct mode
PP_FUZZ_SEEDS=700 pytest tests/test_model_fuzz.py                    # a much longer fuzz run
```

| File | What it proves |
|---|---|
| `test_pure_logic.py`, `test_pure_adversarial.py` | money maths, URL / quote / plan / verdict parsing, hostile inputs, exact thresholds |
| `test_pledge_vault.py` | the real bundled contract: every verdict path, deadlines, refunds, validators |
| `test_vault_regressions.py` | one section per bug the debug loop found (see `DEBUG_LOG.md`) |
| `test_vault_adversarial.py` | access control, second-by-second boundaries, replays, griefing, isolation between campaigns |
| `test_invariants.py` | randomised histories: the vault is exactly solvent after every transaction |
| `test_model_fuzz.py` | the contract against an **independent reference model**, step by step, on random histories |
| `test_live_script_selfcheck.py` | the live script's scenarios, run against the in-memory contract |

The direct-mode suite runs the real bundled contract in GenVM's in-memory
runner with the web and the LLM mocked. A transaction that reverts is rolled
back by the harness, so tests also prove that failed calls leave no trace. The
suite was also mutation-tested: twelve deliberately injected bugs (an off-by-one
deadline, a missing double-claim guard, a skipped bond return, ...) are all
caught.

> **Direct mode needs a GenVM release that ships `genvm-universal.tar.xz`.**
> GitHub's "latest" release can be a pre-release without it (the download then
> fails with a 404). `scripts/codespaces_live.sh` pre-seeds the cache with
> `v0.2.16`; to do it by hand, download
> `https://github.com/genlayerlabs/genvm/releases/download/v0.2.16/genvm-universal.tar.xz`
> to `~/.cache/gltest-direct/genvm-universal-v0.2.16.tar.xz`.

## Live end-to-end on Studionet (GitHub Codespaces)

Open the repository in a Codespace (the included `.devcontainer` gives you
Python 3.12) and run:

```bash
bash scripts/codespaces_live.sh              # bundle -> lint + full tests -> live E2E
```

Useful variants:

```bash
bash scripts/codespaces_live.sh --skip-tests          # only the live run
bash scripts/codespaces_live.sh --only happy,cancel   # pick scenarios
bash scripts/codespaces_live.sh --long                # also the ~65 min goal-missed flow
```

It creates four throw-away accounts (kept in the git-ignored
`.live_accounts.json`), funds them from the Studio faucet RPC, deploys
`dist/pledge_vault.bundle.py`, publishes proof pages to a public paste service
and runs these scenarios against the real validators:

| Scenario | Checks |
|---|---|
| `access` | every access-control and validation refusal, bad proof URLs, state unchanged after each |
| `happy` | two milestones approved, exact tranches, real quote stored, bond returned |
| `notoken` / `wrongtoken` | no payment, no strike, treated as unclear |
| `roadmap` / `injection` / `unrelated` | nothing is ever released for promises, an injected instruction or an unrelated page |
| `cancel` | cancel while funding, refunds, bond back at once |
| `goalmissed` (`--long`) | refunds after a missed goal |

A real model is not deterministic, so the approval step retries up to three
times before it reports a failure, and checks that depend on finalization
(balances) are warnings rather than failures. Results go to the terminal and to
`artifacts/live_report.json`. If the faucet RPC is refused, the script prints
the addresses to fund by hand in [Studio](https://studio.genlayer.com).
To host proof pages yourself, set `PP_PAGE_CMD` to a command that takes a file
path and prints a public `https://` URL.

## Payments: pull, never push

No transaction that takes part in consensus sends GEN. `review`, `close_funding`,
`cancel_campaign`, `declare_default`, `withdraw_pledge` and `claim_refund` only
**credit** an internal ledger; the beneficiary then collects it with `claim_payout`.

| piece | meaning |
|---|---|
| `credits[address]` | what an address can take out now (tranches, bond, refunds, withdrawn pledges, across all campaigns) |
| `claim_payout()` | deterministic: debits the caller's whole credit and emits one transfer to the caller's wallet. The only method that moves GEN out |
| `claim_refund(cid)` | step 1 for a backer of a failed or cancelled campaign: moves their pro-rata share onto their credit. Step 2 is `claim_payout` |
| `get_credit(owner)` | claimable amount of one address |
| `get_accounting()` | `locked_total`, `total_credits`, `total_claimed`, `balance`, `unallocated`, `solvent` |
| `list_credits(cid, start, limit)` / `get_credit_entry(id)` | append-only credit log: who became entitled to what, and why |

The transfer of a claim is an external message, so it runs when the claim is
**finalized**: the credit is gone as soon as the call is accepted, the vault's
balance drops at finalization. Once every claim is finalized,
`balance == locked_total + total_credits` (the invariant the live script checks).

Trade-off: there is no re-send. If the external message of a claim never ran,
the credit is already debited. `get_accounting` shows it as `unallocated`
or `shortfall`, but the contract cannot repair it.

Not verified here: the contract has only been run in Direct Mode. A new live
run on Studionet (`artifacts/MANIFEST.md`: credits, claims and balance
reconciliation) is the proof that the transfer arrives.

## Evidence

`python scripts/live_e2e.py` writes, next to `live_report.json`:

* `artifacts/manifest.json` and `artifacts/MANIFEST.md`: deployment tx, every
  transaction with its status now, the credit log, every `claim_payout`, and each
  recipient's balance before/after against what they sent in and pulled;
* hard failures (not warnings) when a claim does not reach the wallet after finalization
  or a recipient balance does not match.

## Limits and honest caveats

* The LLM can still be fooled by a cleverly written page. The prompt fence,
  the proof token and the verbatim-quote rule shrink that surface but do not
  remove it, and backers should read the acceptance criteria and the creator's
  history before pledging.
* A creator can back their own campaign through other addresses. That only
  moves their own money in a circle (and leaves the bond at risk), but it can
  inflate the apparent raise.
* Acceptance criteria are written by the creator. Vague criteria are a red flag
  for backers.
* Payouts are **pull payments**. Review, cancel and refund transactions only
  credit an internal ledger; `claim_payout` is the single deterministic call that
  debits the caller's credit and emits one transfer. The contract cannot see
  whether an emitted transfer was delivered, so a claim whose external message
  never runs cannot be re-sent from inside the contract.
* Payouts go to ordinary wallets, so `_send_gen()` sends them as **external
  messages** through the vault's ghost contract (an `@gl.evm.contract_interface`
  stub with `emit_transfer`), not `gl.get_contract_at(to).emit_transfer(...)`,
  which is an internal message to another Intelligent Contract. External
  messages run on finalization, never earlier. The direct-mode harness fails any
  test in which the vault sends an internal message.
* Live evidence: `artifacts/live_report.json` and `artifacts/MANIFEST.md` come
  from a Studionet run against `0x61BcF2B2Ed688119d5c06551c092C0Be79879A45`
  (273 PASS, 0 FAIL, 0 WARN). Every claim shows the recipient's wallet before and
  after finalization, plus the outgoing child message(s) the chain reports for each finalized claim, and the vault balance is reconciled against
  `locked_total + total_credits`.
* Proof pages must be plain public `https://` URLs on a domain name. A public
  domain that merely *resolves* to a private address cannot be detected by
  string checks; the validators' own fetch sandbox is the defence there.
* Backing your own campaign through other addresses also lets you win back a
  share of your own forfeited bond (the bond is split by pledge), so the
  penalty shrinks with the share you pledged yourself.
* A creator gets at most three deadline extensions per milestone from reviews
  that paid nothing; after that the stated and minimum windows apply as is.
* Funding must stay open for at least one hour, so a live run can only close
  funding early by reaching the cap (the live script does exactly that).

## License

MIT
