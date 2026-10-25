"""Differential fuzzing: the real bundled contract against an independent reference model.

The model below restates the rules of the README in plain Python (no GenVM, no
storage). Random histories are replayed on both; after every transaction the
two must agree on whether it succeeded and on every observable number, and the
vault must stay exactly solvent. Raise the number of histories with
``PP_FUZZ_SEEDS=500 pytest tests/test_model_fuzz.py``.
"""
import os
import random

import pytest

import pledgeproof_pure as pure
from conftest import DAY, GEN, HOUR, PROOF_URL, T0, launch, page_with_token, plan, solvency_check

SEEDS = int(os.environ.get("PP_FUZZ_SEEDS", "120"))
BODY = "The deliverable is live and documented in detail."
GRACE = pure.REVIEW_GRACE_SECONDS
DELAY = pure.REVIEW_DELAY_SECONDS


class Refused(Exception):
    pass


class Model:
    """Reference semantics of one campaign."""

    def __init__(self, creator, goal, cap, min_pledge, deadline, max_strikes, steps, bond):
        self.creator, self.goal, self.cap, self.min_pledge = creator, goal, cap, min_pledge
        self.deadline, self.max_strikes, self.bond = deadline, max_strikes, bond
        self.bps = [s[1] for s in steps]
        self.dues = [s[2] for s in steps]
        self.status, self.raised, self.released = "funding", 0, 0
        self.pledges = {}
        self.next, self.strikes, self.current_since, self.cure_until = 0, 0, 0, 0
        self.pool = self.weight = 0
        self.mstate = ["open"] * len(steps)
        self.submitted_at = [0] * len(steps)
        self.attempts = [0] * len(steps)
        self.balance = bond
        self.credit = {}          # claimable per address: nothing is sent until claim_payout
        self.paid = {}
        self.backers = 0          # counts backers; claims after a failure do not reduce it

    # -- helpers
    def give(self, who, amount):
        """Credit ``amount`` to ``who``: the GEN stays in the vault until they claim it."""
        if amount > 0:
            self.credit[who] = self.credit.get(who, 0) + amount

    def payout(self, who):
        self.need(self.credit.get(who, 0) > 0)
        amount = self.credit[who]
        self.credit[who] = 0
        self.balance -= amount
        self.paid[who] = self.paid.get(who, 0) + amount

    def eff_due(self):
        return max(self.dues[self.next], self.current_since + GRACE, self.cure_until)

    def need(self, cond):
        if not cond:
            raise Refused

    # -- actions
    def back(self, who, value, now):
        self.need(self.status == "funding" and now < self.deadline and who != self.creator)
        self.need(value >= self.min_pledge and self.raised + value <= self.cap)
        if self.pledges.get(who, 0) == 0:
            self.backers += 1
        self.pledges[who] = self.pledges.get(who, 0) + value
        self.raised += value
        self.balance += value

    def withdraw(self, who, now):
        self.need(self.status == "funding" and now < self.deadline)
        self.need(self.pledges.get(who, 0) > 0)
        amount = self.pledges[who]
        self.pledges[who] = 0
        self.backers -= 1
        self.raised -= amount
        self.give(who, amount)

    def end_without_fault(self, status):
        self.status = status
        self.pool = self.weight = self.raised
        bond, self.bond = self.bond, 0
        self.give(self.creator, bond)

    def cancel(self, who, now):
        self.need(who == self.creator and self.status == "funding")
        self.need(now < self.deadline and self.raised < self.cap)
        self.end_without_fault("cancelled")

    def close(self, now):
        self.need(self.status == "funding")
        self.need(now >= self.deadline or self.raised >= self.cap)
        if self.raised >= self.goal:
            self.status, self.current_since = "active", now
        else:
            self.end_without_fault("failed")

    def submit(self, who, now):
        self.need(who == self.creator and self.status == "active" and now < self.eff_due())
        self.mstate[self.next] = "pending"
        self.submitted_at[self.next] = now

    def review(self, who, now, verdict, confidence, grounded, token_ok):
        self.need(self.status == "active" and self.mstate[self.next] == "pending")
        self.need(who == self.creator or now >= self.submitted_at[self.next] + DELAY)
        if not token_ok:
            verdict, confidence = "unclear", 0
        elif verdict == "met" and not grounded:
            verdict, confidence = "unclear", min(confidence, 49)
        i = self.next
        self.attempts[i] += 1
        decision = pure.decide(verdict, confidence)
        if decision == "release":
            amount = pure.tranche_amounts(self.raised, self.bps)[i]
            self.mstate[i] = "passed"
            self.released += amount
            self.strikes, self.next, self.current_since, self.cure_until = 0, i + 1, now, 0
            payout = amount
            if i + 1 == len(self.bps):
                self.status = "completed"
                payout += self.bond
                self.bond = 0
            self.give(self.creator, payout)
        else:
            self.mstate[i] = "open"
            if decision == "strike":
                self.strikes += 1
                if self.strikes >= self.max_strikes:
                    self.fail("strikes")
                    return
            if self.attempts[i] <= pure.MAX_CURED_REVIEWS:
                self.cure_until = max(self.cure_until, now + GRACE)

    def fail(self, reason):
        self.status = "failed"
        self.pool = self.raised - self.released + self.bond
        self.weight = self.raised
        self.bond = 0

    def default(self, now):
        self.need(self.status == "active")
        self.need(now >= self.eff_due())
        self.need(not (self.mstate[self.next] == "pending" and now < self.submitted_at[self.next] + GRACE))
        self.fail("deadline_missed")

    def claim(self, who):
        self.need(self.status in ("failed", "cancelled"))
        pledge = self.pledges.get(who, 0)
        self.need(pledge > 0)
        share = pure.refund_share(pledge, self.pool, self.weight)
        self.pool -= share
        self.weight -= pledge
        self.pledges[who] = 0
        self.give(who, share)


@pytest.mark.parametrize("seed", range(SEEDS))
def test_contract_matches_the_reference_model(chain, people, seed):
    from gltest.direct.loader import create_address

    rng = random.Random(10_000 + seed)
    goal = rng.choice([10, 97, 10**6 + 3, 100 * GEN + 7])
    cap = goal * rng.choice([1, 2])
    n_steps = rng.randint(1, 4)
    cuts = sorted(rng.sample(range(1, 10_000), n_steps - 1)) if n_steps > 1 else []
    shares = [b - a for a, b in zip([0] + cuts, cuts + [10_000])]
    deadline = T0 + rng.choice([HOUR, DAY, 7 * DAY])
    steps = [(f"milestone number {i} with detail", s, deadline + (4 + 5 * (i + 1)) * DAY)
             for i, s in enumerate(shares)]
    max_strikes = rng.randint(1, 3)
    min_pledge = rng.choice([1, max(1, goal // 10)])
    bond = pure.min_bond(goal) + rng.choice([0, 0, 3])
    creator = people["creator"]
    launch(chain, creator, goal=goal, cap=cap, min_pledge=min_pledge, deadline=deadline,
           max_strikes=max_strikes, milestones=plan(*steps), bond=bond)
    model = Model(str(creator), goal, cap, min_pledge, deadline, max_strikes, steps, bond)
    funders = [create_address(f"m{seed}-{i}") for i in range(rng.randint(2, 6))]
    everyone = funders + [creator, people["mallory"]]

    def run(action, sender, method, *args, value=0, **kw):
        ok_model = True
        try:
            action(**kw)
        except Refused:
            ok_model = False
        try:
            chain.tx(sender, method, *args, value=value)
            ok_chain = True
        except Exception as exc:
            ok_chain = False
            assert "[EXPECTED]" in str(exc), f"unexpected error type: {exc!r}"
        assert ok_chain == ok_model, (method, args, value, "model said", ok_model, "contract said", ok_chain)
        compare()

    def compare():
        c = chain.view("get_campaign", 0)
        assert c["status"] == model.status
        assert int(c["raised"]) == model.raised and int(c["released"]) == model.released
        assert int(c["bond"]) == model.bond and c["strikes"] == model.strikes
        assert c["next_milestone"] == model.next and int(c["cure_until"]) == model.cure_until
        assert int(c["refund_pool"]) == model.pool and int(c["refund_weight"]) == model.weight
        assert c["backer_count"] == model.backers
        assert [m["state"] for m in c["milestones"]] == model.mstate
        assert [m["attempts"] for m in c["milestones"]] == model.attempts
        assert chain.balance == model.balance, (chain.balance, model.balance)
        for who in everyone:
            assert chain.paid_to(who) == model.paid.get(str(who), 0)
            assert chain.credit(who) == model.credit.get(str(who), 0)
        acc = chain.view("get_accounting")
        assert int(acc["total_credits"]) == sum(model.credit.values())
        solvency_check(chain)

    for _ in range(70):
        now = chain.now
        who = rng.choice(funders)
        action = rng.choice(["back", "back", "withdraw", "cancel", "close", "submit", "submit", "review", "review",
                             "review", "default", "claim", "claim", "payout", "payout", "time", "time", "time"])
        if action == "back":
            value = rng.randint(1, max(1, goal))
            run(lambda: model.back(str(who), value, now), who, "back", 0, value=value)
        elif action == "withdraw":
            run(lambda: model.withdraw(str(who), now), who, "withdraw_pledge", 0)
        elif action == "cancel":
            sender = rng.choice([creator, who])
            run(lambda: model.cancel(str(sender), now), sender, "cancel_campaign", 0)
        elif action == "close":
            run(lambda: model.close(now), who, "close_funding", 0)
        elif action == "submit":
            sender = rng.choice([creator, creator, who])
            if model.status == "active":
                text, _ = page_with_token(chain, 0, model.next, BODY)
                chain.set_page(PROOF_URL, text)
            run(lambda: model.submit(str(sender), now), sender, "submit_proof", 0, PROOF_URL)
        elif action == "review":
            verdict = rng.choice(["met", "met", "not_met", "unclear"])
            confidence = rng.choice([0, 30, 49, 64, 65, 69, 70, 71, 90, 100])
            grounded = rng.random() < 0.8
            token_ok = rng.random() < 0.85
            if model.status == "active":
                token = chain.view("get_proof_token", 0, model.next)
                text = f"{BODY} {token}" if token_ok else BODY
                chain.set_page(PROOF_URL, text)
            quote = BODY if (verdict == "met" and grounded) else ("Totally different words appear here." if verdict == "met" else "")
            chain.set_llm(verdict, confidence, quote, "random")
            sender = rng.choice([creator, who, people["mallory"]])
            run(lambda: model.review(str(sender), now, verdict, confidence, grounded, token_ok),
                sender, "review", 0)
        elif action == "default":
            run(lambda: model.default(now), who, "declare_default", 0)
        elif action == "claim":
            run(lambda: model.claim(str(who)), who, "claim_refund", 0)
        elif action == "payout":
            sender = rng.choice([creator, who])
            run(lambda: model.payout(str(sender)), sender, "claim_payout")
        else:
            chain.advance(rng.choice([1, HOUR - 1, HOUR, DAY, 3 * DAY, 3 * DAY + 1, 9 * DAY]))

    # drive to a terminal state and pay everybody out
    chain.set_time(max(chain.now, deadline) + 1)
    now = chain.now
    if model.status == "funding":
        run(lambda: model.close(now), people["dave"], "close_funding", 0)
    if model.status == "active":
        chain.set_time(chain.now + 400 * DAY)
        now = chain.now
        run(lambda: model.default(now), people["dave"], "declare_default", 0)
    for who in funders:
        run(lambda: model.claim(str(who)) if model.pledges.get(str(who), 0) > 0 else (_ for _ in ()).throw(Refused()),
            who, "claim_refund", 0)
    assert model.status in ("completed", "failed", "cancelled")
    for who in funders + [creator]:                                  # everybody pulls what they are owed
        run(lambda: model.payout(str(who)), who, "claim_payout")
    assert chain.balance == 0 and model.balance == 0, "money was left stranded in the vault"
