"""The password rules, tested as pure functions.

No DB, no HTTP, no fixtures -- the whole module runs in milliseconds, which
is the point: the rules have changed three times in a day, and a policy you
can re-check instantly is a policy that stays honest.

The end-to-end behaviour (a refused change leaves the account untouched, an
accepted one logs in) lives in test_auth.py. Here we only pin the rules.
"""
import pytest

from app.services.password_policy import (
    MAXIMUM_PASSWORD_BYTES,
    MAXIMUM_SEQUENTIAL_RUN,
    MINIMUM_DISTINCT_CHARACTERS,
    MINIMUM_PASSWORD_LENGTH,
    CommonPasswordError,
    PasswordContainsIdentifierError,
    RepetitivePasswordError,
    WeakPasswordError,
    identifier_fragments,
    validate_password,
)

# A password that passes every rule, used as the base for "and this one is
# fine" assertions so a test that expects acceptance cannot pass merely
# because some other rule happened not to fire.
GOOD = "harbour7lantern"


def test_the_baseline_password_is_actually_accepted():
    """Guards every other test in this file.

    If GOOD ever stops being valid, the "rejected" tests below could start
    passing for the wrong reason -- they would still raise, just not for the
    reason each one names.
    """
    validate_password(GOOD)


# --- Structural -----------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("a1b2c"[: MINIMUM_PASSWORD_LENGTH - 1], id="one-below-minimum"),
        pytest.param("", id="empty"),
    ],
)
def test_too_short_is_refused(password):
    with pytest.raises(WeakPasswordError):
        validate_password(password)


def test_exactly_the_minimum_is_accepted():
    """The minimum must be attainable, not merely approached."""
    password = "harb7x"
    assert len(password) == MINIMUM_PASSWORD_LENGTH
    validate_password(password)


def test_exactly_the_hashing_limit_is_accepted_and_one_more_is_not():
    """bcrypt raises above 72 bytes; without this rule that is an HTTP 500."""
    filler = "harbour7lantern9kettle3window5anchor1bucket4cupboard6ferry8marina2quayside"
    at_limit = filler[:MAXIMUM_PASSWORD_BYTES]
    assert len(at_limit.encode("utf-8")) == MAXIMUM_PASSWORD_BYTES
    validate_password(at_limit)

    over_limit = filler[: MAXIMUM_PASSWORD_BYTES + 1]
    assert len(over_limit.encode("utf-8")) == MAXIMUM_PASSWORD_BYTES + 1
    with pytest.raises(WeakPasswordError):
        validate_password(over_limit)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("ก" * 10, id="thai"),
        pytest.param("harbour!7", id="punctuation"),
        pytest.param("harbour 7", id="internal-space"),
        pytest.param("harbour-7", id="hyphen"),
        pytest.param("harbour_7", id="underscore"),
        pytest.param("café127", id="accented-latin"),
        pytest.param("harbour7​", id="zero-width-space"),
        pytest.param(" harbour7", id="leading-space"),
        pytest.param("harbour7 ", id="trailing-space"),
    ],
)
def test_only_english_letters_and_digits_are_accepted(password):
    with pytest.raises(WeakPasswordError):
        validate_password(password)


def test_a_digit_is_required():
    with pytest.raises(WeakPasswordError):
        validate_password("harbourlantern")


def test_a_letter_is_required():
    """The natural pair to the digit rule.

    Without it "123456" satisfies "contains a digit" while being the single
    most common password in the world -- it would then be caught only by the
    blocklist, one rule deep instead of two.
    """
    with pytest.raises(WeakPasswordError):
        validate_password("907142")


def test_no_mix_of_cases_is_required():
    """A restriction on the allowed set is not a composition requirement.

    Requiring at least one of each kind is exactly the rule NIST SP 800-63B
    advises against; all-lowercase-plus-a-digit is valid.
    """
    validate_password("harbour7")
    validate_password("HARBOUR7")


# --- Repetition -----------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("111a11", id="one-letter-two-digits"),
        pytest.param("a1a1a1", id="two-characters-alternating"),
        pytest.param("aa11aa", id="three-distinct"),
    ],
)
def test_too_few_distinct_characters_is_refused(password):
    assert len(set(password)) < MINIMUM_DISTINCT_CHARACTERS
    with pytest.raises(RepetitivePasswordError):
        validate_password(password)


def test_exactly_the_distinct_character_minimum_is_accepted():
    password = "aa11b2"
    assert len(set(password)) == MINIMUM_DISTINCT_CHARACTERS
    validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x1234y", id="ascending-digits"),
        pytest.param("x4321y", id="descending-digits"),
        pytest.param("7wxyz8", id="ascending-letters"),
        pytest.param("7dcba8", id="descending-letters"),
        pytest.param("9abcdefgh", id="long-run"),
    ],
)
def test_long_sequential_runs_are_refused(password):
    with pytest.raises(RepetitivePasswordError):
        validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("x123y7", id="three-ascending-digits"),
        pytest.param("7abcx9", id="three-ascending-letters"),
    ],
)
def test_runs_at_the_allowed_length_are_accepted(password):
    """Three in a row is deliberately left alone.

    "abc" and "123" turn up inside plenty of passwords a person chose for
    their own reasons; refusing them would cost far more in rejected
    reasonable passwords than it buys. The famous three-plus-three case,
    "abc123", is caught by the blocklist instead -- where it belongs, because
    what makes it bad is that everybody picks it, not its shape.
    """
    assert MAXIMUM_SEQUENTIAL_RUN == 3
    validate_password(password)


# --- Blocklist ------------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("abc123", id="the-classic"),
        pytest.param("password1", id="word-plus-digit"),
        pytest.param("Passw0rd", id="leetspeak"),
        pytest.param("admin99", id="admin"),
        pytest.param("ward01", id="deployment-word"),
        pytest.param("nurse7", id="role-word"),
        pytest.param("1hospital", id="leading-digit"),
        pytest.param("BANGKOK7", id="uppercase-context-word"),
        pytest.param("l3tme1n", id="leet-letmein"),
    ],
)
def test_common_and_context_passwords_are_refused(password):
    with pytest.raises(CommonPasswordError):
        validate_password(password)


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("ward7bed12", id="contains-a-blocked-word-but-is-not-one"),
        pytest.param("harbour7lantern", id="ordinary-words"),
        pytest.param("kettle3window", id="ordinary-words-2"),
    ],
)
def test_the_blocklist_matches_whole_passwords_not_substrings(password):
    """"ward7bed12" is a perfectly good password and must stay one.

    Substring matching would refuse it for containing "ward", and would
    refuse a large share of the reasonable passwords this deployment's own
    vocabulary suggests. The list is compared against the whole normalised
    password only.
    """
    validate_password(password)


# --- Identifier -----------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        pytest.param("bme0017x", id="employee-code"),
        pytest.param("xsomchai9", id="given-name"),
        pytest.param("jaidee77", id="family-name"),
        pytest.param("SOMCHAI42", id="case-insensitive"),
    ],
)
def test_a_password_built_from_the_account_itself_is_refused(password):
    """The rule that matters most here.

    A colleague who can read a badge already knows the employee code and the
    name. In a ward, that is the realistic attacker -- not someone with the
    hash store.
    """
    with pytest.raises(PasswordContainsIdentifierError):
        validate_password(
            password,
            identifiers=("BME001", "Somchai Jaidee", "somchai.j@hospital.local"),
        )


def test_the_email_local_part_counts_but_the_domain_does_not():
    """Nobody's password is "@hospital.local", and refusing every password
    containing "local" would be absurd."""
    with pytest.raises(PasswordContainsIdentifierError):
        validate_password("xsomchai9", identifiers=("somchai.j@hospital.local",))

    validate_password("harbour7lantern", identifiers=("someone@hospital.local",))


def test_short_identifier_fragments_are_ignored():
    """Two-letter fragments would refuse ordinary passwords for no gain."""
    assert identifier_fragments("Al Vo", "x@y.z") == []
    validate_password("harbour7lantern", identifiers=("Al Vo",))


def test_identifiers_are_optional():
    """The policy is usable without an account -- which is what lets the
    bootstrap generator check its own output before handing it over."""
    validate_password(GOOD)
    validate_password(GOOD, identifiers=())


def test_a_none_identifier_does_not_crash():
    """`User.phone` and friends are nullable; passing one through must be a
    no-op rather than an AttributeError at the worst possible moment."""
    validate_password(GOOD, identifiers=(None, "", "BME001"))
