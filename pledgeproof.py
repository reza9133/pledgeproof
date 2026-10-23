# PledgeProof oracle: turns one public web page plus one LLM judgment into a
# consensus-verified milestone verdict.
#
# Two kinds of guarantee are combined here and kept deliberately apart:
#
#   * Deterministic checks the contract can make itself -- the page must
#     carry the campaign's proof token, and a "met" verdict must be backed
#     by a quote that really appears on the page. These run inside the
#     non-deterministic block, so every validator applies them to its own
#     fetch of the page.
#
#   * Judgment -- whether the page actually demonstrates the milestone. No
#     single correct byte string exists for that, so validators re-run the
#     same prompt independently and compare only the *effect* of the
#     verdict (release / strike / nothing) plus a confidence tolerance,
#     never the wording.
#
# Errors use the prefixes GenLayer's own guidance recommends:
#   [EXPECTED]  caller mistake, compared for exact equality
#   [EXTERNAL]  deterministic upstream rejection, compared for exact equality
#   [TRANSIENT] temporary outage, validators agree if both hit one
#   [LLM_ERROR] the model misbehaved, validators never agree (forces rotation)

from genlayer import *


from pledgeproof_pure import (
    MAX_PAGE_CHARS,
    VERDICT_MET,
    VERDICT_UNCLEAR,
    build_review_prompt,
    clean_verdict,
    normalize_text,
    quote_is_grounded,
    strip_fence_markers,
    token_on_page,
    verdict_is_wellformed,
    verdicts_agree,
)

ERROR_EXPECTED = "[EXPECTED]"
ERROR_EXTERNAL = "[EXTERNAL]"
ERROR_TRANSIENT = "[TRANSIENT]"
ERROR_LLM = "[LLM_ERROR]"


def _unclear(reason: str) -> dict:
    return {"verdict": VERDICT_UNCLEAR, "confidence": 0, "quote": "", "reason": reason}


def _review_once(url: str, token: str, title: str, pitch: str, number: int, total: int, criteria: str) -> tuple:
    """Fetch, check and judge once. Returns ``(verdict, excerpt)``.

    ``excerpt`` is the page text the model saw ("" when the page never got that
    far), so a validator can re-check the leader's quote against its own copy.
    """
    try:
        rendered = gl.nondet.web.render(url, mode="text")
    except Exception:
        raise gl.vm.UserError(f"{ERROR_TRANSIENT} the proof page could not be loaded right now")

    page = strip_fence_markers(normalize_text(rendered if isinstance(rendered, str) else ""))
    if not page:
        return _unclear("The proof page has no readable text."), ""
    if not token_on_page(token, page):
        return _unclear("The proof token for this milestone was not found on the page."), ""

    excerpt = page[:MAX_PAGE_CHARS]
    prompt = build_review_prompt(title, pitch, number, total, criteria, excerpt)
    try:
        answer = gl.nondet.exec_prompt(prompt, response_format="json")
    except Exception:
        # The model backend failed or returned something the host could not parse.
        # Validators never agree on this, which rotates the leader instead of
        # letting a half-working model decide.
        raise gl.vm.UserError(f"{ERROR_LLM} the model call failed")
    try:
        verdict = clean_verdict(answer)
    except (ValueError, RecursionError):
        raise gl.vm.UserError(f"{ERROR_LLM} the model returned no usable verdict")

    if verdict["verdict"] == VERDICT_MET and not quote_is_grounded(verdict["quote"], excerpt):
        verdict = {
            "verdict": VERDICT_UNCLEAR,
            "confidence": min(int(verdict["confidence"]), 49),
            "quote": "",
            "reason": ("Approval withheld: the model's supporting quote was not found on the page. "
                       + verdict["reason"])[:600],
        }
    return verdict, excerpt


def _errors_agree(leaders_res, leader_fn) -> bool:
    leader_message = str(getattr(leaders_res, "message", ""))
    try:
        leader_fn()
        return False  # the leader failed, this validator succeeded
    except gl.vm.UserError as exc:
        mine = str(exc.message)
    except Exception:
        return False
    if mine.startswith(ERROR_EXPECTED) or mine.startswith(ERROR_EXTERNAL):
        return mine == leader_message
    if mine.startswith(ERROR_TRANSIENT) and leader_message.startswith(ERROR_TRANSIENT):
        return True
    return False  # [LLM_ERROR] or anything unknown: never agree


class ProofJudge:
    """Static, key-less, consensus-aware judge for milestone proof pages."""

    @staticmethod
    def review(
        url: str, token: str, title: str, pitch: str, number: int, total: int, criteria: str
    ) -> dict:
        """Render ``url``, check the proof token, ask the model whether the
        page shows ``criteria`` delivered, and return the validators' agreed
        verdict: ``{"verdict", "confidence", "quote", "reason"}``.

        Everything the closures use is a plain ``str`` / ``int`` copy: a
        non-deterministic block must never touch contract storage.
        """
        url = str(url)
        token = str(token)
        title = str(title)
        pitch = str(pitch)
        number = int(number)
        total = int(total)
        criteria = str(criteria)

        def leader_fn() -> dict:
            return _review_once(url, token, title, pitch, number, total, criteria)[0]

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return _errors_agree(leaders_res, leader_fn)
            leader = leaders_res.calldata
            if not verdict_is_wellformed(leader):
                return False        # never trust the shape of the leader's answer
            try:
                mine, excerpt = _review_once(url, token, title, pitch, number, total, criteria)
            except gl.vm.UserError:
                return False
            except Exception:
                return False
            if leader["verdict"] == VERDICT_MET and not quote_is_grounded(leader["quote"], excerpt):
                return False        # the quote that will be shown to backers must be on the page
            return verdicts_agree(leader, mine)

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
