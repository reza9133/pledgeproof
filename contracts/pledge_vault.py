# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
PledgeVault
===========

Milestone crowdfunding where the money is released by GenLayer consensus,
not by the creator's say-so.

Lifecycle
---------
1. ``launch_campaign``  -- a creator publishes a pitch, a funding goal and a
   plan of up to six milestones (each with acceptance criteria, a share of
   the money and a due date) and locks a **creator bond** (at least 5% of
   the goal) in the same call.
2. ``back`` / ``withdraw_pledge`` -- while funding is open, anyone except the
   creator pledges GEN. Pledges can be withdrawn until the deadline.
3. ``close_funding``   -- once the deadline passes (or the cap is reached),
   anyone closes funding. Goal met: the campaign goes ``active``. Goal
   missed: backers are refunded in full and the bond returns to the creator.
4. ``submit_proof``    -- for the current milestone the creator points at a
   public https page that shows the work, and puts the milestone's **proof
   token** (see ``get_proof_token``) on that page.
5. ``review``          -- validators render the page, check the token, and
   independently judge whether it demonstrates the milestone. Approved:
   that milestone's tranche is paid to the creator. Rejected: the creator
   takes a strike. Unclear: nothing happens and the creator may resubmit.
6. The last approved milestone completes the campaign and the bond is
   returned to the creator.

When it goes wrong
------------------
Too many strikes, or a missed deadline (``declare_default``), fail the
campaign. Whatever has not been paid out, **plus the creator's bond**, goes
back to the backers in proportion to what they pledged, and every backer
pulls their own share with ``claim_refund``.

Design notes
------------
* Pull payments for refunds: no loop over backers, so nobody can block
  anybody else, and the number of backers is unbounded.
* Refund shares use a running pool/weight pair so the payouts add up to the
  pool exactly -- no dust is ever stranded.
* A review never changes state on a transient failure (page unreachable);
  it reverts, and anyone can simply try again later.
* A strike requires a confident "not_met"; an approval requires a confident
  "met" backed by a quote that really appears on the page. Everything else
  is "unclear", which costs the creator nothing and pays nothing.
* A review that pays nothing (unclear, or a strike that does not end the
  campaign) extends the creator's deadline by a grace window, up to
  ``MAX_CURED_REVIEWS`` times per milestone, so a verdict that arrives late
  can always be answered.
* Time comes from the transaction's own timestamp, so every validator
  agrees on it.
* Outgoing payments are fire-and-forget messages: the contract cannot see
  whether one was delivered. Every payment is therefore also written to a
  **payout ledger** and stays there until the contract's own balance proves
  that the money left (``reconcile_payouts``). A payment that never lands can
  be sent again (``retry_payout``) once a patience window has passed and only
  while nothing at all has landed, so a duplicate can never be paid out of
  other people's money. Nothing is lost: the beneficiary's entitlement is
  recorded in ``payouts`` even though the campaign books were already cleared.
"""

from genlayer import *

from dataclasses import dataclass

from pledgeproof import ProofJudge, ERROR_EXPECTED, ERROR_EXTERNAL
from pledgeproof_pure import (
    MAX_CURED_REVIEWS,
    MAX_RECONCILE_BATCH,
    PAYOUT_ALL_LANDED,
    MAX_FUNDING_WINDOW_SECONDS,
    MIN_FUNDING_WINDOW_SECONDS,
    REVIEW_DELAY_SECONDS,
    REVIEW_GRACE_SECONDS,
    DECISION_RELEASE,
    DECISION_STRIKE,
    PlanError,
    decide,
    has_hidden_chars,
    is_safe_proof_url,
    may_resend,
    min_bond,
    normalize_text,
    parse_iso_timestamp,
    parse_milestones,
    payout_state,
    proof_token,
    refund_share,
    tranche_amounts,
)

_ZERO_ADDRESS = Address("0x0000000000000000000000000000000000000000")

# Campaign statuses
_FUNDING = "funding"
_ACTIVE = "active"
_COMPLETED = "completed"
_FAILED = "failed"
_CANCELLED = "cancelled"

# Milestone states
_OPEN = "open"          # waiting for the creator to submit (or resubmit) proof
_PENDING = "pending"    # proof submitted, waiting for review
_PASSED = "passed"      # approved and paid

# Outgoing payments go to ordinary wallets (EOAs). GenLayer distinguishes two
# kinds of message: ``gl.get_contract_at(addr).emit_transfer`` is an *internal*
# message to another Intelligent Contract, while a wallet lives on the chain
# layer and is paid by an *external* message through the vault's ghost
# contract. That is what an EVM contract interface produces, even though the
# recipient is not a contract. External messages always run on finalization.
@gl.evm.contract_interface
class _Wallet:
    class View:
        pass

    class Write:
        pass


# Payout states
_SENT = "sent"          # transfer emitted, not yet proven to have left the contract
_SETTLED = "settled"    # the contract's balance proved the money left


@allow_storage
@dataclass
class Campaign:
    creator: Address
    title: str
    pitch: str
    goal: u256                  # minimum raise for the campaign to go active
    cap: u256                   # maximum raise accepted
    min_pledge: u256            # smallest single contribution
    funding_deadline: u256      # unix seconds
    max_strikes: u8             # strikes on one milestone before the campaign fails
    milestone_count: u8
    status: str                 # funding | active | completed | failed | cancelled
    raised: u256                # total currently pledged
    released: u256              # total paid out to the creator as tranches
    bond: u256                  # creator bond still held by the contract
    backer_count: u32
    next_milestone: u8          # index of the milestone currently being worked on
    strikes: u8                 # strikes taken on the current milestone
    current_since: u256         # when the current milestone became current
    cure_until: u256            # deadline extension earned by a review that did not pay out
    fail_reason: str            # "" | goal_not_met | strikes | deadline_missed | cancelled
    refund_pool: u256           # GEN still owed to backers after a failure
    refund_weight: u256         # pledges not yet refunded (denominator of the pro-rata share)


@allow_storage
@dataclass
class Milestone:
    description: str
    bps: u32                    # share of the raised amount, in basis points
    due: u256                   # unix seconds
    state: str                  # open | pending | passed
    proof_url: str
    submitted_at: u256
    tranche: u256               # amount released (0 until passed)
    verdict: str                # last verdict: "" | met | not_met | unclear
    confidence: u8
    quote: str
    reason: str
    reviewed_at: u256
    attempts: u32               # number of completed reviews


@allow_storage
@dataclass
class Payout:
    to: Address
    amount: u256
    campaign_id: u256
    kind: str                   # pledge_withdrawn | refund | bond_returned | tranche | tranche_and_bond
    state: str                  # sent | settled
    created_at: u256
    last_sent_at: u256
    attempts: u32               # times the transfer was emitted


class PledgeVault(gl.Contract):
    campaigns: TreeMap[u256, Campaign]
    milestones: TreeMap[u256, Milestone]       # key = campaign_id * 8 + index
    pledges: TreeMap[str, u256]                # key = "<campaign_id>:<backer address>"
    next_id: u256
    payouts: TreeMap[u256, Payout]             # every outgoing payment, until the balance proves it left
    next_payout: u256
    payout_cursor: u256                        # every payout below this id is settled
    held: u256                                 # received and not yet proven paid out
    inflight_total: u256                       # sum of the payouts that are not settled

    def __init__(self):
        self.next_id = u256(0)
        self.next_payout = u256(0)
        self.payout_cursor = u256(0)
        self.held = u256(0)
        self.inflight_total = u256(0)

    # ------------------------------------------------------------------
    # Creating and funding
    # ------------------------------------------------------------------

    @gl.public.write.payable
    def launch_campaign(
        self,
        title: str,
        pitch: str,
        goal: u256,
        cap: u256,
        min_pledge: u256,
        funding_deadline: u256,
        max_strikes: u8,
        milestones_json: str,
    ) -> u256:
        now = self._now()
        bond = int(gl.message.value)
        self.held = u256(int(self.held) + bond)
        if has_hidden_chars(title) or has_hidden_chars(pitch):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} title and pitch must not contain control or bidirectional characters")
        title = normalize_text(title)
        pitch = normalize_text(pitch)
        goal_i = int(goal)
        cap_i = int(cap)
        min_pledge_i = int(min_pledge)
        funding_deadline_i = int(funding_deadline)
        max_strikes_i = int(max_strikes)

        if not (3 <= len(title) <= 80):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} title must be 3-80 characters")
        if not (10 <= len(pitch) <= 1000):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} pitch must be 10-1000 characters")
        if goal_i < 1:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} goal must be positive")
        if cap_i < goal_i:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} cap must be at least the goal")
        if not (1 <= min_pledge_i <= goal_i):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} min_pledge must be between 1 and the goal")
        if not (1 <= max_strikes_i <= 3):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} max_strikes must be between 1 and 3")
        if funding_deadline_i < now + MIN_FUNDING_WINDOW_SECONDS:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} funding must stay open for at least one hour")
        if funding_deadline_i > now + MAX_FUNDING_WINDOW_SECONDS:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} funding may stay open for at most 90 days")
        required_bond = min_bond(goal_i)
        if bond < required_bond:
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} the creator bond must be at least {required_bond} wei (5% of the goal)"
            )
        try:
            plan = parse_milestones(milestones_json, funding_deadline_i)
        except PlanError as exc:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} invalid milestone plan: {exc}")

        campaign_id = int(self.next_id)
        self.next_id = u256(campaign_id + 1)
        self.campaigns[u256(campaign_id)] = Campaign(
            creator=gl.message.sender_address,
            title=title,
            pitch=pitch,
            goal=u256(goal_i),
            cap=u256(cap_i),
            min_pledge=u256(min_pledge_i),
            funding_deadline=u256(funding_deadline_i),
            max_strikes=u8(max_strikes_i),
            milestone_count=u8(len(plan)),
            status=_FUNDING,
            raised=u256(0),
            released=u256(0),
            bond=u256(bond),
            backer_count=u32(0),
            next_milestone=u8(0),
            strikes=u8(0),
            current_since=u256(0),
            cure_until=u256(0),
            fail_reason="",
            refund_pool=u256(0),
            refund_weight=u256(0),
        )
        for index, step in enumerate(plan):
            self.milestones[self._mkey(campaign_id, index)] = Milestone(
                description=step["description"],
                bps=u32(step["bps"]),
                due=u256(step["due"]),
                state=_OPEN,
                proof_url="",
                submitted_at=u256(0),
                tranche=u256(0),
                verdict="",
                confidence=u8(0),
                quote="",
                reason="",
                reviewed_at=u256(0),
                attempts=u32(0),
            )
        return u256(campaign_id)

    @gl.public.write.payable
    def back(self, campaign_id: u256) -> None:
        campaign = self._campaign(campaign_id)
        now = self._now()
        if campaign.status != _FUNDING:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this campaign is not accepting pledges")
        if now >= int(campaign.funding_deadline):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the funding window has closed")
        backer = gl.message.sender_address
        if backer == campaign.creator:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} creators cannot back their own campaign")
        value = int(gl.message.value)
        self.held = u256(int(self.held) + value)
        if value < int(campaign.min_pledge):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the pledge is below the campaign minimum")
        if int(campaign.raised) + value > int(campaign.cap):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the pledge would exceed the funding cap")

        key = self._pkey(int(campaign_id), backer)
        previous = int(self.pledges[key]) if key in self.pledges else 0
        self.pledges[key] = u256(previous + value)
        if previous == 0:
            campaign.backer_count = u32(int(campaign.backer_count) + 1)
        campaign.raised = u256(int(campaign.raised) + value)

    @gl.public.write
    def withdraw_pledge(self, campaign_id: u256) -> None:
        campaign = self._campaign(campaign_id)
        now = self._now()
        if campaign.status != _FUNDING or now >= int(campaign.funding_deadline):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} pledges can only be withdrawn while funding is open")
        backer = gl.message.sender_address
        key = self._pkey(int(campaign_id), backer)
        pledge = int(self.pledges[key]) if key in self.pledges else 0
        if pledge == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} you have no pledge on this campaign")

        self.pledges[key] = u256(0)
        campaign.raised = u256(int(campaign.raised) - pledge)
        campaign.backer_count = u32(int(campaign.backer_count) - 1)
        self._send(backer, pledge, int(campaign_id), "pledge_withdrawn")

    @gl.public.write
    def cancel_campaign(self, campaign_id: u256) -> None:
        campaign = self._campaign(campaign_id)
        if gl.message.sender_address != campaign.creator:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the creator can cancel this campaign")
        if campaign.status != _FUNDING:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only a campaign that is still funding can be cancelled")
        if self._now() >= int(campaign.funding_deadline) or int(campaign.raised) >= int(campaign.cap):
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} funding is over: a campaign can only be cancelled while its funding window is open"
            )
        self._end_without_fault(int(campaign_id), campaign, _CANCELLED, "cancelled")

    @gl.public.write
    def close_funding(self, campaign_id: u256) -> None:
        campaign = self._campaign(campaign_id)
        now = self._now()
        if campaign.status != _FUNDING:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} funding is already closed")
        capped = int(campaign.raised) >= int(campaign.cap)
        if now < int(campaign.funding_deadline) and not capped:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the funding window is still open")

        if int(campaign.raised) >= int(campaign.goal):
            campaign.status = _ACTIVE
            campaign.current_since = u256(now)
        else:
            self._end_without_fault(int(campaign_id), campaign, _FAILED, "goal_not_met")

    # ------------------------------------------------------------------
    # Delivering and judging
    # ------------------------------------------------------------------

    @gl.public.write
    def submit_proof(self, campaign_id: u256, url: str) -> None:
        campaign = self._campaign(campaign_id)
        if gl.message.sender_address != campaign.creator:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the creator can submit proof")
        if campaign.status != _ACTIVE:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this campaign is not active")
        index = int(campaign.next_milestone)
        milestone = self._milestone(int(campaign_id), index)
        now = self._now()
        if now >= self._effective_due(campaign, milestone):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the deadline for this milestone has passed")
        ok, reason = is_safe_proof_url(url)
        if not ok:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} {reason}")

        milestone.proof_url = str(url)
        milestone.submitted_at = u256(now)
        milestone.state = _PENDING

    @gl.public.write
    def review(self, campaign_id: u256) -> None:
        """Judge the pending proof of the current milestone.

        The creator may call this right after submitting. Anyone else must
        wait ``REVIEW_DELAY_SECONDS``, so a bystander cannot trigger a
        verdict while the creator is still finishing the page.
        """
        campaign = self._campaign(campaign_id)
        if campaign.status != _ACTIVE:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this campaign is not active")
        cid = int(campaign_id)
        index = int(campaign.next_milestone)
        milestone = self._milestone(cid, index)
        if milestone.state != _PENDING:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} there is no submitted proof to review")
        now = self._now()
        is_creator = gl.message.sender_address == campaign.creator
        if not is_creator and now < int(milestone.submitted_at) + REVIEW_DELAY_SECONDS:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the review delay for this submission has not elapsed yet")

        token = proof_token(str(gl.message.contract_address), cid, index, str(campaign.creator))
        verdict = ProofJudge.review(
            str(milestone.proof_url),
            token,
            str(campaign.title),
            str(campaign.pitch),
            index + 1,
            int(campaign.milestone_count),
            str(milestone.description),
        )

        decision = decide(verdict["verdict"], verdict["confidence"])
        milestone.verdict = verdict["verdict"]
        milestone.confidence = u8(int(verdict["confidence"]))
        milestone.quote = verdict["quote"]
        milestone.reason = verdict["reason"]
        milestone.reviewed_at = u256(now)
        milestone.attempts = u32(int(milestone.attempts) + 1)

        if decision == DECISION_RELEASE:
            self._release_tranche(campaign, milestone, cid, index, now)
        elif decision == DECISION_STRIKE:
            milestone.state = _OPEN
            campaign.strikes = u8(int(campaign.strikes) + 1)
            if int(campaign.strikes) >= int(campaign.max_strikes):
                self._fail_with_fault(campaign, "strikes")
            else:
                self._grant_cure(campaign, milestone, now)
        else:
            milestone.state = _OPEN
            self._grant_cure(campaign, milestone, now)

    @gl.public.write
    def declare_default(self, campaign_id: u256) -> None:
        """Fail a campaign whose current milestone is overdue.

        A milestone is overdue once its due date has passed *and* the
        creator has had at least ``REVIEW_GRACE_SECONDS`` since it became
        current. A submitted proof always gets a full grace window of
        review before anyone may call a default over it, and a review that
        paid nothing gives the creator a fresh window to fix and resubmit
        (see ``_grant_cure``).
        """
        campaign = self._campaign(campaign_id)
        if campaign.status != _ACTIVE:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this campaign is not active")
        milestone = self._milestone(int(campaign_id), int(campaign.next_milestone))
        now = self._now()
        if now < self._effective_due(campaign, milestone):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the current milestone is not overdue yet")
        if milestone.state == _PENDING and now < int(milestone.submitted_at) + REVIEW_GRACE_SECONDS:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} a submitted proof is still inside its review window")
        self._fail_with_fault(campaign, "deadline_missed")

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------

    @gl.public.write
    def claim_refund(self, campaign_id: u256) -> None:
        campaign = self._campaign(campaign_id)
        if campaign.status not in (_FAILED, _CANCELLED):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this campaign has nothing to refund")
        backer = gl.message.sender_address
        key = self._pkey(int(campaign_id), backer)
        pledge = int(self.pledges[key]) if key in self.pledges else 0
        if pledge == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} you have no unclaimed pledge on this campaign")

        share = refund_share(pledge, int(campaign.refund_pool), int(campaign.refund_weight))
        campaign.refund_pool = u256(int(campaign.refund_pool) - share)
        campaign.refund_weight = u256(int(campaign.refund_weight) - pledge)
        self.pledges[key] = u256(0)
        self._send(backer, share, int(campaign_id), "refund")

    # ------------------------------------------------------------------
    # Payout ledger
    # ------------------------------------------------------------------

    @gl.public.write
    def reconcile_payouts(self, max_items: u32) -> None:
        """Mark payouts as settled once the contract's balance proves they left.

        Anyone may call this. It changes nothing unless *every* payout still in
        flight has demonstrably left the contract (see ``payout_state``); a
        partial picture is left alone because the balance cannot say which
        payment it was.
        """
        if int(self.inflight_total) == 0:
            return
        if payout_state(int(self.held), self._balance(), int(self.inflight_total)) != PAYOUT_ALL_LANDED:
            return
        limit = int(max_items)
        limit = MAX_RECONCILE_BATCH if limit < 1 or limit > MAX_RECONCILE_BATCH else limit
        cursor = int(self.payout_cursor)
        end = int(self.next_payout)
        examined = 0
        while cursor < end and examined < limit:
            record = self.payouts[u256(cursor)]
            if record.state == _SENT:
                amount = int(record.amount)
                record.state = _SETTLED
                self.inflight_total = u256(int(self.inflight_total) - amount)
                self.held = u256(int(self.held) - amount)
            cursor += 1
            examined += 1
        self.payout_cursor = u256(cursor)

    @gl.public.write
    def retry_payout(self, payout_id: u256) -> None:
        """Emit a payment again when the first attempt never arrived.

        Allowed only once ``PAYOUT_PATIENCE_SECONDS`` have passed since the last
        attempt *and* while the contract's balance shows that nothing at all has
        left it. Then the payment cannot have been delivered, and the money for
        a second attempt is still the beneficiary's own.
        """
        if payout_id not in self.payouts:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no payout with that id")
        record = self.payouts[payout_id]
        if record.state != _SENT:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} this payout is already settled")
        now = self._now()
        if not may_resend(int(self.held), self._balance(), int(record.last_sent_at), now):
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} this payout cannot be re-sent yet: it is either still within its patience window "
                "or part of it may already have been delivered (call reconcile_payouts)"
            )
        record.last_sent_at = u256(now)
        record.attempts = u32(int(record.attempts) + 1)
        self._emit(record.to, int(record.amount))

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @gl.public.view
    def get_ledger(self) -> dict:
        held = int(self.held)
        inflight = int(self.inflight_total)
        try:
            balance = self._balance()
            state = payout_state(held, balance, inflight)
            balance_s = str(balance)
        except Exception:
            balance_s, state = "", "unknown"
        return {
            "held": str(held),
            "inflight_total": str(inflight),
            "balance": balance_s,
            "state": state,
            "payout_count": int(self.next_payout),
            "payout_cursor": int(self.payout_cursor),
        }

    @gl.public.view
    def get_payout(self, payout_id: u256) -> dict:
        if payout_id not in self.payouts:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no payout with that id")
        return self._payout_view(int(payout_id))

    @gl.public.view
    def list_payouts(self, campaign_id: u256, start: u32, limit: u32) -> list:
        """Payouts of one campaign with id >= start (at most ``limit``, never more than 100)."""
        cap = max(1, min(int(limit), 100))
        out = []
        for i in range(int(start), int(self.next_payout)):
            if int(self.payouts[u256(i)].campaign_id) == int(campaign_id):
                out.append(self._payout_view(i))
                if len(out) >= cap:
                    break
        return out

    @gl.public.view
    def get_campaign(self, campaign_id: u256) -> dict:
        campaign = self._campaign(campaign_id)
        cid = int(campaign_id)
        count = int(campaign.milestone_count)
        return {
            "id": cid,
            "creator": str(campaign.creator),
            "title": campaign.title,
            "pitch": campaign.pitch,
            "goal": str(int(campaign.goal)),
            "cap": str(int(campaign.cap)),
            "min_pledge": str(int(campaign.min_pledge)),
            "funding_deadline": str(int(campaign.funding_deadline)),
            "max_strikes": int(campaign.max_strikes),
            "status": campaign.status,
            "raised": str(int(campaign.raised)),
            "released": str(int(campaign.released)),
            "bond": str(int(campaign.bond)),
            "backer_count": int(campaign.backer_count),
            "next_milestone": int(campaign.next_milestone),
            "milestone_count": count,
            "strikes": int(campaign.strikes),
            "current_since": str(int(campaign.current_since)),
            "cure_until": str(int(campaign.cure_until)),
            "fail_reason": campaign.fail_reason,
            "refund_pool": str(int(campaign.refund_pool)),
            "refund_weight": str(int(campaign.refund_weight)),
            "milestones": [self._milestone_view(cid, i) for i in range(count)],
        }

    @gl.public.view
    def get_milestone(self, campaign_id: u256, index: u32) -> dict:
        self._campaign(campaign_id)
        return self._milestone_view(int(campaign_id), int(index))

    @gl.public.view
    def get_proof_token(self, campaign_id: u256, index: u32) -> str:
        campaign = self._campaign(campaign_id)
        if not (0 <= int(index) < int(campaign.milestone_count)):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no such milestone")
        return proof_token(str(gl.message.contract_address), int(campaign_id), int(index), str(campaign.creator))

    @gl.public.view
    def get_position(self, campaign_id: u256, backer: str) -> dict:
        campaign = self._campaign(campaign_id)
        try:
            address = Address(backer)
        except Exception:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} backer must be a 0x-prefixed address")
        key = self._pkey(int(campaign_id), address)
        pledge = int(self.pledges[key]) if key in self.pledges else 0
        refundable = 0
        if campaign.status in (_FAILED, _CANCELLED) and pledge > 0:
            refundable = refund_share(pledge, int(campaign.refund_pool), int(campaign.refund_weight))
        return {"pledged": str(pledge), "refundable_now": str(refundable)}

    @gl.public.view
    def list_campaign_ids(self, status: str) -> list:
        """Ids of campaigns with the given status ("" lists them all)."""
        return [int(k) for k, v in self.campaigns.items() if status == "" or v.status == status]

    @gl.public.view
    def campaign_count(self) -> int:
        return int(self.next_id)

    @gl.public.view
    def required_bond(self, goal: u256) -> str:
        if int(goal) < 1:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} goal must be positive")
        return str(min_bond(int(goal)))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _now(self) -> int:
        return parse_iso_timestamp(gl.message_raw["datetime"])

    def _campaign(self, campaign_id: u256) -> Campaign:
        if campaign_id not in self.campaigns:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no campaign with that id")
        return self.campaigns[campaign_id]

    def _mkey(self, campaign_id: int, index: int) -> u256:
        return u256(int(campaign_id) * 8 + int(index))

    def _milestone(self, campaign_id: int, index: int) -> Milestone:
        key = self._mkey(campaign_id, index)
        if not (0 <= index < 8) or key not in self.milestones:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no such milestone")
        return self.milestones[key]

    def _pkey(self, campaign_id: int, backer: Address) -> str:
        return f"{int(campaign_id)}:{backer.as_hex}"

    def _effective_due(self, campaign: Campaign, milestone: Milestone) -> int:
        """Due date, stretched so every milestone gets a minimum working window.

        Two things can push it past the stated due date: the minimum working
        window since the milestone became current, and the cure window earned
        by a review that paid nothing.
        """
        return max(
            int(milestone.due),
            int(campaign.current_since) + REVIEW_GRACE_SECONDS,
            int(campaign.cure_until),
        )

    def _grant_cure(self, campaign: Campaign, milestone: Milestone, now: int) -> None:
        """Give the creator time to answer a verdict that paid nothing.

        Without this, a proof submitted shortly before the due date and judged
        "unclear" (or struck) could never be fixed, and anyone could default
        the campaign at once. The extension is a fresh grace window, and only
        the first ``MAX_CURED_REVIEWS`` reviews of a milestone earn one, so the
        creator cannot stall forever.
        """
        if int(milestone.attempts) <= MAX_CURED_REVIEWS:
            campaign.cure_until = u256(max(int(campaign.cure_until), now + REVIEW_GRACE_SECONDS))

    def _milestone_view(self, campaign_id: int, index: int) -> dict:
        m = self._milestone(campaign_id, index)
        return {
            "index": index,
            "description": m.description,
            "bps": int(m.bps),
            "due": str(int(m.due)),
            "state": m.state,
            "proof_url": m.proof_url,
            "submitted_at": str(int(m.submitted_at)),
            "tranche": str(int(m.tranche)),
            "verdict": m.verdict,
            "confidence": int(m.confidence),
            "quote": m.quote,
            "reason": m.reason,
            "reviewed_at": str(int(m.reviewed_at)),
            "attempts": int(m.attempts),
        }

    def _release_tranche(self, campaign: Campaign, milestone: Milestone, cid: int, index: int, now: int) -> None:
        count = int(campaign.milestone_count)
        shares = [int(self._milestone(cid, i).bps) for i in range(count)]
        amount = tranche_amounts(int(campaign.raised), shares)[index]

        milestone.state = _PASSED
        milestone.tranche = u256(amount)
        campaign.released = u256(int(campaign.released) + amount)
        campaign.strikes = u8(0)
        campaign.next_milestone = u8(index + 1)
        campaign.current_since = u256(now)
        campaign.cure_until = u256(0)

        payout = amount
        kind = "tranche"
        if index + 1 == count:
            campaign.status = _COMPLETED
            payout += int(campaign.bond)
            campaign.bond = u256(0)
            kind = "tranche_and_bond"
        self._send(campaign.creator, payout, cid, kind)

    def _end_without_fault(self, cid: int, campaign: Campaign, status: str, reason: str) -> None:
        """Funding never started: backers get everything back, the bond returns."""
        bond = int(campaign.bond)
        campaign.status = status
        campaign.fail_reason = reason
        campaign.refund_pool = campaign.raised
        campaign.refund_weight = campaign.raised
        campaign.bond = u256(0)
        self._send(campaign.creator, bond, cid, "bond_returned")

    def _fail_with_fault(self, campaign: Campaign, reason: str) -> None:
        """The creator did not deliver: the bond joins the refund pool."""
        unreleased = int(campaign.raised) - int(campaign.released)
        campaign.status = _FAILED
        campaign.fail_reason = reason
        campaign.refund_pool = u256(unreleased + int(campaign.bond))
        campaign.refund_weight = campaign.raised
        campaign.bond = u256(0)

    def _send(self, to: Address, amount: int, campaign_id: int, kind: str) -> None:
        """Record a payment on the ledger, then emit the transfer.

        The ledger entry is what keeps the beneficiary's entitlement alive: the
        campaign books are cleared the moment the payment is requested, but the
        entry stays ``sent`` until ``reconcile_payouts`` sees the money leave.
        """
        amount = int(amount)
        if amount <= 0 or to == _ZERO_ADDRESS:
            return
        now = self._now()
        payout_id = int(self.next_payout)
        self.next_payout = u256(payout_id + 1)
        self.payouts[u256(payout_id)] = Payout(
            to=to,
            amount=u256(amount),
            campaign_id=u256(int(campaign_id)),
            kind=kind,
            state=_SENT,
            created_at=u256(now),
            last_sent_at=u256(now),
            attempts=u32(1),
        )
        self.inflight_total = u256(int(self.inflight_total) + amount)
        self._emit(to, amount)

    def _emit(self, to: Address, amount: int) -> None:
        # The one place that talks to the network's transfer mechanism: an
        # external message to a wallet, delivered by the ghost contract when
        # the transaction that emitted it is finalized.
        _Wallet(to).emit_transfer(value=u256(amount))

    def _balance(self) -> int:
        try:
            return int(self.balance)
        except Exception:
            raise gl.vm.UserError(f"{ERROR_EXTERNAL} the contract balance could not be read")

    def _payout_view(self, payout_id: int) -> dict:
        p = self.payouts[u256(payout_id)]
        return {
            "id": payout_id,
            "to": str(p.to),
            "amount": str(int(p.amount)),
            "campaign_id": int(p.campaign_id),
            "kind": p.kind,
            "state": p.state,
            "created_at": str(int(p.created_at)),
            "last_sent_at": str(int(p.last_sent_at)),
            "attempts": int(p.attempts),
        }
