import datetime
from collections.abc import Sequence
from uuid import UUID

from sqlmodel import Session, col, func, select

from app.models import ApiToken, ApiTokenStatus
from app.repositories.base import BaseRepository


class ApiTokenRepository(BaseRepository[ApiToken]):
    """Repository for ApiToken database operations.

    A token belongs to a user rather than to a household, like a password
    reset. The household scope is derived afterwards, from the membership row,
    exactly as it is for a session.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the API token repository.

        Args:
            session: The database session.
        """
        super().__init__(session, ApiToken)

    def get_by_token_id(self, token_id: str) -> ApiToken | None:
        """Get a token by the lookup half of its credential.

        Args:
            token_id: The lookup half presented by the caller.

        Returns:
            The token if one carries that lookup id, None otherwise.
        """
        statement = select(ApiToken).where(ApiToken.token_id == token_id)
        return self.session.exec(statement).first()

    def get_for_user(self, token_id: UUID, user_id: UUID) -> ApiToken | None:
        """Get a token by ID, within one user.

        The user is part of the query rather than checked afterwards, so one
        person can never reach another person's token.

        Args:
            token_id: The primary key of the token.
            user_id: The ID of the user who must own it.

        Returns:
            The token if it exists and belongs to the user, None otherwise.
        """
        statement = select(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
        return self.session.exec(statement).first()

    def list_for_user(self, user_id: UUID, *, include_revoked: bool = False) -> Sequence[ApiToken]:
        """List the tokens of a user, newest first.

        Args:
            user_id: The ID of the user.
            include_revoked: Whether revoked tokens are listed as well.

        Returns:
            The tokens.
        """
        statement = select(ApiToken).where(ApiToken.user_id == user_id)
        if not include_revoked:
            statement = statement.where(ApiToken.status == ApiTokenStatus.ACTIVE)

        return self.session.exec(statement.order_by(ApiToken.created_at.desc())).all()  # type: ignore[attr-defined]

    def count_active_for_user(self, user_id: UUID, *, now: datetime.datetime) -> int:
        """Count the tokens of a user that still work.

        Expiry is checked here rather than left to the status, which is only
        ever flipped by a revoke. Counting an expired row would let ten
        short-lived tokens lock a user out of minting an eleventh forever,
        although none of the ten opens anything.

        Args:
            user_id: The ID of the user.
            now: The moment to measure expiry against.

        Returns:
            How many usable tokens the user holds.
        """
        statement = (
            select(func.count())
            .select_from(ApiToken)
            .where(
                ApiToken.user_id == user_id,
                ApiToken.status == ApiTokenStatus.ACTIVE,
                col(ApiToken.expires_at).is_(None) | (col(ApiToken.expires_at) > now),
            )
        )
        return self.session.exec(statement).one()

    def touch_last_used(self, api_token: ApiToken, now: datetime.datetime) -> ApiToken:
        """Record that a token was just used.

        Flushes but does not commit, as every write in this layer does.

        Args:
            api_token: The token that was used.
            now: The moment to record.

        Returns:
            The updated token.
        """
        api_token.last_used_at = now
        return self.save(api_token)

    def revoke(self, api_token: ApiToken) -> ApiToken:
        """Revoke a token.

        A status flip rather than a delete, so the record of when the token was
        last used survives its revocation.

        Args:
            api_token: The token to revoke.

        Returns:
            The revoked token.
        """
        api_token.status = ApiTokenStatus.REVOKED
        return self.save(api_token)
