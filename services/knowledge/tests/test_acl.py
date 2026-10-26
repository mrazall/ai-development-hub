import pytest

from aihub_knowledge.acl import Principal, parse_principal, sign_principal


def test_principal_hmac_roundtrip_and_tamper_rejection():
    principal = Principal("u", "viewer", frozenset({"alpha"}))
    signed = sign_principal(principal, "dev-only-test-secret")
    assert parse_principal(signed, "dev-only-test-secret") == principal
    with pytest.raises(ValueError):
        parse_principal(signed + "x", "dev-only-test-secret")


def test_missing_principal_rejected():
    with pytest.raises(ValueError):
        parse_principal(None, "dev-only-test-secret")
