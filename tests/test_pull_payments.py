"""Pull payments: nothing but ``claim_payout`` ever sends GEN.

Every amount that becomes somebody's money (a released tranche, the creator's bond, a
refund share, a withdrawn pledge) is only *credited* to an internal ledger. The
beneficiary then calls ``claim_payout`` themselves. These tests pin that behaviour:

* no consensus-time method (review, close_funding, cancel, default, withdraw, claim_refund)
  emits a transfer (``Chain.tx`` also fails any test where one does);
* credits add up across tranches, campaigns and kinds, and are claimed in one transfer;
* a claim debits the credit at once, cannot be repeated and cannot touch anyone else's money;
* the books (``get_accounting``) stay equal to the vault's balance, also while a claim's
  external transfer has not been finalized yet.
"""
import pytest

from conftest import DAY, GEN, HOUR, T0, fund_and_activate, launch, solvency_check, submit

BODY = "The alpha build is live and the changelog is published."


def pass_milestone(chain, people, cid=0):
    submit(chain, people, cid, body=BODY)
    chain.set_llm("met", 90, BODY, "The page shows the alpha and the changelog.")
    chain.tx(people["creator"], "review", cid)


def strike_out(chain, people, cid=0):
    for _ in range(2):
        submit(chain, people, cid, body=BODY)
        chain.set_llm("not_met", 90, "", "Nothing is delivered.")
        chain.tx(people["creator"], "review", cid)


# ---------------------------------------------------------------------------
# nothing is pushed
# ---------------------------------------------------------------------------

def test_no_consensus_time_method_sends_gen(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)                    # credit, no transfer
    fund_and_activate(chain, people)
    pass_milestone(chain, people)                                    # review -> credit
    strike_out(chain, people)                                        # review -> campaign fails
    chain.tx(people["bob"], "claim_refund", 0)                       # credit, no transfer
    chain.tx(people["carol"], "claim_refund", 0)
    assert chain.transfers == [] and chain.undelivered == []
    assert chain.balance == 105 * GEN + 10 * GEN                     # nothing has left the vault, not even the withdrawn pledge
    solvency_check(chain)


def test_cancel_and_goal_missed_only_credit_the_bond(chain, people):
    launch(chain, people["creator"])
    launch(chain, people["bob"], title="Second Telescope")
    chain.tx(people["carol"], "back", 0, value=3 * GEN)
    chain.tx(people["creator"], "cancel_campaign", 0)
    chain.set_time(T0 + 7 * DAY)
    chain.tx(people["dave"], "close_funding", 1)                     # goal missed
    assert chain.transfers == []
    assert chain.credit(people["creator"]) == 5 * GEN and chain.credit(people["bob"]) == 5 * GEN
    assert chain.credit(people["carol"]) == 0                        # refunds need claim_refund first


# ---------------------------------------------------------------------------
# claiming
# ---------------------------------------------------------------------------

def test_claim_payout_collects_every_tranche_in_one_transfer(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    pass_milestone(chain, people)
    assert chain.credit(people["creator"]) == 60 * GEN               # 30 + 30, not yet paid
    chain.tx(people["creator"], "claim_payout")
    assert chain.transfers == [(str(people["creator"]), 60 * GEN)]   # one transfer for both tranches
    assert chain.credit(people["creator"]) == 0
    pass_milestone(chain, people)                                    # last tranche + bond
    assert chain.credit(people["creator"]) == 40 * GEN + 5 * GEN
    chain.tx(people["creator"], "claim_payout")
    assert chain.paid_to(people["creator"]) == 105 * GEN and chain.balance == 0
    solvency_check(chain)


def test_credits_of_different_kinds_and_campaigns_merge_into_one_claim(chain, people):
    launch(chain, people["creator"])                                 # campaign 0
    launch(chain, people["bob"], title="Second Telescope")           # campaign 1, bob is its creator
    chain.tx(people["bob"], "back", 0, value=7 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)                    # pledge_withdrawn credit for bob
    chain.tx(people["bob"], "cancel_campaign", 1)                    # bond_returned credit for bob
    kinds = sorted(e["kind"] for e in chain.view("list_credits", 0, 0, 10) + chain.view("list_credits", 1, 0, 10))
    assert kinds == ["bond_returned", "pledge_withdrawn"]
    assert chain.credit(people["bob"]) == 7 * GEN + 5 * GEN
    chain.tx(people["bob"], "claim_payout")
    assert chain.transfers == [(str(people["bob"]), 12 * GEN)]


def test_a_claim_cannot_be_repeated_or_used_by_a_stranger(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    chain.reverts(people["mallory"], "claim_payout", match="nothing to claim")
    chain.reverts(people["bob"], "claim_payout", match="nothing to claim")       # a backer of an active campaign
    chain.tx(people["creator"], "claim_payout")
    chain.reverts(people["creator"], "claim_payout", match="nothing to claim")
    assert chain.paid_to(people["creator"]) == 30 * GEN
    assert chain.paid_to(people["mallory"]) == 0


def test_a_claim_only_ever_pays_the_caller(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    before = chain.credit(people["creator"])
    chain.reverts(people["bob"], "claim_payout", match="nothing to claim")
    assert chain.credit(people["creator"]) == before and chain.transfers == []


def test_claiming_a_refund_is_two_steps_and_the_second_pays(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=20 * GEN)
    chain.tx(people["creator"], "cancel_campaign", 0)
    chain.reverts(people["bob"], "claim_payout", match="nothing to claim")       # refund not credited yet
    assert chain.view("get_position", 0, str(people["bob"]))["refundable_now"] == str(20 * GEN)
    chain.tx(people["bob"], "claim_refund", 0)
    assert chain.credit(people["bob"]) == 20 * GEN and chain.paid_to(people["bob"]) == 0
    chain.tx(people["bob"], "claim_payout")
    assert chain.paid_to(people["bob"]) == 20 * GEN
    chain.reverts(people["bob"], "claim_refund", 0, match="no unclaimed pledge")


def test_a_zero_share_refund_leaves_nothing_to_claim(chain, people):
    """A tiny pledge can round to a zero share; that is a no-op, not a stuck credit."""
    launch(chain, people["creator"], goal=10**6, cap=10**7, min_pledge=1, bond=50_000)
    chain.tx(people["bob"], "back", 0, value=1)
    chain.tx(people["creator"], "cancel_campaign", 0)
    chain.tx(people["bob"], "claim_refund", 0)
    assert chain.credit(people["bob"]) == 1                          # cancelled: full refund, 1 wei
    chain.tx(people["bob"], "claim_payout")
    assert chain.paid_to(people["bob"]) == 1


# ---------------------------------------------------------------------------
# a transfer that has not been finalized yet
# ---------------------------------------------------------------------------

def test_the_credit_is_debited_at_once_but_the_balance_drops_at_finalization(chain, people):
    chain.hold_transfers = True                                      # external messages run on finalization
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    chain.tx(people["creator"], "claim_payout")

    assert chain.credit(people["creator"]) == 0                      # debited immediately: no double claim
    chain.reverts(people["creator"], "claim_payout", match="nothing to claim")
    assert chain.balance == 105 * GEN and chain.paid_to(people["creator"]) == 0
    acc = chain.view("get_accounting")
    assert acc["total_credits"] == "0" and acc["total_claimed"] == str(30 * GEN)
    assert acc["solvent"] is True
    assert acc["unallocated"] == str(30 * GEN)                       # the claimed GEN is still in the vault

    chain.deliver()                                                  # finalization
    assert chain.paid_to(people["creator"]) == 30 * GEN and chain.balance == 75 * GEN
    acc = chain.view("get_accounting")
    assert acc["unallocated"] == "0" and acc["solvent"] is True
    solvency_check(chain)


# ---------------------------------------------------------------------------
# the books
# ---------------------------------------------------------------------------

def test_accounting_tracks_every_step(chain, people):
    acc = chain.view("get_accounting")
    assert acc["accounted"] == "0" and acc["solvent"] is True and acc["credit_count"] == 0

    launch(chain, people["creator"])
    assert chain.view("get_accounting")["locked_total"] == str(5 * GEN)
    fund_and_activate(chain, people)
    acc = chain.view("get_accounting")
    assert acc["locked_total"] == str(105 * GEN) and acc["total_credits"] == "0"

    pass_milestone(chain, people)
    acc = chain.view("get_accounting")
    assert acc["locked_total"] == str(75 * GEN) and acc["total_credits"] == str(30 * GEN)
    assert acc["accounted"] == acc["balance"] == str(105 * GEN) and acc["credit_count"] == 1

    chain.tx(people["creator"], "claim_payout")
    acc = chain.view("get_accounting")
    assert acc["accounted"] == acc["balance"] == str(75 * GEN) and acc["total_claimed"] == str(30 * GEN)


def test_get_credit_accepts_any_address_spelling_and_rejects_garbage(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["creator"], "cancel_campaign", 0)
    text = str(people["creator"])
    assert chain.view("get_credit", text) == str(5 * GEN)
    assert chain.view("get_credit", text.lower()) == str(5 * GEN)
    assert chain.view("get_credit", str(people["bob"])) == "0"
    with pytest.raises(Exception, match="0x-prefixed"):
        chain.view("get_credit", "not-an-address")


def test_the_credit_log_explains_every_credit(chain, people):
    launch(chain, people["creator"])
    launch(chain, people["creator"], title="Second Telescope")
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.tx(people["bob"], "back", 1, value=10 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)
    chain.tx(people["bob"], "withdraw_pledge", 1)
    chain.tx(people["creator"], "cancel_campaign", 0)
    log0 = chain.view("list_credits", 0, 0, 10)
    assert [(e["kind"], e["to"], e["amount"]) for e in log0] == [
        ("pledge_withdrawn", str(people["bob"]), str(10 * GEN)),
        ("bond_returned", str(people["creator"]), str(5 * GEN)),
    ]
    assert len(chain.view("list_credits", 1, 0, 10)) == 1
    assert len(chain.view("list_credits", 0, 0, 1)) == 1             # honours the limit
    assert chain.view("list_credits", 0, 3, 10) == []                # start past campaign 0's entries
    entry = chain.view("get_credit_entry", log0[1]["id"])
    assert entry["kind"] == "bond_returned" and entry["created_at"] == str(T0)
    with pytest.raises(Exception, match="no credit entry"):
        chain.view("get_credit_entry", 99)


def test_failure_pays_the_bond_to_backers_through_credits_only(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    strike_out(chain, people)
    assert chain.credit(people["creator"]) == 0                      # a failed creator is owed nothing
    chain.tx(people["bob"], "claim_refund", 0)
    chain.tx(people["carol"], "claim_refund", 0)
    chain.tx(people["bob"], "claim_payout")
    chain.tx(people["carol"], "claim_payout")
    assert chain.paid_to(people["bob"]) == 63 * GEN and chain.paid_to(people["carol"]) == 42 * GEN
    assert chain.balance == 0
    acc = chain.view("get_accounting")
    assert acc["locked_total"] == "0" and acc["total_credits"] == "0"


def test_removed_push_machinery_is_really_gone(chain):
    for name in ("reconcile_payouts", "retry_payout", "get_ledger", "list_payouts", "get_payout"):
        assert not hasattr(chain.contract, name), name
