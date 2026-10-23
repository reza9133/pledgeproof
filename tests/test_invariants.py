"""Randomised end-to-end runs: whatever sequence of actions happens, the vault
must always hold exactly what it owes and, once everyone has been paid, nothing."""
import random

import pytest

from conftest import DAY, GEN, HOUR, PROOF_URL, T0, launch, page_with_token, plan, solvency_check

BODY = "The deliverable is live and documented in detail."


@pytest.mark.parametrize("seed", range(40))
def test_random_histories_stay_solvent(chain, people, seed):
    from gltest.direct.loader import create_address

    rng = random.Random(seed)
    goal = rng.choice([10, 97, 10**6 + 3, 100 * GEN + 7])
    n_steps = rng.randint(1, 5)
    cuts = sorted(rng.sample(range(1, 10_000), n_steps - 1)) if n_steps > 1 else []
    shares = [b - a for a, b in zip([0] + cuts, cuts + [10_000])]
    dues = [T0 + (8 + 12 * (i + 1)) * DAY for i in range(n_steps)]
    steps = [(f"milestone number {i} with detail", s, d) for i, (s, d) in enumerate(zip(shares, dues))]
    creator = people["creator"]
    launch(chain, creator, goal=goal, cap=goal * 2, min_pledge=1, max_strikes=rng.randint(1, 3),
           milestones=plan(*steps))
    paid_in = int(chain.view("get_campaign", 0)["bond"])
    funders = [create_address(f"f{seed}-{i}") for i in range(rng.randint(1, 8))]
    pledged = set()

    def attempt(sender, method, *args, value=0):
        nonlocal paid_in
        try:
            chain.tx(sender, method, *args, value=value)
        except Exception:
            solvency_check(chain)          # a revert must leave the books untouched
            return False
        paid_in += value
        solvency_check(chain)
        return True

    for step in range(60):
        status = chain.view("get_campaign", 0)["status"]
        action = rng.choice(["back", "back", "withdraw", "close", "submit", "review", "review", "default",
                             "claim", "time", "time"])
        who = rng.choice(funders)
        if action == "back":
            if attempt(who, "back", 0, value=rng.randint(1, max(1, goal))):
                pledged.add(who)
        elif action == "withdraw":
            attempt(who, "withdraw_pledge", 0)
        elif action == "close":
            attempt(people["dave"], "close_funding", 0)
        elif action == "submit" and status == "active":
            index = chain.view("get_campaign", 0)["next_milestone"]
            text, _ = page_with_token(chain, 0, index, BODY)
            chain.set_page(PROOF_URL, text)
            attempt(creator, "submit_proof", 0, PROOF_URL)
        elif action == "review":
            verdict = rng.choice(["met", "met", "not_met", "unclear"])
            chain.set_llm(verdict, rng.randint(0, 100), BODY if verdict == "met" else "", "random")
            attempt(rng.choice([creator, who]), "review", 0)
        elif action == "default":
            attempt(who, "declare_default", 0)
        elif action == "claim":
            attempt(who, "claim_refund", 0)
        else:
            chain.advance(rng.choice([HOUR, DAY, 5 * DAY]))

    # drive the campaign to a terminal state, then pay everyone out
    chain.set_time(max(chain.now, T0 + 8 * DAY))
    attempt(people["dave"], "close_funding", 0)
    final = chain.view("get_campaign", 0)
    if final["status"] == "active":
        chain.set_time(chain.now + 200 * DAY)
        assert attempt(people["dave"], "declare_default", 0)
        final = chain.view("get_campaign", 0)
    assert final["status"] in ("completed", "failed", "cancelled")
    for funder in funders:
        attempt(funder, "claim_refund", 0)
    solvency_check(chain)
    assert chain.balance == 0, "money was left stranded in the vault"
    assert sum(chain.received.values()) == paid_in, "money was created or destroyed"
