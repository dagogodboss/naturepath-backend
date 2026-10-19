"""Unit tests for post-consent cutover helpers."""

from scripts.phase6_post_consent_helpers import (
    evaluate_mailbox_probes,
    qa_artifact_name,
    staging_env_gaps,
    validate_prod_gate,
    busy_intervals_assertion,
    decode_jwt_roles,
    is_synthetic_busy_source,
    prod_cutover_steps,
    real_outlook_busy_assertion,
)


def test_evaluate_mailbox_probes_ok():
    verdict = evaluate_mailbox_probes(
        [
            {"mailbox": "a@example.com", "status": "ok", "event_count": 3},
            {"mailbox": "b@example.com", "status": "ok", "event_count": 0},
        ]
    )
    assert verdict.ok is True
    assert verdict.code == "ok"


def test_evaluate_mailbox_probes_403_blocker():
    verdict = evaluate_mailbox_probes(
        [
            {
                "mailbox": "Clients@thenaturalpathla.com",
                "status": "error",
                "error": "Client error '403 Forbidden' ... ErrorAccessDenied",
            }
        ]
    )
    assert verdict.ok is False
    assert verdict.code == "entra_admin_consent_required"
    assert "admin consent" in verdict.message.lower()


def test_staging_env_gaps_detects_unset():
    gaps = staging_env_gaps({"MULTI_RESOURCE_SCHEDULING": "true"})
    assert any("OUTLOOK_APP_ONLY" in g for g in gaps)


def test_validate_prod_gate_requires_ack():
    assert validate_prod_gate(prod=True, dry_run=False, i_understand_prod=False) is not None
    assert validate_prod_gate(prod=True, dry_run=False, i_understand_prod=True) is None
    assert validate_prod_gate(prod=False, dry_run=False, i_understand_prod=False) is None


def test_validate_prod_gate_rejects_prod_dry_run():
    err = validate_prod_gate(prod=True, dry_run=True, i_understand_prod=True)
    assert err is not None


def test_busy_intervals_assertion_empty_not_allowed():
    ok, msg = busy_intervals_assertion({"r1": 0}, allow_empty=False)
    assert ok is False
    ok2, _ = busy_intervals_assertion({"r1": 0}, allow_empty=True)
    assert ok2 is True


def test_qa_artifact_name_stable_phase():
    name = qa_artifact_name(phase="staging", stamp="20261018")
    assert name == "post-consent-cutover-staging-20261018.json"


def test_decode_jwt_roles_empty_for_garbage():
    assert decode_jwt_roles("not-a-jwt") == []


def test_is_synthetic_busy_source():
    assert is_synthetic_busy_source("staging_prove_synthetic") is True
    assert is_synthetic_busy_source("outlook") is False
    assert is_synthetic_busy_source("booking") is False


def test_real_outlook_busy_assertion_rejects_empty_and_synthetic_only():
    ok_empty, _ = real_outlook_busy_assertion([], require_non_empty=True)
    assert ok_empty is False
    ok_synth, msg = real_outlook_busy_assertion(
        [{"source": "staging_prove_synthetic", "start_time": "15:00"}],
        require_non_empty=True,
    )
    assert ok_synth is False
    assert "synthetic" in msg.lower()
    ok_real, detail = real_outlook_busy_assertion(
        [
            {"source": "outlook", "start_time": "15:00", "end_time": "15:45"},
            {"source": "staging_prove_synthetic", "start_time": "16:00"},
        ],
        require_non_empty=True,
    )
    assert ok_real is True
    assert "real_busy_count=1" in detail


def test_prod_cutover_steps_enable_flag_last():
    steps = prod_cutover_steps()
    assert steps[0] == "validate"
    assert steps[-1] == "enable_flag"
    assert steps.index("prove_real_busy") < steps.index("enable_flag")
    assert steps.index("sync") < steps.index("prove_real_busy")
