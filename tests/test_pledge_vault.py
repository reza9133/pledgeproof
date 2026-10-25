"""Direct-mode tests for PledgeVault (web and LLM are mocked)."""
import json
import random

import pytest

from conftest import (
    DAY, GEN, HOUR, PROOF_URL, T0, DEFAULT_PLAN, fund_and_activate, launch, page_with_token,
    plan, solvency_check, submit,
)

BODY = "The alpha build is live and the changelog is published."


def approve(chain, confidence=90):
    chain.set_llm("met", confidence, BODY, "The page shows the alpha and the changelog.")


def run_review(chain, people, who="creator"):
    return chain.tx(people[who], "review", 0)


def pass_milestone(chain, people, cid=0, confidence=90):
    submit(chain, people, cid, body=BODY)
    approve(chain, confidence)
    chain.tx(people["creator"], "review", cid)


# ===========================================================================
# launching
# ===========================================================================

def test_launch_stores_everything(chain, people):
    assert launch(chain, people["creator"]) == 0
    c = chain.view("get_campaign", 0)
    assert c["status"] == "funding" and c["milestone_count"] == 3
    assert c["bond"] == str(5 * GEN) and c["creator"] == str(people["creator"])
    assert [m["bps"] for m in c["milestones"]] == [3000, 3000, 4000]
    assert chain.balance == 5 * GEN
    assert chain.view("campaign_count") == 1
    assert launch(chain, people["bob"]) == 1
    assert chain.view("list_campaign_ids", "funding") == [0, 1]
    assert chain.view("list_campaign_ids", "active") == []
    assert chain.view("list_campaign_ids", "") == [0, 1]


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"title": "ab"}, "title"),
        ({"title": "x" * 81}, "title"),
        ({"pitch": "short"}, "pitch"),
        ({"goal": 0, "bond": 1}, "goal"),
        ({"goal": 100 * GEN, "cap": 99 * GEN}, "cap"),
        ({"min_pledge": 0}, "min_pledge"),
        ({"min_pledge": 101 * GEN}, "min_pledge"),
        ({"max_strikes": 0}, "max_strikes"),
        ({"max_strikes": 4}, "max_strikes"),
        ({"deadline": T0 + 10}, "at least one hour"),
        ({"deadline": T0 - DAY}, "at least one hour"),
        ({"deadline": T0 + 91 * DAY}, "at most 90 days"),
        ({"bond": 5 * GEN - 1}, "creator bond"),
        ({"bond": 0}, "creator bond"),
        ({"milestones": "nope"}, "invalid milestone plan"),
        ({"milestones": plan(("a long enough description", 9000, T0 + 8 * DAY))}, "10000"),
        ({"milestones": plan(("a long enough description", 10000, T0 + DAY))}, "later than"),
    ],
)
def test_launch_rejects_bad_input(chain, people, overrides, match):
    kwargs = dict(overrides)
    with pytest.raises(Exception) as info:
        launch(chain, people["creator"], **kwargs)
    assert match in str(info.value)
    assert chain.view("campaign_count") == 0


def test_title_and_pitch_whitespace_is_normalised(chain, people):
    launch(chain, people["creator"], title="  Open   Telescope \n Kit ")
    assert chain.view("get_campaign", 0)["title"] == "Open Telescope Kit"


def test_required_bond_view(chain):
    assert chain.view("required_bond", 100 * GEN) == str(5 * GEN)
    assert chain.view("required_bond", 1) == "1"


# ===========================================================================
# funding
# ===========================================================================

def test_back_accumulates_and_counts_backers_once(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.tx(people["bob"], "back", 0, value=5 * GEN)
    chain.tx(people["carol"], "back", 0, value=2 * GEN)
    c = chain.view("get_campaign", 0)
    assert c["raised"] == str(17 * GEN) and c["backer_count"] == 2
    assert chain.view("get_position", 0, str(people["bob"]))["pledged"] == str(15 * GEN)
    solvency_check(chain)


def test_back_rules(chain, people):
    launch(chain, people["creator"], goal=100 * GEN, cap=120 * GEN)
    chain.reverts(people["creator"], "back", 0, value=5 * GEN, match="own campaign")
    chain.reverts(people["bob"], "back", 0, value=GEN - 1, match="below the campaign minimum")
    chain.reverts(people["bob"], "back", 0, value=0, match="below the campaign minimum")
    chain.reverts(people["bob"], "back", 0, value=121 * GEN, match="funding cap")
    chain.reverts(people["bob"], "back", 7, value=5 * GEN, match="no campaign")
    chain.tx(people["bob"], "back", 0, value=100 * GEN)
    chain.reverts(people["carol"], "back", 0, value=21 * GEN, match="funding cap")
    chain.tx(people["carol"], "back", 0, value=20 * GEN)
    chain.set_time(T0 + 7 * DAY)
    chain.reverts(people["dave"], "back", 0, value=GEN, match="window has closed")


def test_withdraw_pledge(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=30 * GEN)
    chain.reverts(people["carol"], "withdraw_pledge", 0, match="no pledge")
    chain.tx(people["bob"], "withdraw_pledge", 0)
    assert chain.paid_to(people["bob"]) == 0                 # credited, not sent
    assert chain.credit(people["bob"]) == 30 * GEN
    solvency_check(chain)
    chain.tx(people["bob"], "claim_payout")
    assert chain.paid_to(people["bob"]) == 30 * GEN and chain.credit(people["bob"]) == 0
    c = chain.view("get_campaign", 0)
    assert c["raised"] == "0" and c["backer_count"] == 0
    chain.reverts(people["bob"], "withdraw_pledge", 0, match="no pledge")
    chain.tx(people["bob"], "back", 0, value=10 * GEN)       # can come back
    assert chain.view("get_campaign", 0)["backer_count"] == 1
    chain.set_time(T0 + 7 * DAY)
    chain.reverts(people["bob"], "withdraw_pledge", 0, match="while funding is open")
    solvency_check(chain)


def test_cancel_campaign(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=30 * GEN)
    chain.tx(people["carol"], "back", 0, value=20 * GEN)
    chain.reverts(people["bob"], "cancel_campaign", 0, match="only the creator")
    chain.tx(people["creator"], "cancel_campaign", 0)
    assert chain.paid_to(people["creator"]) == 0 and chain.transfers == []   # cancelling sends nothing
    assert chain.credit(people["creator"]) == 5 * GEN               # the bond is credited at once
    c = chain.view("get_campaign", 0)
    assert c["status"] == "cancelled" and c["fail_reason"] == "cancelled" and c["bond"] == "0"
    chain.reverts(people["creator"], "cancel_campaign", 0, match="still funding")
    chain.reverts(people["dave"], "back", 0, value=GEN, match="not accepting pledges")
    solvency_check(chain)
    chain.tx(people["bob"], "claim_refund", 0)
    chain.tx(people["carol"], "claim_refund", 0)
    assert chain.transfers == []                                    # refunds are credits until claimed
    assert chain.credit(people["bob"]) == 30 * GEN and chain.credit(people["carol"]) == 20 * GEN
    solvency_check(chain)
    chain.claim_all(people)
    assert chain.paid_to(people["bob"]) == 30 * GEN and chain.paid_to(people["carol"]) == 20 * GEN
    assert chain.paid_to(people["creator"]) == 5 * GEN
    assert chain.balance == 0


def test_close_funding_rules(chain, people):
    launch(chain, people["creator"], goal=100 * GEN, cap=150 * GEN)
    chain.tx(people["bob"], "back", 0, value=100 * GEN)
    chain.reverts(people["dave"], "close_funding", 0, match="still open")
    chain.tx(people["carol"], "back", 0, value=50 * GEN)            # hits the cap
    chain.tx(people["dave"], "close_funding", 0)                    # cap reached: may close early
    c = chain.view("get_campaign", 0)
    assert c["status"] == "active" and int(c["current_since"]) == T0
    chain.reverts(people["dave"], "close_funding", 0, match="already closed")
    solvency_check(chain)


def test_goal_missed_refunds_everyone_and_returns_bond(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=30 * GEN)
    chain.tx(people["carol"], "back", 0, value=29 * GEN + 1)
    chain.set_time(T0 + 7 * DAY)
    chain.tx(people["dave"], "close_funding", 0)
    c = chain.view("get_campaign", 0)
    assert c["status"] == "failed" and c["fail_reason"] == "goal_not_met"
    assert chain.transfers == [] and chain.credit(people["creator"]) == 5 * GEN
    assert chain.view("get_position", 0, str(people["bob"]))["refundable_now"] == str(30 * GEN)
    chain.tx(people["bob"], "claim_refund", 0)
    chain.tx(people["carol"], "claim_refund", 0)
    assert chain.transfers == []
    chain.claim_all(people)
    assert chain.paid_to(people["creator"]) == 5 * GEN
    assert chain.paid_to(people["bob"]) == 30 * GEN
    assert chain.paid_to(people["carol"]) == 29 * GEN + 1
    assert chain.balance == 0


def test_claim_refund_rules(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=30 * GEN)
    chain.reverts(people["bob"], "claim_refund", 0, match="nothing to refund")
    chain.set_time(T0 + 7 * DAY)
    chain.tx(people["dave"], "close_funding", 0)
    chain.reverts(people["carol"], "claim_refund", 0, match="no unclaimed pledge")
    chain.reverts(people["creator"], "claim_refund", 0, match="no unclaimed pledge")
    chain.tx(people["bob"], "claim_refund", 0)
    chain.reverts(people["bob"], "claim_refund", 0, match="no unclaimed pledge")


# ===========================================================================
# submitting proof
# ===========================================================================

def test_submit_proof_rules(chain, people):
    launch(chain, people["creator"])
    chain.reverts(people["creator"], "submit_proof", 0, PROOF_URL, match="not active")
    fund_and_activate(chain, people)
    chain.reverts(people["bob"], "submit_proof", 0, PROOF_URL, match="only the creator")
    chain.reverts(people["creator"], "submit_proof", 0, "http://example.com/x", match="https")
    chain.reverts(people["creator"], "submit_proof", 0, "https://127.0.0.1/x", match="domain name")
    chain.reverts(people["creator"], "submit_proof", 9, PROOF_URL, match="no campaign")
    chain.tx(people["creator"], "submit_proof", 0, PROOF_URL)
    m = chain.view("get_milestone", 0, 0)
    assert m["state"] == "pending" and m["proof_url"] == PROOF_URL and int(m["submitted_at"]) == chain.now
    # replacing a pending submission is allowed and restarts the review delay
    chain.advance(HOUR)
    chain.tx(people["creator"], "submit_proof", 0, "https://example.com/second")
    assert chain.view("get_milestone", 0, 0)["proof_url"] == "https://example.com/second"
    assert int(chain.view("get_milestone", 0, 0)["submitted_at"]) == chain.now


def test_submit_after_deadline_is_refused(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.set_time(T0 + 14 * DAY)
    chain.reverts(people["creator"], "submit_proof", 0, PROOF_URL, match="deadline for this milestone")


def test_proof_tokens_are_per_milestone_and_campaign(chain, people):
    launch(chain, people["creator"])
    launch(chain, people["creator"])
    tokens = {chain.view("get_proof_token", c, m) for c in (0, 1) for m in (0, 1, 2)}
    assert len(tokens) == 6
    assert chain.view("get_proof_token", 0, 0).startswith("PP-0-1-")
    with pytest.raises(Exception):
        chain.view("get_proof_token", 0, 3)


# ===========================================================================
# reviewing: the happy path and the money
# ===========================================================================

def test_review_pays_the_tranche(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)
    c = chain.view("get_campaign", 0)
    assert c["released"] == str(30 * GEN) and c["next_milestone"] == 1 and c["strikes"] == 0
    assert chain.transfers == [] and chain.paid_to(people["creator"]) == 0   # review never sends GEN
    assert chain.credit(people["creator"]) == 30 * GEN
    assert chain.balance == 100 * GEN + 5 * GEN                           # the vault still holds everything
    m = chain.view("get_milestone", 0, 0)
    assert m["state"] == "passed" and m["tranche"] == str(30 * GEN)
    assert m["verdict"] == "met" and m["confidence"] == 90 and m["quote"] == BODY and m["attempts"] == 1
    assert int(c["current_since"]) == chain.now
    solvency_check(chain)
    chain.tx(people["creator"], "claim_payout")
    assert chain.paid_to(people["creator"]) == 30 * GEN and chain.credit(people["creator"]) == 0
    assert chain.balance == 75 * GEN
    solvency_check(chain)


def test_full_campaign_pays_everything_and_returns_bond(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    for _ in range(3):
        pass_milestone(chain, people)
        solvency_check(chain)
    c = chain.view("get_campaign", 0)
    assert c["status"] == "completed" and c["bond"] == "0"
    assert chain.transfers == []
    assert chain.credit(people["creator"]) == 100 * GEN + 5 * GEN       # tranches and bond, credited
    chain.tx(people["creator"], "claim_payout")
    assert chain.paid_to(people["creator"]) == 100 * GEN + 5 * GEN
    assert chain.balance == 0
    chain.reverts(people["bob"], "claim_refund", 0, match="nothing to refund")
    chain.reverts(people["creator"], "submit_proof", 0, PROOF_URL, match="not active")


def test_odd_amounts_leave_no_dust(chain, people):
    launch(chain, people["creator"], goal=100, min_pledge=1, cap=1000, bond=5,
           milestones=plan(("first long description", 3333, T0 + 14 * DAY),
                           ("second long description", 3333, T0 + 30 * DAY),
                           ("third long description", 3334, T0 + 60 * DAY)))
    fund_and_activate(chain, people, pledges={"bob": 77, "carol": 34})       # raised = 111
    for _ in range(3):
        pass_milestone(chain, people)
    kinds = [e["kind"] for e in chain.view("list_credits", 0, 0, 10)]
    amounts = [int(e["amount"]) for e in chain.view("list_credits", 0, 0, 10)]
    assert kinds == ["tranche", "tranche", "tranche_and_bond"]
    assert amounts[0] == 111 * 3333 // 10000 and sum(amounts) == 111 + 5
    chain.tx(people["creator"], "claim_payout")                          # one claim collects every tranche
    assert [t[1] for t in chain.transfers] == [111 + 5]
    assert chain.balance == 0


def test_review_access_control_and_delay(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.reverts(people["creator"], "review", 0, match="no submitted proof")
    submit(chain, people, body=BODY)
    approve(chain)
    chain.reverts(people["bob"], "review", 0, match="review delay")
    chain.advance(HOUR - 1)
    chain.reverts(people["bob"], "review", 0, match="review delay")
    chain.advance(1)
    chain.tx(people["bob"], "review", 0)                                    # a backer may now trigger it
    assert chain.view("get_campaign", 0)["next_milestone"] == 1


def test_review_unknown_or_inactive_campaign(chain, people):
    chain.reverts(people["bob"], "review", 0, match="no campaign")
    launch(chain, people["creator"])
    chain.reverts(people["bob"], "review", 0, match="not active")


# ===========================================================================
# reviewing: every verdict path
# ===========================================================================

def test_low_confidence_approval_does_nothing(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    approve(chain, 69)
    run_review(chain, people)
    c, m = chain.view("get_campaign", 0), chain.view("get_milestone", 0, 0)
    assert c["released"] == "0" and c["strikes"] == 0 and m["state"] == "open" and m["verdict"] == "met"
    assert chain.transfers == [] and chain.credit(people["creator"]) == 0
    chain.reverts(people["creator"], "review", 0, match="no submitted proof")   # must resubmit


def test_ungrounded_quote_withholds_approval(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("met", 99, "A sentence that is nowhere on the page at all", "trust me")
    run_review(chain, people)
    m = chain.view("get_milestone", 0, 0)
    assert m["verdict"] == "unclear" and m["confidence"] == 49 and "quote was not found" in m["reason"]
    assert chain.view("get_campaign", 0)["released"] == "0" and chain.view("get_campaign", 0)["strikes"] == 0


def test_not_met_costs_a_strike_and_allows_resubmission(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 80, "", "Only a roadmap is shown.")
    run_review(chain, people)
    c, m = chain.view("get_campaign", 0), chain.view("get_milestone", 0, 0)
    assert c["strikes"] == 1 and c["status"] == "active" and m["state"] == "open"
    submit(chain, people, body=BODY)                                           # resubmit
    approve(chain)
    run_review(chain, people)
    c = chain.view("get_campaign", 0)
    assert c["strikes"] == 0 and c["next_milestone"] == 1                       # strikes reset on pass
    assert chain.view("get_milestone", 0, 0)["attempts"] == 2


def test_low_confidence_not_met_is_no_strike(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 64, "", "Probably not.")
    run_review(chain, people)
    assert chain.view("get_campaign", 0)["strikes"] == 0


def test_unclear_is_free(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("unclear", 95, "", "Cannot tell.")
    run_review(chain, people)
    assert chain.view("get_campaign", 0)["strikes"] == 0
    assert chain.view("get_milestone", 0, 0)["state"] == "open"


def test_missing_token_never_reaches_the_llm_and_costs_nothing(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.set_page(PROOF_URL, BODY + " but no token here")
    chain.tx(people["creator"], "submit_proof", 0, PROOF_URL)
    chain.set_llm("met", 100, BODY)
    run_review(chain, people)
    assert chain.llm_calls_made() == 0
    m = chain.view("get_milestone", 0, 0)
    assert m["verdict"] == "unclear" and "token" in m["reason"] and chain.view("get_campaign", 0)["strikes"] == 0


def test_token_of_another_milestone_is_not_accepted(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    other = chain.view("get_proof_token", 0, 1)
    chain.set_page(PROOF_URL, f"{BODY} {other}")
    chain.tx(people["creator"], "submit_proof", 0, PROOF_URL)
    chain.set_llm("met", 100, BODY)
    run_review(chain, people)
    assert chain.llm_calls_made() == 0 and chain.view("get_campaign", 0)["released"] == "0"


def test_empty_page_is_unclear(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.set_page(PROOF_URL, "  \n\t ")
    chain.tx(people["creator"], "submit_proof", 0, PROOF_URL)
    run_review(chain, people)
    assert chain.view("get_milestone", 0, 0)["verdict"] == "unclear"


def test_garbage_llm_answer_reverts_and_changes_nothing(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    before = chain.view("get_campaign", 0)
    chain.set_llm(raw="I think it is fine!")
    chain.reverts(people["creator"], "review", 0, match="[LLM_ERROR]")
    chain.set_llm(raw=json.dumps({"verdict": "maybe", "confidence": 5}))
    chain.reverts(people["creator"], "review", 0, match="[LLM_ERROR]")
    assert chain.view("get_campaign", 0) == before
    approve(chain)                                                              # a retry later works
    run_review(chain, people)
    assert chain.view("get_campaign", 0)["next_milestone"] == 1


def test_unreachable_page_reverts_as_transient(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.drop_page(PROOF_URL)
    before = chain.view("get_campaign", 0)
    chain.reverts(people["creator"], "review", 0, match="[TRANSIENT]")
    assert chain.view("get_campaign", 0) == before


def test_llm_returning_json_text_instead_of_object(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm(raw='Sure! {"verdict": "Met", "confidence": "92%", "quote": "' + BODY + '", "reason": "ok"}')
    run_review(chain, people)
    assert chain.view("get_campaign", 0)["next_milestone"] == 1


# ===========================================================================
# failing campaigns
# ===========================================================================

def strike_out(chain, people):
    for _ in range(2):
        submit(chain, people, body=BODY)
        chain.set_llm("not_met", 90, "", "Nothing is delivered.")
        run_review(chain, people)


def test_two_strikes_fail_the_campaign_and_slash_the_bond(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    strike_out(chain, people)
    c = chain.view("get_campaign", 0)
    assert c["status"] == "failed" and c["fail_reason"] == "strikes" and c["bond"] == "0"
    assert c["refund_pool"] == str(105 * GEN) and c["refund_weight"] == str(100 * GEN)
    assert chain.paid_to(people["creator"]) == 0 and chain.credit(people["creator"]) == 0
    solvency_check(chain)
    chain.tx(people["bob"], "claim_refund", 0)
    chain.tx(people["carol"], "claim_refund", 0)
    assert chain.transfers == []
    chain.claim_all(people)
    assert chain.paid_to(people["bob"]) == 63 * GEN and chain.paid_to(people["carol"]) == 42 * GEN
    assert chain.balance == 0


def test_max_strikes_is_respected(chain, people):
    launch(chain, people["creator"], max_strikes=1)
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 90)
    run_review(chain, people)
    assert chain.view("get_campaign", 0)["status"] == "failed"


def test_failure_after_partial_delivery_refunds_the_unreleased_part(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    pass_milestone(chain, people)                                   # 30 GEN released
    strike_out(chain, people)
    c = chain.view("get_campaign", 0)
    assert c["status"] == "failed"
    assert c["refund_pool"] == str(70 * GEN + 5 * GEN)              # unreleased + bond
    solvency_check(chain)
    chain.tx(people["carol"], "claim_refund", 0)
    chain.tx(people["bob"], "claim_refund", 0)
    chain.claim_all(people)
    assert chain.paid_to(people["bob"]) + chain.paid_to(people["carol"]) == 75 * GEN
    assert chain.paid_to(people["bob"]) == 45 * GEN
    assert chain.paid_to(people["creator"]) == 30 * GEN                 # the tranche earned before the failure
    assert chain.balance == 0
    chain.reverts(people["creator"], "submit_proof", 0, PROOF_URL, match="not active")


def test_declare_default_when_nothing_was_submitted(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.reverts(people["dave"], "declare_default", 0, match="not overdue")
    chain.set_time(T0 + 14 * DAY - 1)
    chain.reverts(people["dave"], "declare_default", 0, match="not overdue")
    chain.set_time(T0 + 14 * DAY)
    chain.tx(people["dave"], "declare_default", 0)
    c = chain.view("get_campaign", 0)
    assert c["status"] == "failed" and c["fail_reason"] == "deadline_missed"
    assert c["refund_pool"] == str(105 * GEN)
    chain.reverts(people["dave"], "declare_default", 0, match="not active")


def test_a_submitted_proof_gets_a_full_review_window_before_default(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.set_time(T0 + 14 * DAY - 10)
    submit(chain, people, body=BODY)
    chain.set_time(T0 + 14 * DAY + 1)
    chain.reverts(people["dave"], "declare_default", 0, match="review window")
    chain.reverts(people["bob"], "review", 0, match="review delay")
    chain.set_time(T0 + 14 * DAY - 10 + HOUR)
    chain.reverts(people["dave"], "declare_default", 0, match="review window")
    approve(chain)
    chain.tx(people["bob"], "review", 0)                           # a backer reviews it after the delay
    assert chain.view("get_campaign", 0)["next_milestone"] == 1
    chain.set_time(T0 + 14 * DAY - 10 + 3 * DAY)
    chain.reverts(people["dave"], "declare_default", 0, match="not overdue")  # milestone 2 is far away


def test_default_is_possible_after_the_review_window_if_nobody_reviewed(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    chain.set_time(T0 + 14 * DAY - 10)
    submit(chain, people, body=BODY)
    chain.set_time(T0 + 14 * DAY - 10 + 3 * DAY)
    chain.tx(people["dave"], "declare_default", 0)
    assert chain.view("get_campaign", 0)["status"] == "failed"


def test_late_close_funding_does_not_ambush_the_creator(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=100 * GEN)
    chain.set_time(T0 + 14 * DAY + 5)                              # nobody closed funding for a week
    chain.tx(people["dave"], "close_funding", 0)
    chain.reverts(people["dave"], "declare_default", 0, match="not overdue")
    submit(chain, people, body=BODY)                                # creator still has time to deliver
    chain.set_time(T0 + 14 * DAY + 5 + 3 * DAY)
    chain.set_llm("met", 90, BODY)
    chain.tx(people["creator"], "review", 0)


def test_next_milestone_gets_a_minimum_working_window(chain, people):
    launch(chain, people["creator"],
           milestones=plan(("first long description here", 5000, T0 + 8 * DAY),
                           ("second long description here", 5000, T0 + 9 * DAY)))
    fund_and_activate(chain, people)
    chain.set_time(T0 + 8 * DAY - 5)
    pass_milestone(chain, people)
    chain.set_time(T0 + 9 * DAY + 1)                               # past its own due date...
    chain.reverts(people["dave"], "declare_default", 0, match="not overdue")   # ...but inside the grace window
    chain.set_time(T0 + 8 * DAY - 5 + 3 * DAY)
    chain.tx(people["dave"], "declare_default", 0)


# ===========================================================================
# refunds with many backers
# ===========================================================================

def test_pro_rata_refunds_with_awkward_numbers(chain, people):
    launch(chain, people["creator"], goal=10, min_pledge=1, cap=1000, bond=1,
           milestones=plan(("first long description here", 10000, T0 + 14 * DAY)))
    pledges = {"bob": 3, "carol": 3, "dave": 3, "erin": 1}
    fund_and_activate(chain, people, pledges=pledges)
    chain.set_time(T0 + 14 * DAY)
    chain.tx(people["frank"], "declare_default", 0)
    assert chain.view("get_campaign", 0)["refund_pool"] == "11"
    order = ["erin", "dave", "bob", "carol"]
    preview = {n: int(chain.view("get_position", 0, str(people[n]))["refundable_now"]) for n in order}
    for name in order:
        chain.tx(people[name], "claim_refund", 0)
    assert sum(chain.credit(people[n]) for n in order) == 11
    assert preview["erin"] == chain.credit(people["erin"])             # first claimant matches its preview
    chain.claim_all(people, order)
    assert sum(chain.paid_to(people[n]) for n in order) == 11
    assert chain.balance == 0
    assert preview["erin"] == chain.paid_to(people["erin"])


def test_fuzz_money_is_conserved_and_the_vault_is_always_solvent(chain, people, direct_vm):
    from gltest.direct.loader import create_address
    rng = random.Random(2026)
    funders = [create_address(f"funder{i}") for i in range(15)]
    goal = rng.randint(50, 10**6)
    launch(chain, people["creator"], goal=goal, cap=goal * 3, min_pledge=1, max_strikes=2,
           bond=chain.view("required_bond", goal),
           milestones=plan(("first long description here", 2500, T0 + 14 * DAY),
                           ("second long description here", 2500, T0 + 30 * DAY),
                           ("third long description here", 5000, T0 + 60 * DAY)))
    total_in = int(chain.view("get_campaign", 0)["bond"])
    pledged = []
    for funder in funders:
        room = goal * 3 - int(chain.view("get_campaign", 0)["raised"])
        if room < 1:
            break
        amount = rng.randint(1, min(goal, room))
        chain.tx(funder, "back", 0, value=amount)
        pledged.append(funder)
        total_in += amount
        solvency_check(chain)
    raised = int(chain.view("get_campaign", 0)["raised"])
    chain.set_time(T0 + 7 * DAY)
    chain.tx(people["dave"], "close_funding", 0)
    solvency_check(chain)
    pass_milestone(chain, people)
    solvency_check(chain)
    strike_out(chain, people)
    solvency_check(chain)
    for funder in rng.sample(pledged, len(pledged)):
        chain.tx(funder, "claim_refund", 0)
        solvency_check(chain)
    for funder in rng.sample(pledged, len(pledged)):
        if chain.credit(funder) > 0:                                # a tiny pledge can round to a zero share
            chain.claim(funder)
        else:
            chain.reverts(funder, "claim_payout", match="nothing to claim")
        solvency_check(chain)
    chain.claim(people["creator"])
    solvency_check(chain)
    assert chain.balance == 0
    paid = sum(chain.received.values())
    assert paid == total_in
    assert chain.paid_to(people["creator"]) == raised * 2500 // 10000


# ===========================================================================
# validator behaviour (what the other nodes do)
# ===========================================================================

def _review_and_capture(chain, people, **llm):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm(**llm) if llm else approve(chain, 90)
    chain.vm.clear_validators()
    run_review(chain, people)


def test_validator_agrees_with_an_equivalent_verdict(chain, people):
    _review_and_capture(chain, people)
    chain.set_llm("met", 80, BODY, "Different wording, same decision.")
    assert chain.vm.run_validator() is True


def test_validator_rejects_a_different_decision(chain, people):
    _review_and_capture(chain, people)
    chain.set_llm("not_met", 90, "", "Disagree.")
    assert chain.vm.run_validator() is False
    chain.set_llm("met", 60, BODY)                                        # would not release
    assert chain.vm.run_validator() is False
    chain.set_llm("met", 40, BODY)
    assert chain.vm.run_validator() is False


def test_validator_rejects_wildly_different_confidence(chain, people):
    _review_and_capture(chain, people, verdict="met", confidence=99, quote=BODY)
    chain.set_llm("met", 72, BODY)
    assert chain.vm.run_validator() is False


def test_validator_rechecks_the_page_itself(chain, people):
    _review_and_capture(chain, people)
    chain.set_page(PROOF_URL, "The page changed and no longer carries the token.")
    assert chain.vm.run_validator() is False                              # sees "unclear", leader saw "release"
    token = chain.view("get_proof_token", 0, 0)
    chain.set_page(PROOF_URL, f"Different text entirely {token}")
    chain.set_llm("met", 90, BODY)                                        # quote not on this page
    assert chain.vm.run_validator() is False


def test_validator_error_handling(chain, people):
    _review_and_capture(chain, people)
    assert chain.vm.run_validator(leader_error=Exception("[TRANSIENT] the proof page could not be loaded right now")) is False
    chain.drop_page(PROOF_URL)
    assert chain.vm.run_validator(leader_error=Exception("[TRANSIENT] the proof page could not be loaded right now")) is True
    assert chain.vm.run_validator(leader_error=Exception("[LLM_ERROR] the model returned no usable verdict")) is False
    assert chain.vm.run_validator(leader_error=Exception("[EXPECTED] x")) is False
    assert chain.vm.run_validator() is False                               # leader ok, validator cannot load the page


def test_nondet_closures_capture_only_plain_values(chain, people):
    """A non-deterministic block must never hold storage-backed objects."""
    _review_and_capture(chain, people)
    _, leader_fn, validator_fn = chain.vm._captured_validators[-1]
    for fn in (leader_fn, validator_fn):
        for cell in fn.__closure__ or ():
            value = cell.cell_contents
            assert isinstance(value, (str, int)) or callable(value), type(value)


# ===========================================================================
# views
# ===========================================================================

def test_get_position_rejects_a_bad_address(chain, people):
    launch(chain, people["creator"])
    with pytest.raises(Exception) as info:
        chain.view("get_position", 0, "not-an-address")
    assert "0x-prefixed" in str(info.value)
    assert chain.view("get_position", 0, str(people["bob"])) == {"pledged": "0", "refundable_now": "0"}
    with pytest.raises(Exception):
        chain.view("get_campaign", 5)
    with pytest.raises(Exception):
        chain.view("get_milestone", 0, 3)
