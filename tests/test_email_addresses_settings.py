from __future__ import annotations

import pytest

from src.utils.email_addresses import (
    InvalidEmailAddressError,
    header_addresses,
    header_sender_address,
    normalize_email_address,
    parse_email_address,
)
from src.utils.email_settings import (
    DEFAULT_EMAIL_SETTINGS,
    InvalidEmailSettingsError,
    normalize_email_settings,
    parse_allowed_senders,
    parse_email_settings_input,
)


def _input(**overrides) -> dict:
    return {
        "enabled": True,
        "alias": "Agent@Example.TEST",
        "agent_name": "  Helper  ",
        "allowed_senders": "",
        "email_approval_policy": "wait-for-human",
        "followup_behavior": "auto",
        **overrides,
    }


# -- addresses ---------------------------------------------------------------


def test_ascii_addresses_are_trimmed_and_lowercased() -> None:
    assert parse_email_address("  Person.Name+Tag@Example.TEST ") == (
        "person.name+tag@example.test"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "pаypal@example.test",  # Cyrillic 'a' look-alike
        "person@exаmple.test",
        "ｐerson@example.test",  # fullwidth p
        "person​@example.test",  # zero-width space
        "PERSON@EXAMPLE.TESTİ",  # Turkish dotted capital I
    ],
)
def test_non_ascii_is_rejected_before_any_case_change(raw: str) -> None:
    with pytest.raises(InvalidEmailAddressError, match="non-ASCII"):
        parse_email_address(raw)
    assert normalize_email_address(raw) is None


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("a@@example.test", "exactly one"),
        ("noatsign.example.test", "exactly one"),
        ("@example.test", "before '@'"),
        ("a b@example.test", "whitespace"),
        ("person@localhost", "invalid domain"),
        ("person@-bad.test", "invalid domain"),
        ('"quoted"@example.test', "not allowed"),
    ],
)
def test_invalid_addresses_raise_with_a_reason(raw: str, reason: str) -> None:
    with pytest.raises(InvalidEmailAddressError, match=reason):
        parse_email_address(raw)


def test_sender_uses_addr_spec_never_the_display_name() -> None:
    assert (
        header_sender_address('"boss@example.test" <attacker@evil.test>')
        == "attacker@evil.test"
    )
    assert header_sender_address("Person <PERSON@Example.test>") == (
        "person@example.test"
    )
    assert header_sender_address("") is None


def test_empty_headers_do_not_hide_other_recipients() -> None:
    # Regression: strict getaddresses() drops everything for "a@x, , ".
    assert header_addresses("Agent <agent@example.test>", "", "  ") == {
        "agent@example.test"
    }


def test_header_addresses_collects_valid_recipients_only() -> None:
    assert header_addresses(
        "A <a@example.test>, b@EXAMPLE.test", "bad-address", "c@exаmple.test"
    ) == {"a@example.test", "b@example.test"}


# -- settings ----------------------------------------------------------------


def test_parse_settings_normalizes_and_never_trusts_claim_time() -> None:
    settings = parse_email_settings_input(_input(alias_claimed_at=123.0))
    assert settings["alias"] == "agent@example.test"
    assert settings["agent_name"] == "Helper"
    assert settings["alias_claimed_at"] is None


def test_empty_alias_means_no_claim() -> None:
    assert parse_email_settings_input(_input(alias="   "))["alias"] == ""


def test_allowed_senders_one_per_line_deduplicated() -> None:
    assert parse_allowed_senders(
        "a@example.test\n\n  B@Example.Test \r\na@example.test\n"
    ) == ["a@example.test", "b@example.test"]


def test_allowed_senders_commas_are_not_separators() -> None:
    with pytest.raises(InvalidEmailSettingsError, match="line 1"):
        parse_allowed_senders("a@example.test, b@example.test")


def test_invalid_sender_line_names_the_line_and_reason() -> None:
    with pytest.raises(InvalidEmailSettingsError) as info:
        parse_allowed_senders("ok@example.test\npаypal@example.test")
    assert info.value.field == "allowed_senders"
    assert "line 2" in str(info.value)
    assert "non-ASCII" in str(info.value)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"enabled": "yes"}, "enabled"),
        ({"alias": "not-an-address"}, "alias"),
        ({"agent_name": 'Bad "name"'}, "agent_name"),
        ({"agent_name": "x" * 81}, "agent_name"),
        ({"email_approval_policy": "maybe"}, "email_approval_policy"),
        ({"followup_behavior": "sometimes"}, "followup_behavior"),
    ],
)
def test_invalid_settings_report_their_field(overrides: dict, field: str) -> None:
    with pytest.raises(InvalidEmailSettingsError) as info:
        parse_email_settings_input(_input(**overrides))
    assert info.value.field == field


def test_normalize_fills_fields_added_later() -> None:
    assert normalize_email_settings({"enabled": True}) == {
        **DEFAULT_EMAIL_SETTINGS,
        "enabled": True,
    }
    assert normalize_email_settings(None) == DEFAULT_EMAIL_SETTINGS
