"""
The one-time sign-in code model.

Covers the storage and verification contract directly, independent of the API:
codes are hashed, six digits, single-use, expiring, and attempt-capped.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import LoginCode


@pytest.mark.django_db
class TestIssue:
    def test_returns_a_six_digit_code(self):
        _code, raw = LoginCode.objects.issue("rider@example.com")
        assert raw.isdigit() and len(raw) == 6

    def test_code_is_stored_hashed_not_in_the_clear(self):
        code, raw = LoginCode.objects.issue("rider@example.com")
        assert code.code_hash != raw
        assert raw not in code.code_hash

    def test_email_is_normalised_to_lowercase(self):
        code, _raw = LoginCode.objects.issue("RIDER@Example.COM")
        assert code.email == "rider@example.com"

    def test_issuing_again_supersedes_the_previous_code(self):
        first, first_raw = LoginCode.objects.issue("rider@example.com")
        LoginCode.objects.issue("rider@example.com")
        first.refresh_from_db()
        assert first.used_at is not None
        assert LoginCode.objects.verify("rider@example.com", first_raw) is None


@pytest.mark.django_db
class TestVerify:
    def test_correct_code_verifies_and_is_consumed(self):
        _code, raw = LoginCode.objects.issue("rider@example.com")
        match = LoginCode.objects.verify("rider@example.com", raw)
        assert match is not None
        assert match.used_at is not None
        # Second time: already spent.
        assert LoginCode.objects.verify("rider@example.com", raw) is None

    def test_wrong_code_fails(self):
        LoginCode.objects.issue("rider@example.com")
        assert LoginCode.objects.verify("rider@example.com", "000000") is None

    def test_expired_code_fails(self):
        code, raw = LoginCode.objects.issue("rider@example.com")
        LoginCode.objects.filter(pk=code.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert LoginCode.objects.verify("rider@example.com", raw) is None

    def test_attempts_are_capped(self):
        _code, raw = LoginCode.objects.issue("rider@example.com")
        for _ in range(LoginCode.MAX_ATTEMPTS):
            assert LoginCode.objects.verify("rider@example.com", "111111") is None
        # Correct code no longer helps once the attempt budget is gone.
        assert LoginCode.objects.verify("rider@example.com", raw) is None

    def test_unknown_address_fails_cleanly(self):
        assert LoginCode.objects.verify("nobody@example.com", "123456") is None
