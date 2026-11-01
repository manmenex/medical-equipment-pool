"""The password rules, in one place, as pure functions.

Separate from auth_service because these rules are decided by the Owner and
change on their own schedule (this file is on its third revision in a day),
while the change-password flow around them does not. Keeping them here means
one home to read, one home to test, and no DB session required to exercise
any of it.

---------------------------------------------------------------------------
WHY THESE RULES, AT SIX CHARACTERS
---------------------------------------------------------------------------

The Owner set the minimum at 6 and required a digit. Six characters is short,
so it is worth being explicit about what that does and does not buy, rather
than implying the rules make short passwords safe.

**Composition rules do very little against a real attacker.** Requiring a
digit removes "password" and "abcdef" from play, and that is genuinely worth
having -- but an attacker guessing "123456", "admin1" or "ward01" is not
inconvenienced by it at all. NIST SP 800-63B is explicit that screening
against known-bad passwords beats composition rules, and at this length that
gap is wider, not narrower.

So the rules below are weighted accordingly:

  * the structural rules (length, character set, needs a digit, needs a
    letter) are cheap, are mirrored in the form for instant feedback, and
    mostly stop honest mistakes;
  * the rules that actually stop guessing are REPETITION, BLOCKLIST and
    IDENTIFIER -- and the last is the important one in a hospital, where
    every colleague can read the employee code off a badge.

**What these rules cannot do.** They cannot stop online guessing, because
nothing in this application limits login attempts -- there is no rate limit
and no lockout (verified: no such code exists as of this revision). Against
someone sitting at a ward workstation trying the fifty most likely passwords
for a colleague whose employee code they can see, the blocklist and the
identifier rule are the entire defence. A login throttle would be worth more
than every rule in this file combined, and is recorded as the outstanding
gap in docs/DECISION_LOG.md rather than quietly assumed away.
"""
import re
from collections.abc import Iterable

from app.core.exceptions import DomainError


class WeakPasswordError(DomainError):
    """Structural: length, character set, missing digit or letter."""

    code = "WEAK_PASSWORD"
    status_code = 400


class RepetitivePasswordError(DomainError):
    """"aaaa11", "123456", "abcdef" -- technically conforming, trivially
    guessable."""

    code = "PASSWORD_TOO_REPETITIVE"
    status_code = 400


class CommonPasswordError(DomainError):
    """On the curated list of passwords people actually choose."""

    code = "PASSWORD_TOO_COMMON"
    status_code = 400


class PasswordContainsIdentifierError(DomainError):
    """Built from the account's own employee code, name or email -- the
    first thing a colleague who can see a badge would try."""

    code = "PASSWORD_CONTAINS_IDENTIFIER"
    status_code = 400


# --- Structural -----------------------------------------------------------

# Owner decision. Below NIST SP 800-63B's recommended 8 for user-chosen
# secrets; see docs/DECISION_LOG.md for the accepted risk.
MINIMUM_PASSWORD_LENGTH = 6

# NOT a policy choice: bcrypt.hashpw raises ValueError above 72 bytes
# (verified against the pinned bcrypt 5.0.0). Without this the request is an
# unhandled HTTP 500. Kept as a byte count because that is what bcrypt
# measures -- identical to a character count while the set below is ASCII,
# and still correct if that set is ever widened.
MAXIMUM_PASSWORD_BYTES = 72

# Owner decision: English letters and digits. "Not Thai" is the requirement;
# excluding symbols as well is the earlier Owner decision this preserves,
# and it keeps the set to one byte per character.
_ALLOWED_PATTERN = re.compile(r"^[A-Za-z0-9]+$")
ALLOWED_PASSWORD_DESCRIPTION = "English letters (a-z, A-Z) and digits (0-9) only"

# Owner decision: at least one digit. A letter is required as its natural
# pair -- without it "123456" satisfies "has a digit" while being the single
# most common password in the world. Note this is still NOT a full
# composition rule: no uppercase requirement, no symbol requirement, and any
# arrangement is fine.
_DIGIT = re.compile(r"[0-9]")
_LETTER = re.compile(r"[A-Za-z]")

# --- Repetition -----------------------------------------------------------

# "112211" and "aaa111" pass every structural rule above. Four distinct
# characters is the cheapest rule that removes them without touching
# anything a person would plausibly choose on purpose.
MINIMUM_DISTINCT_CHARACTERS = 4

# Four or more consecutive code points in either direction: "1234", "4321",
# "wxyz", "dcba". Three is left alone deliberately -- "abc" and "123" appear
# inside plenty of reasonable passwords, and "abc123" is caught by the
# blocklist instead, where it belongs.
MAXIMUM_SEQUENTIAL_RUN = 3

# --- Blocklist ------------------------------------------------------------

# NOT a dictionary. A dictionary would reject "harbour7" while an attacker
# has no particular reason to try it; this is a curated list of what people
# actually pick, plus the words this specific deployment invites. Checked
# against the whole normalised password, never as a substring -- "ward7bed12"
# is a fine password and must stay one.
_COMMON_PASSWORDS = frozenset(
    {
        # The perennial top of every breach corpus.
        "password", "passwd", "123456", "12345", "1234567", "12345678",
        "123456789", "1234567890", "qwerty", "qwertyuiop", "asdfgh",
        "zxcvbn", "abc123", "letmein", "welcome", "iloveyou", "monkey",
        "dragon", "sunshine", "princess", "football", "baseball", "master",
        "shadow", "superman", "trustno", "starwars", "whatever", "freedom",
        "computer", "internet", "samsung", "google",
        # Credentials people set "temporarily".
        "admin", "administrator", "root", "user", "guest", "test", "testing",
        "temp", "temporary", "changeme", "change", "default", "secret",
        "login", "logon", "pass", "demo", "sample", "example", "new",
        "reset", "initial", "first", "start",
        # What this deployment itself suggests, on the screen the user is
        # looking at while choosing.
        "hospital", "clinic", "nurse", "nursing", "doctor", "patient",
        "ward", "bed", "equipment", "medical", "device", "pool", "borrow",
        "return", "scan", "staff", "bme", "mep",
        # Thailand-context choices for a Thai deployment.
        "thailand", "thai", "bangkok", "krungthep", "sawasdee", "sabaidee",
    }
)

# Applied only to the blocklist comparison, never to the stored password.
_LEET_FOLD = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})

_LEADING_DIGITS = re.compile(r"^[0-9]+")
_TRAILING_DIGITS = re.compile(r"[0-9]+$")

# --- Identifier -----------------------------------------------------------

# Shorter fragments than this produce false positives against ordinary
# passwords ("be", "an") without meaningfully helping a guesser.
MINIMUM_IDENTIFIER_FRAGMENT = 3


def _normalisation_candidates(password: str) -> set[str]:
    """Every form of the password worth comparing to the blocklist.

    "Ward01", "ward1", "w4rd" and "ward" are one password as far as a
    guesser is concerned; comparing only the literal string would catch the
    last of those and none of the rest.
    """
    lowered = password.lower()
    stripped = _TRAILING_DIGITS.sub("", _LEADING_DIGITS.sub("", lowered))
    candidates = {lowered, stripped}
    candidates |= {form.translate(_LEET_FOLD) for form in (lowered, stripped)}
    return {form for form in candidates if form}


def _has_long_sequential_run(password: str) -> bool:
    run_up = run_down = 1
    for previous, current in zip(password, password[1:]):
        step = ord(current) - ord(previous)
        run_up = run_up + 1 if step == 1 else 1
        run_down = run_down + 1 if step == -1 else 1
        if max(run_up, run_down) > MAXIMUM_SEQUENTIAL_RUN:
            return True
    return False


def identifier_fragments(*values: str | None) -> list[str]:
    """Splits account identifiers into the pieces worth refusing.

    An email is reduced to its local part (nobody's password is
    "@hospital.local"), and names are split into words so "somchai2540" is
    caught for Somchai Jaidee without having to match the whole name.
    """
    fragments: list[str] = []
    for value in values:
        if not value:
            continue
        local_part = value.split("@", 1)[0]
        for token in re.split(r"[^A-Za-z0-9]+", local_part):
            if len(token) >= MINIMUM_IDENTIFIER_FRAGMENT:
                fragments.append(token.lower())
    return fragments


def validate_password(new_password: str, *, identifiers: Iterable[str | None] = ()) -> None:
    """Raises the specific DomainError for the first rule the password fails.

    Each rule has its own error code rather than one catch-all, so the form
    can say which rule was broken in the user's own language instead of
    making them guess. `identifiers` is the account's own employee code,
    full name and email; passing nothing skips only the identifier rule.
    """
    if not new_password or len(new_password) < MINIMUM_PASSWORD_LENGTH:
        raise WeakPasswordError(
            f"New password must be at least {MINIMUM_PASSWORD_LENGTH} characters long."
        )
    if new_password.strip() != new_password:
        # Checked before the character rule purely so the message is the
        # useful one: "there is a space at the start" is actionable, while
        # "invalid character" sends the user hunting for something
        # invisible.
        raise WeakPasswordError("New password must not start or end with whitespace.")
    if not _ALLOWED_PATTERN.fullmatch(new_password):
        raise WeakPasswordError(
            f"New password must use {ALLOWED_PASSWORD_DESCRIPTION}. "
            "Spaces, punctuation, symbols and non-English characters are not accepted."
        )
    if len(new_password.encode("utf-8")) > MAXIMUM_PASSWORD_BYTES:
        raise WeakPasswordError(
            f"New password must be at most {MAXIMUM_PASSWORD_BYTES} characters. "
            "This is a limit of the password hashing algorithm, not a policy choice."
        )
    if not _DIGIT.search(new_password):
        raise WeakPasswordError("New password must contain at least one digit (0-9).")
    if not _LETTER.search(new_password):
        raise WeakPasswordError("New password must contain at least one letter (a-z, A-Z).")

    if len(set(new_password)) < MINIMUM_DISTINCT_CHARACTERS:
        raise RepetitivePasswordError(
            f"New password must use at least {MINIMUM_DISTINCT_CHARACTERS} different "
            "characters. Repeating a few characters makes a password easy to guess."
        )
    if _has_long_sequential_run(new_password):
        raise RepetitivePasswordError(
            "New password must not contain a run of more than "
            f"{MAXIMUM_SEQUENTIAL_RUN} characters in order, such as \"1234\" or \"wxyz\"."
        )

    if _normalisation_candidates(new_password) & _COMMON_PASSWORDS:
        raise CommonPasswordError(
            "New password is one of the passwords most commonly chosen, or a simple "
            "variation of one. Choose something a stranger would not guess in ten tries."
        )

    lowered = new_password.lower()
    for fragment in identifier_fragments(*identifiers):
        if fragment in lowered:
            raise PasswordContainsIdentifierError(
                "New password must not contain your employee code, name or email "
                "address. Anyone who can read your badge could guess it."
            )
