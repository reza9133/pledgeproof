"""Shared harness for the direct-mode contract tests.

genlayer-test's direct mode runs the bundled contract inside an in-memory
VM. It has no real chain behind it, so this file adds the missing pieces:

* ``Chain.tx`` -- sends a transaction: attaches GEN, credits the contract's
  balance, and rolls everything back (storage, balances, emitted transfers)
  if the call reverts, the way a real chain would.
* a transfer recorder -- ``emit_transfer`` calls are captured, so tests can
  assert exactly who was paid what, and a running contract balance lets
  every test check that the vault is always exactly solvent.
* a clock -- ``Chain.set_time`` moves the transaction timestamp the
  contract reads from ``gl.message_raw``.
* web / LLM mock helpers that can be re-pointed between calls.
"""
import json
import pathlib
import re
import sys
from datetime import datetime, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

BUNDLE = ROOT / "dist" / "pledge_vault.bundle.py"
GEN = 10**18
T0 = 1_800_000_000          # the "genesis" timestamp every test starts from
HOUR = 3_600
DAY = 86_400


@pytest.fixture(scope="session", autouse=True)
def _fresh_bundle():
    """Rebuild the bundle so the tests never drift from the sources."""
    import bundle

    bundle.main()
    yield


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


class Chain:
    def __init__(self, vm, contract):
        self.vm = vm
        self.contract = contract
        self.balance = 0                 # GEN held by the contract
        self.received = {}               # address -> total GEN sent to it by the contract
        self.transfers = []              # committed (address, amount) in order
        self._pending = []
        self.now = T0
        vm._gl_call_hook = self._hook

    # -- plumbing ---------------------------------------------------------

    def _hook(self, vm, request):
        if "PostMessage" in request:
            data = request["PostMessage"]
            self._pending.append((str(data["address"]), int(data["value"])))
            return {"ok": None}
        return None

    def set_time(self, ts: int) -> None:
        self.now = int(ts)
        stamp = iso(self.now)
        self.vm.warp(stamp)
        gl = sys.modules.get("genlayer.gl")
        if gl is not None:
            gl.message_raw["datetime"] = stamp

    def advance(self, seconds: int) -> None:
        self.set_time(self.now + seconds)

    def tx(self, sender, method: str, *args, value: int = 0):
        """Send a transaction. On revert, roll everything back and re-raise."""
        snapshot = self.vm.snapshot()
        self._pending = []
        self.vm.value = int(value)
        try:
            with self.vm.prank(sender):
                result = getattr(self.contract, method)(*args)
        except BaseException:
            self.vm.value = 0
            self.vm.revert(snapshot)
            self._pending = []
            raise
        self.vm.value = 0
        self.balance += int(value)
        for address, amount in self._pending:
            self.balance -= amount
            self.received[address] = self.received.get(address, 0) + amount
            self.transfers.append((address, amount))
        self._pending = []
        assert self.balance >= 0, "the contract paid out more than it ever received"
        return result

    def reverts(self, sender, method: str, *args, value: int = 0, match: str = ""):
        """Assert that a transaction reverts (with ``match`` in the error) and changes nothing."""
        before_balance = self.balance
        before_transfers = len(self.transfers)
        with pytest.raises(Exception) as info:
            self.tx(sender, method, *args, value=value)
        assert match in str(info.value), f"expected {match!r} in {info.value}"
        assert self.balance == before_balance
        assert len(self.transfers) == before_transfers
        return info.value

    def view(self, method: str, *args):
        return getattr(self.contract, method)(*args)

    # -- mocks ------------------------------------------------------------

    def set_page(self, url: str, text: str) -> None:
        pattern = re.escape(url)
        self.vm._web_mocks[:] = [m for m in self.vm._web_mocks if m[0].pattern != pattern]
        self.vm.mock_web(pattern, {"status": 200, "body": text})

    def drop_page(self, url: str) -> None:
        pattern = re.escape(url)
        self.vm._web_mocks[:] = [m for m in self.vm._web_mocks if m[0].pattern != pattern]

    def set_llm(self, verdict="met", confidence=90, quote="", reason="looks right", raw=None) -> None:
        self.vm._llm_mocks.clear()
        self.vm._llm_mocks_hit.clear()
        body = raw if raw is not None else json.dumps(
            {"verdict": verdict, "confidence": confidence, "quote": quote, "reason": reason}
        )
        self.vm.mock_llm(r"milestone-based crowdfunding", body)

    def llm_calls_made(self) -> int:
        return len(self.vm._llm_mocks_hit)

    def paid_to(self, address) -> int:
        return self.received.get(str(address), 0)


@pytest.fixture
def people(direct_vm):
    from gltest.direct.loader import create_address

    names = ["creator", "bob", "carol", "dave", "erin", "frank", "mallory"]
    return {name: create_address(name) for name in names}


@pytest.fixture
def chain(direct_vm, direct_deploy):
    direct_vm.warp(iso(T0))                     # before the SDK reads its first message
    contract = direct_deploy(str(BUNDLE))
    env = Chain(direct_vm, contract)
    env.set_time(T0)
    return env


# ---------------------------------------------------------------------------
# Scenario builders used by several test modules
# ---------------------------------------------------------------------------

PROOF_URL = "https://example.com/launch-notes"


def plan(*steps):
    """steps: (description, bps, due)"""
    return json.dumps([{"description": d, "bps": b, "due": t} for d, b, t in steps])


DEFAULT_PLAN = plan(
    ("Publish a working alpha with a public changelog", 3000, T0 + 14 * DAY),
    ("Publish the independent security audit report", 3000, T0 + 30 * DAY),
    ("Ship version 1.0 and publish the release notes", 4000, T0 + 60 * DAY),
)


def launch(chain, creator, *, goal=100 * GEN, cap=None, min_pledge=1 * GEN, deadline=None,
           max_strikes=2, milestones=None, bond=None, title="Open Telescope Kit",
           pitch="A community-built open hardware telescope with public designs."):
    deadline = deadline if deadline is not None else T0 + 7 * DAY
    cap = cap if cap is not None else goal * 2
    bond = bond if bond is not None else chain.view("required_bond", goal)
    return chain.tx(
        creator, "launch_campaign", title, pitch, goal, cap, min_pledge, deadline, max_strikes,
        milestones if milestones is not None else DEFAULT_PLAN, value=int(bond),
    )


def fund_and_activate(chain, people, cid=0, pledges=None):
    """Back a campaign and close funding at its deadline. Returns the pledges used."""
    pledges = pledges or {"bob": 60 * GEN, "carol": 40 * GEN}
    for name, amount in pledges.items():
        chain.tx(people[name], "back", cid, value=amount)
    campaign = chain.view("get_campaign", cid)
    chain.set_time(int(campaign["funding_deadline"]))
    chain.tx(people["dave"], "close_funding", cid)
    return pledges


def page_with_token(chain, cid, index, body="The alpha build is live and the changelog is published."):
    token = chain.view("get_proof_token", cid, index)
    return f"{body} Proof: {token}", token


def submit(chain, people, cid=0, url=PROOF_URL, body="The alpha build is live and the changelog is published.",
           quote=None):
    """Submit proof for the current milestone with a page that carries the token."""
    campaign = chain.view("get_campaign", cid)
    index = campaign["next_milestone"]
    text, _ = page_with_token(chain, cid, index, body)
    chain.set_page(url, text)
    chain.tx(people["creator"], "submit_proof", cid, url)
    return quote or body


def solvency_check(chain, cid=0, extra_open_pool=0):
    """The vault must hold exactly what it owes -- never more, never less."""
    c = chain.view("get_campaign", cid)
    raised, released, bond = int(c["raised"]), int(c["released"]), int(c["bond"])
    status = c["status"]
    if status in ("funding",):
        owed = raised + bond
    elif status == "active":
        owed = (raised - released) + bond
    elif status == "completed":
        owed = 0
    else:  # failed / cancelled
        owed = int(c["refund_pool"]) + bond
    assert chain.balance == owed + extra_open_pool, (status, chain.balance, owed)
