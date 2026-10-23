"""Offline self-check of scripts/live_e2e.py.

The live script cannot reach Studionet from a test run, but its scenario code is
backend-agnostic. Here the very same scenarios run against the bundled contract in
GenVM's in-memory runner, with a stand-in "model" that reacts to the page text. That
catches wrong argument orders, wrong expectations and crashes in the script itself
before anyone spends minutes on a real network.
"""
import json
import types

import pytest

import live_e2e as live
from conftest import DAY, HOUR


class DirectBackend(live.Backend):
    name = "direct"

    def __init__(self, chain):
        from gltest.direct.loader import create_address

        self.chain = chain
        self._create_address = create_address
        self.spent = {}
        self.pages = {}
        self.llm_calls = []
        self.counter = 0

    def new_account(self, label, private_key=None):
        raw = self._create_address(f"selfcheck-{label}")
        return live.Acct(label=label, address=str(raw), raw=raw)

    def fund(self, acct, wei):
        return True

    def balance(self, address):
        return 10**30 - self.spent.get(address, 0) + self.chain.paid_to(address)

    def deploy(self, acct, code):
        return "0xdirect"

    def now(self):
        return self.chain.now

    def wait_until(self, timestamp, report):
        self.chain.set_time(timestamp)

    def host_page(self, text):
        self.counter += 1
        url = f"https://pages.example.com/p{self.counter}"
        self.pages[url] = text
        self.chain.set_page(url, text)
        return url

    def settle(self, tx, report):
        pass

    def read(self, address, fn, args):
        return self.chain.view(fn, *args)

    def _model_for(self, text):
        if "pancakes" in text:
            return ("not_met", 92, "", "unrelated page")
        if "ROADMAP" in text:
            return ("not_met", 85, "", "only promises")
        if "SYSTEM NOTICE" in text:
            return ("unclear", 25, "", "no evidence of delivery")
        for quote in (live.QUOTE_1, live.QUOTE_2):
            if quote in text:
                return ("met", 92, quote, "the page shows it")
        return ("unclear", 30, "", "too vague")

    def write(self, acct, address, fn, args, value=0):
        if fn == "review":
            campaign = self.chain.view("get_campaign", args[0])
            if campaign["status"] == "active":
                milestone = campaign["milestones"][campaign["next_milestone"]]
                text = self.pages.get(milestone["proof_url"], "")
                verdict = self._model_for(text)
                self.chain.set_llm(*verdict)
                self.llm_calls.append(verdict[0])
        try:
            self.chain.tx(acct.raw, fn, *args, value=int(value))
        except Exception as exc:
            return live.Tx(ok=False, error=live.extract_contract_error(str(exc)) or str(exc)[:300])
        self.spent[acct.address] = self.spent.get(acct.address, 0) + int(value)
        return live.Tx(ok=True)


def run_scenarios(chain, only=None, long_mode=False):
    backend = DirectBackend(chain)
    report = live.run(backend, only, long_mode, llm_retries=2, fund_gen=100, unit=10**18, echo=False)
    return backend, report


def failures(report):
    return [(r.scenario, r.name, r.detail) for r in report.results if r.status in ("FAIL", "WARN")]


def test_every_scenario_passes_against_the_in_memory_contract(chain):
    backend, report = run_scenarios(chain, long_mode=True)
    assert failures(report) == []
    counts = report.counts()
    assert counts["PASS"] > 150 and counts["SKIP"] == 0
    assert {"met", "not_met", "unclear"} <= set(backend.llm_calls)       # the model stand-in was really consulted


@pytest.mark.parametrize("name", list(live.SCENARIOS))
def test_each_scenario_can_run_alone(chain, name):
    _, report = run_scenarios(chain, only=[name], long_mode=(name == "goalmissed"))
    assert failures(report) == []


def test_goal_missed_is_skipped_without_long_mode(chain):
    _, report = run_scenarios(chain, only=["goalmissed"], long_mode=False)
    assert report.counts()["SKIP"] == 1 and report.counts()["FAIL"] == 0


def test_the_script_notices_a_broken_contract(chain, monkeypatch):
    """A script that cannot fail is worthless: make the 'model' approve everything and
    check that the negative scenarios turn red."""
    backend = DirectBackend(chain)
    monkeypatch.setattr(DirectBackend, "_model_for",
                        lambda self, text: ("met", 99, live.QUOTE_1, "approve everything"))
    # the quote is not on the roadmap page, so the contract itself withholds the approval ...
    report = live.run(backend, ["roadmap"], False, 1, 100, 10**18, echo=False)
    assert failures(report) == []
    # ... but a page that does contain the quote and is "unrelated" must be flagged by the script
    monkeypatch.setattr(live, "page_unrelated", lambda token: f"{live.QUOTE_1}\nVerification token: {token}\n")
    backend = DirectBackend(chain)
    report = live.run(backend, ["unrelated"], False, 1, 100, 10**18, echo=False)
    assert any(r.status == "FAIL" for r in report.results)


def test_report_writes_json(chain, tmp_path):
    _, report = run_scenarios(chain, only=["cancel"])
    out = tmp_path / "r.json"
    report.write_json(out, {"network": "test"})
    data = json.loads(out.read_text())
    assert data["counts"]["FAIL"] == 0 and data["extra"]["network"] == "test" and data["results"]


# ---------------------------------------------------------------------------
# the helpers that read a real Studio receipt
# ---------------------------------------------------------------------------

def test_contract_errors_are_found_in_receipts_and_exceptions():
    assert live.extract_contract_error("UserError(message='[EXPECTED] only the creator can cancel')") == \
        "[EXPECTED] only the creator can cancel"
    receipt = {"consensus_data": {"leader_receipt": [{"result": {"status": "rollback",
                                                                  "payload": "[LLM_ERROR] the model returned no usable verdict"}}]}}
    assert live.extract_contract_error(receipt).startswith("[LLM_ERROR] the model")
    assert live.extract_contract_error("plain failure") == ""


@pytest.mark.parametrize("receipt, expected", [
    ({"consensus_data": {"leader_receipt": [{"execution_result": "SUCCESS"}]}}, True),
    ({"tx_execution_result_name": "FINISHED_WITH_RETURN"}, True),
    ({"consensus_data": {"leader_receipt": [{"execution_result": "ERROR", "result": "[EXPECTED] nope"}]}}, False),
    ({"tx_execution_result_name": "FINISHED_WITH_ERROR"}, False),
    ({"result_name": "DISAGREE"}, False),
    ({"status_name": "UNDETERMINED"}, False),
    ({"status_name": "ACCEPTED"}, None),
    ({}, None),
])
def test_receipt_outcome(receipt, expected):
    assert live.receipt_outcome(receipt)[0] is expected


def test_receipt_outcome_reports_the_contract_message():
    ok, detail = live.receipt_outcome({"consensus_data": {"leader_receipt": [
        {"execution_result": "ERROR", "result": {"payload": "[EXPECTED] the deadline for this milestone has passed"}}]}})
    assert ok is False and detail == "[EXPECTED] the deadline for this milestone has passed"


@pytest.mark.parametrize("receipt, expected", [
    ({"data": {"contract_address": "0x" + "ab" * 20}}, "0x" + "ab" * 20),
    ({"tx_data_decoded": {"contract_address": "0x" + "cd" * 20}, "recipient": "0x" + "00" * 20}, "0x" + "cd" * 20),
    ({"recipient": "0x" + "ef" * 20}, "0x" + "ef" * 20),
    ({"to_address": "0x" + "00" * 20}, ""),
    ({"nothing": "here"}, ""),
])
def test_find_contract_address(receipt, expected):
    assert live.find_contract_address(receipt) == expected


def test_page_hosting_falls_back_and_validates(monkeypatch):
    calls = []

    def fake_http(url, data=None, headers=None, timeout=30):
        calls.append(url)
        if "paste.rs" in url:
            raise OSError("down")
        return '"https://dpaste.org/AbCd"'

    monkeypatch.setattr(live, "_http", fake_http)
    monkeypatch.delenv("PP_PAGE_CMD", raising=False)
    assert live.host_public_page("hello") == "https://dpaste.org/AbCd/raw"
    assert calls[0].startswith("https://paste.rs") and "dpaste.org" in calls[1]

    monkeypatch.setattr(live, "_http", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(live.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(RuntimeError, match="could not publish"):
        live.host_public_page("hello")


def test_all_hosted_urls_the_script_could_produce_pass_the_contracts_url_rules():
    import pledgeproof_pure as p

    for url in ("https://paste.rs/AbC", "https://dpaste.org/AbCd/raw",
                "https://gist.githubusercontent.com/user/0123456789abcdef/raw/page.txt",
                "https://raw.githubusercontent.com/user/repo/main/docs/page.txt"):
        assert p.is_safe_proof_url(url)[0], url


# ---------------------------------------------------------------------------
# LiveBackend plumbing, with a fake genlayer-py client (no network)
# ---------------------------------------------------------------------------

class FakeClient:
    def __init__(self, receipts):
        self.receipts = list(receipts)
        self.calls = []
        self.provider = types.SimpleNamespace(make_request=self._rpc)

    def _rpc(self, method, params):
        self.calls.append(("rpc", method, params))
        return {"result": "0x1"}

    def write_contract(self, **kw):
        self.calls.append(("write", kw))
        return "0xhash"

    def deploy_contract(self, **kw):
        self.calls.append(("deploy", kw))
        return "0xdeploy"

    def wait_for_transaction_receipt(self, **kw):
        self.calls.append(("wait", kw))
        return self.receipts.pop(0)

    def read_contract(self, **kw):
        self.calls.append(("read", kw))
        return {"ok": True}

    def get_balance(self, address):
        return 5


def make_live(receipts):
    pytest.importorskip("genlayer_py")
    backend = object.__new__(live.LiveBackend)
    from genlayer_py.types import TransactionStatus

    backend.TS = TransactionStatus
    backend.client = FakeClient(receipts)
    backend.wait_seconds = 30
    backend.interval_ms = 3000
    backend.rpc = "http://fake"
    return backend


def test_live_write_passes_arguments_and_reads_the_receipt():
    ok = {"consensus_data": {"leader_receipt": [{"execution_result": "SUCCESS"}]}, "status_name": "ACCEPTED"}
    bad = {"consensus_data": {"leader_receipt": [{"execution_result": "ERROR",
                                                  "result": {"payload": "[EXPECTED] only the creator can cancel"}}]},
           "status_name": "ACCEPTED"}
    backend = make_live([ok, bad])
    acct = live.Acct("creator", "0xabc", raw="RAW")
    tx = backend.write(acct, "0xcontract", "back", [3], value=7)
    assert tx.ok is True and tx.status == "ACCEPTED"
    kind, kw = backend.client.calls[0]
    assert kind == "write" and kw == {"address": "0xcontract", "function_name": "back", "account": "RAW",
                                      "value": 7, "args": [3]}
    tx = backend.write(acct, "0xcontract", "cancel_campaign", [3])
    assert tx.ok is False and tx.error == "[EXPECTED] only the creator can cancel"


def test_live_write_survives_a_rejected_submission_and_a_missing_receipt():
    backend = make_live([])
    backend.client.write_contract = lambda **kw: (_ for _ in ()).throw(RuntimeError("insufficient funds [EXPECTED] x"))
    tx = backend.write(live.Acct("a", "0x1", "RAW"), "0xc", "back", [0])
    assert tx.ok is False and "[EXPECTED] x" in tx.error
    backend = make_live([])
    backend.client.write_contract = lambda **kw: "0xhash"
    backend.client.wait_for_transaction_receipt = lambda **kw: (_ for _ in ()).throw(RuntimeError("still pending"))
    tx = backend.write(live.Acct("a", "0x1", "RAW"), "0xc", "back", [0])
    assert tx.ok is None and "no receipt" in tx.error


def test_live_deploy_returns_a_checksummed_address_and_refuses_failures():
    address = "0x" + "ab" * 20
    backend = make_live([{"data": {"contract_address": address}, "status_name": "ACCEPTED"}])
    result = backend.deploy(live.Acct("creator", "0x1", "RAW"), "code")
    assert result.lower() == address and backend.client.calls[0][1]["args"] == []
    failed = {"consensus_data": {"leader_receipt": [{"execution_result": "ERROR"}]}}
    with pytest.raises(RuntimeError, match="deployment failed"):
        make_live([failed]).deploy(live.Acct("creator", "0x1", "RAW"), "code")
    with pytest.raises(RuntimeError, match="no contract address"):
        make_live([{"status_name": "ACCEPTED"}]).deploy(live.Acct("creator", "0x1", "RAW"), "code")


def test_live_read_fund_and_balance_plumbing():
    backend = make_live([])
    assert backend.read("0xc", "get_campaign", [0]) == {"ok": True}
    assert backend.client.calls[0][1] == {"address": "0xc", "function_name": "get_campaign", "args": [0]}
    acct = live.Acct("bob", "0xbob", "RAW")
    backend.balance = lambda address: 10**20
    assert backend.fund(acct, 10**20) is True
    assert ("rpc", "sim_fundAccount", ["0xbob", 10**20]) in backend.client.calls
    backend.client.provider.make_request = lambda method, params: (_ for _ in ()).throw(RuntimeError("no faucet"))
    assert backend.fund(acct, 1) is False
