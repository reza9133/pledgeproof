"""The payout ledger: an unsuccessful payment must never erase a beneficiary's entitlement.

An emitted transfer is fire-and-forget, so the contract keeps every payment on a ledger
until its own balance proves the money left. These tests cover the pure classification
(no VM needed) and the contract, with transfers that land late, never land, or land only
in part.
"""
import pytest

import pledgeproof_pure as pure
from conftest import DAY, GEN, HOUR, T0, fund_and_activate, launch, solvency_check, submit

BODY = "The alpha build is live and the changelog is published."


# ---------------------------------------------------------------------------
# pure classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "held,balance,inflight,expected",
    [
        (10, 10, 0, pure.PAYOUT_IDLE),
        (10, 10, 4, pure.PAYOUT_NONE_LANDED),
        (10, 12, 4, pure.PAYOUT_NONE_LANDED),      # stray deposits never look like a delivery
        (10, 7, 4, pure.PAYOUT_PARTIAL),
        (10, 6, 4, pure.PAYOUT_ALL_LANDED),
        (10, 3, 4, pure.PAYOUT_ALL_LANDED),
    ],
)
def test_payout_state(held, balance, inflight, expected):
    assert pure.payout_state(held, balance, inflight) == expected


def test_payout_state_rejects_an_inconsistent_ledger():
    with pytest.raises(pure.PlanError):
        pure.payout_state(5, 5, 6)
    with pytest.raises(pure.PlanError):
        pure.payout_state(-1, 0, 0)


def test_may_resend_needs_patience_and_an_untouched_balance():
    patience = pure.PAYOUT_PATIENCE_SECONDS
    assert pure.may_resend(10, 10, 0, patience)
    assert not pure.may_resend(10, 10, 0, patience - 1)
    assert not pure.may_resend(10, 9, 0, patience * 10)     # something left: never re-send blindly


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def pass_milestone(chain, people, cid=0):
    submit(chain, people, cid, body=BODY)
    chain.set_llm("met", 90, BODY, "The page shows the alpha and the changelog.")
    chain.tx(people["creator"], "review", cid)


def ledger(chain):
    return chain.view("get_ledger")


# ---------------------------------------------------------------------------
# the ledger follows every payment
# ---------------------------------------------------------------------------

def test_every_payment_is_recorded_and_settles_once_it_landed(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)

    payouts = chain.view("list_payouts", 0, 0, 10)
    assert [p["kind"] for p in payouts] == ["tranche"]
    assert payouts[0]["to"] == str(people["creator"]) and payouts[0]["amount"] == str(30 * GEN)
    assert payouts[0]["state"] == "sent" and payouts[0]["attempts"] == 1
    assert ledger(chain)["inflight_total"] == str(30 * GEN)
    assert ledger(chain)["state"] == pure.PAYOUT_ALL_LANDED          # simulated transfer landed at once

    chain.tx(people["dave"], "reconcile_payouts", 10)
    assert chain.view("get_payout", 0)["state"] == "settled"
    led = ledger(chain)
    assert led["inflight_total"] == "0" and led["state"] == pure.PAYOUT_IDLE
    assert int(led["held"]) == chain.balance                         # the books match the real balance
    solvency_check(chain)


def test_the_last_milestone_records_tranche_and_bond_together(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    for _ in range(3):
        pass_milestone(chain, people)
    kinds = [p["kind"] for p in chain.view("list_payouts", 0, 0, 10)]
    assert kinds == ["tranche", "tranche", "tranche_and_bond"]
    chain.tx(people["dave"], "reconcile_payouts", 0)                 # 0 = default batch
    assert ledger(chain)["inflight_total"] == "0" and int(ledger(chain)["held"]) == chain.balance == 0


def test_refunds_withdrawals_and_bond_return_are_recorded(chain, people):
    launch(chain, people["creator"], goal=100 * GEN)
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)
    chain.tx(people["bob"], "back", 0, value=20 * GEN)
    chain.tx(people["creator"], "cancel_campaign", 0)
    chain.tx(people["bob"], "claim_refund", 0)
    kinds = [p["kind"] for p in chain.view("list_payouts", 0, 0, 10)]
    assert kinds == ["pledge_withdrawn", "bond_returned", "refund"]
    chain.tx(people["dave"], "reconcile_payouts", 10)
    assert ledger(chain)["inflight_total"] == "0" and chain.balance == 0


def test_list_payouts_filters_by_campaign_and_honours_the_limit(chain, people):
    launch(chain, people["creator"])
    launch(chain, people["creator"], title="Second Telescope")
    chain.tx(people["bob"], "back", 0, value=5 * GEN)
    chain.tx(people["bob"], "back", 1, value=5 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)
    chain.tx(people["bob"], "withdraw_pledge", 1)
    assert len(chain.view("list_payouts", 0, 0, 10)) == 1
    assert len(chain.view("list_payouts", 1, 0, 10)) == 1
    assert chain.view("list_payouts", 0, 1, 10) == []                # start past campaign 0's payout
    assert len(chain.view("list_payouts", 1, 0, 1)) == 1


# ---------------------------------------------------------------------------
# payments that do not land
# ---------------------------------------------------------------------------

def test_a_payment_that_has_not_landed_is_not_settled(chain, people):
    chain.hold_transfers = True
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    assert ledger(chain)["state"] == pure.PAYOUT_NONE_LANDED

    chain.tx(people["dave"], "reconcile_payouts", 10)                # nothing left the contract: no change
    assert chain.view("get_payout", 0)["state"] == "sent"
    assert ledger(chain)["inflight_total"] == str(30 * GEN)

    chain.deliver()                                                  # finalization arrives
    chain.tx(people["dave"], "reconcile_payouts", 10)
    assert chain.view("get_payout", 0)["state"] == "settled"
    assert chain.paid_to(people["creator"]) == 30 * GEN


def test_a_lost_payment_is_kept_and_can_be_sent_again_after_the_patience_window(chain, people):
    chain.hold_transfers = True
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    chain.lose()                                                     # the transfer never arrives

    chain.reverts(people["creator"], "retry_payout", 0, match="cannot be re-sent yet")
    chain.advance(pure.PAYOUT_PATIENCE_SECONDS - 1)
    chain.reverts(people["creator"], "retry_payout", 0, match="cannot be re-sent yet")
    chain.advance(1)

    chain.tx(people["creator"], "retry_payout", 0)
    p = chain.view("get_payout", 0)
    assert p["attempts"] == 2 and p["state"] == "sent"
    chain.reverts(people["creator"], "retry_payout", 0, match="cannot be re-sent yet")   # window restarted

    chain.deliver()
    chain.tx(people["dave"], "reconcile_payouts", 10)
    assert chain.view("get_payout", 0)["state"] == "settled"
    assert chain.paid_to(people["creator"]) == 30 * GEN              # paid exactly once
    chain.reverts(people["creator"], "retry_payout", 0, match="already settled")


def test_a_payment_that_landed_can_never_be_sent_twice(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)                                    # landed at once
    chain.advance(10 * pure.PAYOUT_PATIENCE_SECONDS)
    chain.reverts(people["creator"], "retry_payout", 0, match="cannot be re-sent yet")
    assert chain.paid_to(people["creator"]) == 30 * GEN


def test_partial_delivery_blocks_a_blind_resend_and_settles_later(chain, people):
    chain.hold_transfers = True
    launch(chain, people["creator"], goal=100 * GEN)
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.tx(people["carol"], "back", 0, value=10 * GEN)
    chain.tx(people["bob"], "withdraw_pledge", 0)
    chain.tx(people["carol"], "withdraw_pledge", 0)
    chain.deliver(1)                                                 # only the first lands so far
    assert ledger(chain)["state"] == pure.PAYOUT_PARTIAL

    chain.tx(people["dave"], "reconcile_payouts", 10)                # ambiguous: left alone
    assert [p["state"] for p in chain.view("list_payouts", 0, 0, 10)] == ["sent", "sent"]
    chain.advance(10 * pure.PAYOUT_PATIENCE_SECONDS)
    chain.reverts(people["carol"], "retry_payout", 1, match="cannot be re-sent yet")   # nothing is re-sent blindly

    chain.deliver()
    chain.tx(people["dave"], "reconcile_payouts", 10)
    assert [p["state"] for p in chain.view("list_payouts", 0, 0, 10)] == ["settled", "settled"]


def test_reconcile_works_in_batches(chain, people):
    launch(chain, people["creator"], goal=100 * GEN)
    for name in ("bob", "carol", "dave"):
        chain.tx(people[name], "back", 0, value=GEN)
        chain.tx(people[name], "withdraw_pledge", 0)
    chain.tx(people["erin"], "reconcile_payouts", 2)
    assert [p["state"] for p in chain.view("list_payouts", 0, 0, 10)] == ["settled", "settled", "sent"]
    assert ledger(chain)["state"] == pure.PAYOUT_ALL_LANDED          # what is left still reconciles
    chain.tx(people["erin"], "reconcile_payouts", 2)
    assert ledger(chain)["inflight_total"] == "0"


def test_unknown_payout_ids_are_refused(chain, people):
    chain.reverts(people["bob"], "retry_payout", 7, match="no payout")
    with pytest.raises(Exception):
        chain.view("get_payout", 7)


def test_reconcile_with_nothing_in_flight_is_a_no_op(chain, people):
    chain.tx(people["bob"], "reconcile_payouts", 5)
    assert ledger(chain)["inflight_total"] == "0"
