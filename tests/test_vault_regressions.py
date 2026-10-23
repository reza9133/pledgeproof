"""Regression tests: one section per bug found (and fixed) during the debug loop.

Every test here failed against the first version of the contract.
"""
import json

import pytest

from conftest import (
    DAY, GEN, HOUR, PROOF_URL, T0, fund_and_activate, launch, page_with_token, plan, solvency_check, submit,
)

BODY = "The alpha build is live and the changelog is published."
GRACE = 3 * DAY


def approve(chain, confidence=90):
    chain.set_llm("met", confidence, BODY, "The page shows the alpha and the changelog.")


def activate(chain, people, **kwargs):
    launch(chain, people["creator"], **kwargs)
    fund_and_activate(chain, people)
    return chain.view("get_campaign", 0)


# ===========================================================================
# BUG 1: a verdict that arrives after the due date used to leave the creator
# no way to fix the proof, and anyone could default the campaign at once.
# ===========================================================================

@pytest.mark.parametrize("verdict, confidence", [("unclear", 40), ("unclear", 0), ("met", 60), ("not_met", 50)])
def test_nothing_verdict_near_the_deadline_gives_the_creator_time_to_resubmit(chain, people, verdict, confidence):
    c = activate(chain, people)
    due = int(c["milestones"][0]["due"])
    chain.set_time(due - 600)
    submit(chain, people, body=BODY)
    chain.set_time(due - 600 + HOUR)                          # a bystander may review now, after the due date
    chain.set_llm(verdict, confidence, BODY if verdict == "met" else "", "not sure")
    chain.tx(people["erin"], "review", 0)

    after = chain.view("get_campaign", 0)
    assert after["status"] == "active" and after["strikes"] == 0
    assert int(after["cure_until"]) == chain.now + GRACE
    chain.reverts(people["mallory"], "declare_default", 0, match="not overdue yet")

    submit(chain, people, body=BODY)                          # the creator fixes the page and resubmits
    approve(chain)
    chain.tx(people["creator"], "review", 0)
    assert chain.view("get_milestone", 0, 0)["state"] == "passed"
    solvency_check(chain)


def test_a_strike_near_the_deadline_also_gets_a_cure_window(chain, people):
    c = activate(chain, people, max_strikes=3)
    due = int(c["milestones"][0]["due"])
    chain.set_time(due - 60)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 95, "", "The page is only a plan.")
    chain.tx(people["creator"], "review", 0)
    after = chain.view("get_campaign", 0)
    assert after["strikes"] == 1 and int(after["cure_until"]) == chain.now + GRACE
    chain.set_time(due + DAY)
    chain.reverts(people["mallory"], "declare_default", 0, match="not overdue yet")
    chain.tx(people["creator"], "submit_proof", 0, PROOF_URL)             # still allowed after the due date


def test_a_strike_that_ends_the_campaign_grants_nothing(chain, people):
    c = activate(chain, people, max_strikes=1)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 95, "", "No.")
    chain.tx(people["creator"], "review", 0)
    after = chain.view("get_campaign", 0)
    assert after["status"] == "failed" and after["fail_reason"] == "strikes" and after["cure_until"] == "0"


def test_the_cure_window_is_limited_so_a_creator_cannot_stall_forever(chain, people):
    launch(chain, people["bob"], title="Second Campaign")
    chain.tx(people["carol"], "back", 0, value=100 * GEN)
    chain.set_time(int(chain.view("get_campaign", 0)["funding_deadline"]))
    chain.tx(people["dave"], "close_funding", 0)
    due = int(chain.view("get_campaign", 0)["milestones"][0]["due"])
    chain.set_time(due - 60)
    chain.set_llm("unclear", 30, "", "vague")
    cures = []
    for _ in range(4):
        text, _ = page_with_token(chain, 0, 0, BODY)
        chain.set_page(PROOF_URL, text)
        chain.tx(people["bob"], "submit_proof", 0, PROOF_URL)
        chain.tx(people["bob"], "review", 0)
        cures.append(int(chain.view("get_campaign", 0)["cure_until"]))
        chain.advance(GRACE - HOUR)                                    # use almost the whole window each time
    assert cures[0] < cures[1] < cures[2]                              # the first three reviews extend it
    assert cures[2] == cures[3]                                        # the fourth does not
    chain.set_time(cures[3])                                           # the last extension has run out
    chain.reverts(people["bob"], "submit_proof", 0, PROOF_URL, match="deadline")
    chain.tx(people["mallory"], "declare_default", 0)
    assert chain.view("get_campaign", 0)["status"] == "failed"


def test_cure_is_cleared_when_the_milestone_is_paid(chain, people):
    c = activate(chain, people)
    due = int(c["milestones"][0]["due"])
    chain.set_time(due - 60)
    submit(chain, people, body=BODY)
    chain.set_llm("unclear", 10, "", "hmm")
    chain.tx(people["creator"], "review", 0)
    assert chain.view("get_campaign", 0)["cure_until"] != "0"
    submit(chain, people, body=BODY)
    approve(chain)
    chain.tx(people["creator"], "review", 0)
    after = chain.view("get_campaign", 0)
    assert after["cure_until"] == "0" and after["next_milestone"] == 1


def test_cure_extends_only_the_current_milestone(chain, people):
    c = activate(chain, people)
    chain.set_time(int(c["milestones"][0]["due"]) - 60)
    submit(chain, people, body=BODY)
    chain.set_llm("unclear", 10, "", "hmm")
    chain.tx(people["creator"], "review", 0)
    submit(chain, people, body=BODY)
    approve(chain)
    chain.tx(people["creator"], "review", 0)                          # milestone 1 paid, cure cleared
    due2 = int(chain.view("get_campaign", 0)["milestones"][1]["due"])
    chain.set_time(due2 + GRACE + 1)
    chain.tx(people["mallory"], "declare_default", 0)                 # milestone 2 gets no leftover extension
    assert chain.view("get_campaign", 0)["status"] == "failed"


def test_an_honest_creator_who_never_got_a_chance_is_not_slashed_by_a_late_review(chain, people):
    """The exact attack: submit in time, let a bystander review once the window is over."""
    c = activate(chain, people)
    due = int(c["milestones"][0]["due"])
    chain.set_time(due - 1)
    submit(chain, people, body=BODY)
    chain.set_time(due + HOUR)
    chain.set_llm("unclear", 20, "", "cannot tell")
    chain.tx(people["mallory"], "review", 0)                           # hostile bystander triggers the verdict
    chain.reverts(people["mallory"], "declare_default", 0, match="not overdue yet")
    assert chain.view("get_campaign", 0)["bond"] == str(5 * GEN)


# ===========================================================================
# BUG 2: the creator could cancel a campaign that had already been funded
# ===========================================================================

def test_creator_cannot_cancel_after_the_funding_deadline(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=60 * GEN)
    chain.tx(people["carol"], "back", 0, value=40 * GEN)
    chain.set_time(T0 + 7 * DAY)                                       # exactly the deadline
    chain.reverts(people["creator"], "cancel_campaign", 0, match="funding is over")
    chain.tx(people["dave"], "close_funding", 0)
    assert chain.view("get_campaign", 0)["status"] == "active"


def test_creator_cannot_cancel_once_the_cap_is_reached(chain, people):
    launch(chain, people["creator"], goal=100 * GEN, cap=100 * GEN)
    chain.tx(people["bob"], "back", 0, value=100 * GEN)
    chain.reverts(people["creator"], "cancel_campaign", 0, match="funding is over")
    chain.tx(people["dave"], "close_funding", 0)
    assert chain.view("get_campaign", 0)["status"] == "active"


def test_creator_can_still_cancel_while_the_window_is_open_even_with_the_goal_met(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=100 * GEN)
    chain.set_time(T0 + 7 * DAY - 1)
    chain.tx(people["creator"], "cancel_campaign", 0)
    assert chain.view("get_campaign", 0)["status"] == "cancelled"
    chain.tx(people["bob"], "claim_refund", 0)
    assert chain.paid_to(people["bob"]) == 100 * GEN and chain.balance == 0


def test_goal_missed_campaign_cannot_be_cancelled_after_the_deadline_but_still_refunds(chain, people):
    launch(chain, people["creator"])
    chain.tx(people["bob"], "back", 0, value=10 * GEN)
    chain.set_time(T0 + 8 * DAY)
    chain.reverts(people["creator"], "cancel_campaign", 0, match="funding is over")
    chain.tx(people["dave"], "close_funding", 0)
    assert chain.paid_to(people["creator"]) == 5 * GEN                 # bond back, as for any missed goal
    chain.tx(people["bob"], "claim_refund", 0)
    assert chain.balance == 0


# ===========================================================================
# BUG 3: views that raised a raw ValueError instead of a clear error
# ===========================================================================

@pytest.mark.parametrize("goal", [0])
def test_required_bond_of_nothing_is_a_clean_error(chain, people, goal):
    with pytest.raises(Exception) as info:
        chain.view("required_bond", goal)
    assert "[EXPECTED]" in str(info.value) and "goal must be positive" in str(info.value)


# ===========================================================================
# BUG 4: proof URLs that a parser could read differently
# ===========================================================================

@pytest.mark.parametrize("url", [
    "https://localhost\\.example.com/x", "https://127.0.0.1\\.example.com/x", "https://1.0x7f/",
    "https://0x7f.0x1/", "https://example.com:0/", "https://münchen.de/x", "https://a_b.example.com/",
    "https://example.com/\u202e", "https://example.c/", "https://example.123/",
])
def test_submit_proof_refuses_urls_a_parser_could_misread(chain, people, url):
    activate(chain, people)
    chain.reverts(people["creator"], "submit_proof", 0, url, match="[EXPECTED]")
    assert chain.view("get_milestone", 0, 0)["state"] == "open"


# ===========================================================================
# BUG 5: tiny quote fragments joined by "..." matched almost any page
# ===========================================================================

def test_a_quote_made_of_tiny_fragments_does_not_release_money(chain, people):
    activate(chain, people)
    page_body = "the quick brown fox jumps over the lazy dog and then the cat sat on the mat"
    submit(chain, people, body=page_body)
    chain.set_llm("met", 95, "the ... the ... the ... the", "Looks delivered.")
    chain.tx(people["creator"], "review", 0)
    m = chain.view("get_milestone", 0, 0)
    assert m["state"] == "open" and m["verdict"] == "unclear" and m["tranche"] == "0"
    assert chain.paid_to(people["creator"]) == 0


# ===========================================================================
# BUG 6: parser crashes and type confusion in launch input
# ===========================================================================

@pytest.mark.parametrize("bad_plan", [
    "[" * 50_000 + "]" * 50_000,
    json.dumps([{"description": {"k": "v" * 30}, "bps": 10000, "due": T0 + 20 * DAY}]),
    json.dumps([{"description": 12345678901234567890, "bps": 10000, "due": T0 + 20 * DAY}]),
    " " * 20_000 + json.dumps([{"description": "x" * 20, "bps": 10000, "due": T0 + 20 * DAY}]),
])
def test_launch_rejects_crashing_or_confusing_plans_cleanly(chain, people, bad_plan):
    chain.reverts(people["creator"], "launch_campaign", "Open Telescope Kit", "A pitch that is long enough.",
                  100 * GEN, 200 * GEN, GEN, T0 + 7 * DAY, 2, bad_plan, value=5 * GEN, match="[EXPECTED]")
    assert chain.view("campaign_count") == 0


def test_a_garbage_model_answer_with_a_recursion_bomb_reverts_cleanly(chain, people):
    activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm(raw='{"verdict": "met", "confidence": 90, "x": ' + "[" * 20_000 + "]" * 20_000 + "}")
    chain.reverts(people["creator"], "review", 0, match="[LLM_ERROR]")
    assert chain.view("get_milestone", 0, 0)["state"] == "pending"


# ===========================================================================
# BUG 7: text that looks different from what machines read
# ===========================================================================

@pytest.mark.parametrize("field", ["title", "pitch"])
def test_launch_rejects_bidirectional_and_control_characters(chain, people, field):
    for bad in ("\u202e", "\u2066", "\x00", "\x1b", "\u200f"):
        kwargs = {field: ("Open Telescope " if field == "title" else "A pitch that is long enough ") + bad + "Kit"}
        with pytest.raises(Exception) as info:
            launch(chain, people["creator"], **kwargs)
        assert "control or bidirectional" in str(info.value)
    assert chain.view("campaign_count") == 0


def test_launch_rejects_a_hidden_override_inside_a_milestone(chain, people):
    steps = (("Ship the audit \u202eeulav ytiruces\u202c report", 10000, T0 + 20 * DAY),)
    with pytest.raises(Exception) as info:
        launch(chain, people["creator"], milestones=plan(*steps))
    assert "control or bidirectional" in str(info.value)


def test_zero_width_characters_are_still_silently_removed(chain, people):
    launch(chain, people["creator"], title="Open\u200b Telescope\u2060 Kit")
    assert chain.view("get_campaign", 0)["title"] == "Open Telescope Kit"


# ===========================================================================
# BUG 8: a validator trusted whatever shape the leader returned and never
# re-checked the quote that would be shown to backers
# ===========================================================================

def _leader_review(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    approve(chain)
    chain.vm.clear_validators()
    chain.tx(people["creator"], "review", 0)


GOOD = {"verdict": "met", "confidence": 90, "quote": BODY, "reason": "fine"}


def test_validator_accepts_a_wellformed_equivalent_leader_answer(chain, people):
    _leader_review(chain, people)
    assert chain.vm.run_validator(leader_result=dict(GOOD)) is True
    assert chain.vm.run_validator(leader_result={**GOOD, "confidence": 75}) is True


@pytest.mark.parametrize("bad", [
    None, "met", [], 5, {},
    {"verdict": "met"},
    {**GOOD, "extra": 1},
    {**GOOD, "verdict": "approved"},
    {**GOOD, "confidence": 300},
    {**GOOD, "confidence": -5},
    {**GOOD, "confidence": "90"},
    {**GOOD, "confidence": 90.5},
    {**GOOD, "confidence": 10**30},
    {**GOOD, "quote": ["x"]},
    {**GOOD, "reason": None},
    {**GOOD, "reason": "r" * 5000},
    {**GOOD, "quote": BODY + "\u202e"},
])
def test_validator_rejects_a_malformed_leader_answer(chain, people, bad):
    _leader_review(chain, people)
    assert chain.vm.run_validator(leader_result=bad) is False


def test_validator_rejects_a_leader_quote_that_is_not_on_the_page(chain, people):
    _leader_review(chain, people)
    forged = {**GOOD, "quote": "The creator also cured three diseases and shipped version two."}
    assert chain.vm.run_validator(leader_result=forged) is False


def test_validator_rejects_a_leader_quote_made_of_tiny_fragments(chain, people):
    _leader_review(chain, people)
    forged = {**GOOD, "quote": "the ... the ... the ... the"}
    assert chain.vm.run_validator(leader_result=forged) is False


def test_validator_does_not_need_a_quote_when_the_leader_did_not_approve(chain, people):
    launch(chain, people["creator"])
    fund_and_activate(chain, people)
    submit(chain, people, body=BODY)
    chain.set_llm("not_met", 90, "", "The page is only a plan.")
    chain.vm.clear_validators()
    chain.tx(people["creator"], "review", 0)
    assert chain.vm.run_validator(leader_result={"verdict": "not_met", "confidence": 85, "quote": "",
                                                 "reason": "Only a plan."}) is True


# ===========================================================================
# the stored views stay consistent with the new field
# ===========================================================================

def test_get_campaign_reports_cure_until(chain, people):
    launch(chain, people["creator"])
    assert chain.view("get_campaign", 0)["cure_until"] == "0"
