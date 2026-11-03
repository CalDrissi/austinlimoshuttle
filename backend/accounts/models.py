"""
Accounts.

Replaces two legacy tables: `limousin_member` (1,251 customers, passwords in
plaintext) and `limousin_admin` (a single shared staff login, also plaintext).

Legacy findings that shaped this module:
  * `email` was the login identity, compared with BINARY -- i.e. case-sensitive.
    All 1,251 addresses are distinct even when lowercased, so normalising to
    lowercase on import is safe and fixes the "Jo@x.com and jo@x.com are
    different accounts" trap.
  * `user_email` was populated in zero rows. Dropped.
  * Passwords cannot be migrated. There is no field here that could hold one in
    a recoverable form, and the importer never reads the legacy column.
"""

import secrets
from datetime import timedelta

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for the email-identified user model."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        # set_password(None) produces an unusable password, which is exactly
        # what imported legacy accounts need: they must reset before signing in.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """A customer or staff member. Email is the login identity."""

    class Title(models.TextChoices):
        NONE = "", "—"
        MR = "mr", "Mr"
        MRS = "mrs", "Mrs"
        MS = "ms", "Ms"
        MISS = "miss", "Miss"
        DR = "dr", "Dr"

    email = models.EmailField(
        "email address",
        max_length=254,
        unique=True,
        help_text="Login identity. Stored lowercase.",
    )
    title = models.CharField(
        max_length=10, choices=Title.choices, blank=True, default="",
        help_text="Legacy `pfix`.",
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(
        max_length=32, blank=True,
        help_text="Contact number used by dispatch.",
    )

    stripe_customer_id = models.CharField(
        max_length=64, blank=True, db_index=True,
        help_text="Stripe Customer, created the first time a card is saved. "
                  "Lets the customer reuse a card and lets staff charge it.",
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Unselect instead of deleting: bookings reference this row.",
    )
    is_staff = models.BooleanField(
        "staff status", default=False,
        help_text="Can sign in to the dashboard. Capabilities come from groups.",
    )

    marketing_opt_in = models.BooleanField(
        default=False,
        help_text="The legacy system recorded no consent, so imported accounts "
                  "default to false.",
    )

    legacy_member_id = models.IntegerField(
        null=True, blank=True, unique=True, db_index=True,
        help_text="`limousin_member.id`. Makes the import idempotent and keeps "
                  "a trail back to the old system.",
    )

    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["last_name", "first_name"])]

    def __str__(self):
        name = self.get_full_name()
        return f"{name} <{self.email}>" if name else self.email

    def save(self, *args, **kwargs):
        # Belt and braces: the manager lowercases, but objects created directly
        # (imports, factories, admin) must not bypass it.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def get_full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self) -> str:
        return self.first_name or self.email


class BillingAddress(models.Model):
    """
    A customer's billing address.

    Legacy spread this across five loosely-used columns on the member row
    (`bill_address`, `bill_street_name`, `bill_city`, `bill_zip`,
    `bill_country`) with no consistent convention for which held what.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="billing_addresses",
    )
    line1 = models.CharField(max_length=255, blank=True)
    line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(
        max_length=2, default="US",
        help_text="ISO 3166-1 alpha-2. Replaces the 240-row legacy country table.",
    )
    is_default = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "billing addresses"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        parts = [p for p in (self.line1, self.city, self.postal_code) if p]
        return ", ".join(parts) or f"Address #{self.pk}"


class CorporateAccount(models.Model):
    """
    A corporate account application.

    Legacy captured three of these in nine years and never connected them to
    billing, so this remains a record of interest rather than a billing entity.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="corporate_accounts",
        help_text="Applications may predate the account they belong to.",
    )
    company_name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    alt_phone = models.CharField(max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.company_name


class LoginCodeManager(models.Manager):
    """Issues and verifies one-time sign-in codes."""

    CODE_TTL = timedelta(minutes=10)

    def issue(self, email):
        """
        Create a fresh code for ``email`` and return ``(instance, raw_code)``.

        Any still-live code for the address is superseded first, so a second
        request does not leave two valid codes in flight. The six-digit value
        is returned to the caller to email and is never persisted in the clear.
        """
        email = (email or "").strip().lower()
        self.filter(email=email, used_at__isnull=True).update(
            used_at=timezone.now(),
        )
        raw = f"{secrets.randbelow(1_000_000):06d}"
        code = self.create(
            email=email,
            code_hash=make_password(raw),
            expires_at=timezone.now() + self.CODE_TTL,
        )
        return code, raw

    def verify(self, email, raw_code):
        """
        Return the matching :class:`LoginCode` for a correct guess, else None.

        The newest outstanding code for the address is the only candidate; the
        attempt is counted *before* the comparison so a flood of guesses burns
        the budget whether or not any is right, and a correct guess is consumed
        (``used_at`` stamped) so it cannot be replayed.
        """
        email = (email or "").strip().lower()
        raw_code = (raw_code or "").strip()
        code = (
            self.filter(email=email, used_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if code is None or not code.is_usable():
            return None

        code.attempts = models.F("attempts") + 1
        code.save(update_fields=["attempts"])
        code.refresh_from_db(fields=["attempts"])

        # check_password compares via the hasher, which is constant-time.
        if not check_password(raw_code, code.code_hash):
            return None

        code.used_at = timezone.now()
        code.save(update_fields=["used_at"])
        return code


class LoginCode(models.Model):
    """
    A one-time numeric code for passwordless storefront sign-in.

    The code is never stored in the clear -- only a salted hash, so a database
    read cannot reveal a live code and the comparison at verify time is
    constant-time. A row is single-use (``used_at`` is stamped the moment it
    verifies), expires after ten minutes, and counts verification attempts so
    the 10^6 space cannot be brute-forced within a code's short life.
    """

    MAX_ATTEMPTS = 5

    email = models.EmailField(db_index=True, help_text="Stored lowercase.")
    code_hash = models.CharField(
        max_length=255, help_text="Salted hash of the six-digit code.",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Stamped on a successful verify (or when superseded). "
                  "A stamped code is spent.",
    )
    attempts = models.PositiveSmallIntegerField(
        default=0, help_text="Failed/used verification attempts against this code.",
    )

    objects = LoginCodeManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "-created_at"])]

    def __str__(self):
        return f"login code for {self.email}"

    def is_usable(self) -> bool:
        return (
            self.used_at is None
            and self.attempts < self.MAX_ATTEMPTS
            and timezone.now() < self.expires_at
        )
