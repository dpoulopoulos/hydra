"""What the token limit counts, verified against a real Postgres.

The unit suite mocks the session, so the predicate that leaves expired rows out
of the count is never executed and the limit is only ever as right as the mock
says it is. A user who mints ten short-lived tokens has to be able to mint an
eleventh once they lapse, and that answer lives entirely in SQL.
"""

import datetime
import uuid

import pytest
from sqlmodel import Session

from app.models import (
    MAX_ACTIVE_TOKENS_PER_USER,
    ApiToken,
    ApiTokenScope,
    ApiTokenStatus,
    HouseholdContext,
)
from app.repositories.api_token import ApiTokenRepository


@pytest.fixture
def api_token_repository(db_session: Session) -> ApiTokenRepository:
    """Build the repository under test.

    Args:
        db_session: The database session.

    Returns:
        A repository bound to the test's transaction.
    """
    return ApiTokenRepository(session=db_session)


def mint(
    session: Session,
    user_id: uuid.UUID,
    *,
    expires_at: datetime.datetime | None,
    status: ApiTokenStatus = ApiTokenStatus.ACTIVE,
) -> ApiToken:
    """Put one token row in the database.

    Args:
        session: The database session.
        user_id: Whose token it is.
        expires_at: When it lapses, or None to never.
        status: Whether it is still active.

    Returns:
        The saved row.
    """
    token = ApiToken(
        name="Claude",
        scope=ApiTokenScope.READ,
        status=status,
        expires_at=expires_at,
        token_id=uuid.uuid4().hex[:16],
        secret_hash="0" * 64,
        user_id=user_id,
    )
    session.add(token)
    session.flush()
    return token


class TestCountingWhatStillWorks:
    """Test which rows the per-user limit is measured over."""

    def test_an_expired_token_does_not_use_up_a_slot(
        self, db_session: Session, api_token_repository: ApiTokenRepository, household_a: HouseholdContext
    ) -> None:
        """A lapsed token must not lock its owner out of minting another."""
        # Arrange: Fill the allowance with tokens that all lapsed yesterday
        now = datetime.datetime.now(datetime.UTC)
        for _ in range(MAX_ACTIVE_TOKENS_PER_USER):
            mint(db_session, household_a.user.id, expires_at=now - datetime.timedelta(days=1))

        # Act: Count what still works
        count = api_token_repository.count_active_for_user(household_a.user.id, now=now)

        # Assert: None of them does
        assert count == 0

    def test_a_live_token_does(
        self, db_session: Session, api_token_repository: ApiTokenRepository, household_a: HouseholdContext
    ) -> None:
        """A token still within its life is counted."""
        # Arrange: One token good for another day
        now = datetime.datetime.now(datetime.UTC)
        mint(db_session, household_a.user.id, expires_at=now + datetime.timedelta(days=1))

        # Act & Assert: It counts
        assert api_token_repository.count_active_for_user(household_a.user.id, now=now) == 1

    def test_a_token_that_never_expires_does(
        self, db_session: Session, api_token_repository: ApiTokenRepository, household_a: HouseholdContext
    ) -> None:
        """A NULL expiry means forever, not lapsed."""
        # Arrange: One token with no expiry at all
        now = datetime.datetime.now(datetime.UTC)
        mint(db_session, household_a.user.id, expires_at=None)

        # Act & Assert: It counts, rather than being dropped by the NULL
        assert api_token_repository.count_active_for_user(household_a.user.id, now=now) == 1

    def test_a_revoked_token_does_not(
        self, db_session: Session, api_token_repository: ApiTokenRepository, household_a: HouseholdContext
    ) -> None:
        """Revoking frees the slot, as it always did."""
        # Arrange: A live token that has been revoked
        now = datetime.datetime.now(datetime.UTC)
        mint(
            db_session,
            household_a.user.id,
            expires_at=now + datetime.timedelta(days=1),
            status=ApiTokenStatus.REVOKED,
        )

        # Act & Assert: It does not count
        assert api_token_repository.count_active_for_user(household_a.user.id, now=now) == 0
