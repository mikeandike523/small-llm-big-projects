from __future__ import annotations

import pytest

from src.utils.email_addresses import (
    InvalidEmailAddressError,
    header_addresses,
    header_sender_address,
    normalize_email_address,
    parse_email_address,
)
from src.utils.agent_settings import (
    InvalidAgentSettingsError,
    parse_agent_identity,
    parse_agent_settings,
    parse_allowed_senders,
)


def _input(**overrides) -> dict:
    return {
        "name": "  Helper  ",
        "email": "Agent@Example.TEST",
        "enabled": True,
        "allowed_senders": "",
        "profile_name": "default-profile",
        "approval_mode": "default",
        "automation_approval_policy": "wait-for-human",
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


def test_identity_lowercases_the_email_and_keeps_the_name_case() -> None:
    identity = parse_agent_identity(_input())
    assert identity.email == "agent@example.test"
    assert identity.name == "Helper"
    assert identity.name_key == "helper"


def test_allowed_senders_one_per_line_deduplicated() -> None:
    assert parse_allowed_senders(
        "a@example.test\n\n  B@Example.Test \r\na@example.test\n"
    ) == ["a@example.test", "b@example.test"]


def test_allowed_senders_commas_are_not_separators() -> None:
    with pytest.raises(InvalidAgentSettingsError, match="line 1"):
        parse_allowed_senders("a@example.test, b@example.test")


def test_invalid_sender_line_names_the_line_and_reason() -> None:
    with pytest.raises(InvalidAgentSettingsError) as info:
        parse_allowed_senders("ok@example.test\npаypal@example.test")
    assert info.value.field == "allowed_senders"
    assert "line 2" in str(info.value)
    assert "non-ASCII" in str(info.value)


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"enabled": "yes"}, "enabled"),
        ({"profile_name": " "}, "profile_name"),
        ({"approval_mode": "maybe"}, "approval_mode"),
        ({"automation_approval_policy": "maybe"}, "automation_approval_policy"),
    ],
)
def test_invalid_settings_report_their_field(overrides: dict, field: str) -> None:
    with pytest.raises(InvalidAgentSettingsError) as info:
        parse_agent_settings(_input(**overrides))
    assert info.value.field == field


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"email": "not-an-address"}, "email"),
        ({"email": " "}, "email"),
        ({"name": " "}, "name"),
        ({"name": 'Bad "name"'}, "name"),
        ({"name": "x" * 81}, "name"),
    ],
)
def test_invalid_identity_reports_its_field(overrides: dict, field: str) -> None:
    with pytest.raises(InvalidAgentSettingsError) as info:
        parse_agent_identity(_input(**overrides))
    assert info.value.field == field
