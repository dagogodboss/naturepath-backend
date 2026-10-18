"""Unit tests for post-consent cutover helpers."""

from scripts.phase6_post_consent_helpers import (
    evaluate_mailbox_probes,
    qa_artifact_name,
    staging_env_gaps,
    validate_prod_gate,
    busy_intervals_assertion,
    decode_jwt_roles,
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
