import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import settings
from app.core.security import create_access_token, dummy_password_hash, get_password_hash, verify_password
from app.exceptions import (
    DeleteSuperUserError,
    InvalidEmailOrPasswordError,
    PasswordIsWrongError,
    PasswordUnmodifiedError,
    UserExistsError,
    UserNotActiveError,
    UserNotAuthorizedError,
    UserNotFoundError,
)
from app.logging import get_logger
from app.models import (
    Message,
    PasswordUpdate,
    Token,
    TokenPayload,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.repositories.user import UserRepository
from app.services.email_outbox import EmailOutboxService
from app.services.household import INVITE_UNUSABLE_ERRORS
from app.utils import generate_new_account_email, generate_signup_attempt_email

logger = get_logger(__name__)

# What signup answers with, for an address that is free and for one that is taken alike. It has to
# read the same in both cases, so it promises mail rather than an account.
SIGNUP_MESSAGE = "Check your email. We sent a message to that address with what to do next."

if TYPE_CHECKING:
    from app.services.email_verification import EmailVerificationService
    from app.services.household import CategorySeeder, HouseholdService


class UserService:
    """Provide services for user management."""

    def __init__(self, session: Session, user_repository: UserRepository) -> None:
        """Initialize the user service.

        Args:
            session: The database session.
            user_repository: The user repository instance.
        """
        self.session = session
        self.user_repository = user_repository

    def authenticate(
        self, email: str, password: str, email_verification_service: "EmailVerificationService | None" = None
    ) -> Token:
        """Authenticate a user.

        Args:
            email: The user's email address.
            password: The user's password.
            email_verification_service: Optional email verification service to check verification status.

        Returns:
            A token for the authenticated user.

        Raises:
            InvalidEmailOrPasswordError: If no user has the given email, or the given password does not
                match the stored one. Both cases raise the same error on purpose, so that a caller cannot
                use the endpoint to find out which addresses have an account.
            UserNotActiveError: If the user is inactive.
        """
        user = self.get_user_by_email(email=email)

        if not user:
            # Check the password against a hash nobody holds, rather than returning here. Skipping the
            # hashing would answer sooner for an unregistered address, which is the same disclosure the
            # shared error avoids, told by the clock instead.
            verify_password(password, dummy_password_hash())
            raise InvalidEmailOrPasswordError from None

        if not verify_password(password, user.hashed_password):
            raise InvalidEmailOrPasswordError from None

        if not user.is_active:
            # Only a pending activation means the address is still waiting to be
            # confirmed. An account that asked to change address and was disabled
            # before the link came back is disabled, and telling its holder to go
            # and confirm something describes the wrong reason for the refusal.
            is_verified = True
            if email_verification_service:
                pending_activation = email_verification_service.get_pending_activation_by_user_id(user.id)
                is_verified = pending_activation is None

            raise UserNotActiveError(user=user, is_verified=is_verified) from None

        return Token(access_token=create_access_token(user.id))

    def create_user(
        self,
        user_create: UserCreate | UserRegister,
        category_service: "CategorySeeder",
        household_service: "HouseholdService | None" = None,
        hashed_password: str | None = None,
    ) -> UserPublic:
        """Create a new user.

        Args:
            user_create: The user creation data.
            category_service: The category service, used to seed the default
                categories of the new household. Required, so the household is
                never left without them.
            household_service: Optional household service. When given, a
                household is provisioned for the user in the same transaction,
                so a user is never observable without one.
            hashed_password: Optional hash of the submitted password, for a
                caller that has already paid for it. When given it is stored as
                it is, so the password is never hashed twice for one request.

        Note:
            An invitation the registration came through is neither read nor
            redeemed here: the user gets a household of their own either way. A
            registration is a claim on an address, not a proof of it, so the
            invitation is attributed only once the address is verified. Whether
            it could be applied at all is settled by `register_user`, before
            anything is written.

        Returns:
            The created user.

        Raises:
            UserExistsError: If a user with the same email already exists.
        """
        existing_user = self.get_user_by_email(email=user_create.email)
        if existing_user:
            raise UserExistsError(user=existing_user) from None

        if hashed_password is None:
            hashed_password = get_password_hash(user_create.password)

        extra_data: dict[str, Any] = {"hashed_password": hashed_password}

        # Set is_active=False for public signup (UserRegister), True for admin-created users (UserCreate)
        if isinstance(user_create, UserRegister):
            extra_data["is_active"] = False

        user = User.model_validate(user_create, update=extra_data)

        user = self.user_repository.save(user)

        if household_service:
            household_service.create_for_user(user=user, category_service=category_service)

        self.session.commit()

        # Only send welcome email for admin-created users who are immediately active
        # Public signup users will receive email verification instead.
        # The account is committed by now, so a greeting that cannot be
        # delivered is queued rather than reported as a failed creation.
        if isinstance(user_create, UserCreate) and settings.emails_enabled:
            email_data = generate_new_account_email(username=user.email)
            EmailOutboxService.for_session(self.session).deliver_or_queue(
                email_to=user.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )

        return UserPublic.model_validate(user)

    def register_user(
        self,
        user_register: UserRegister,
        category_service: "CategorySeeder",
        household_service: "HouseholdService",
        email_verification_service: "EmailVerificationService",
    ) -> Message:
        """Register a user through the public signup flow.

        The reply says the same thing whether or not the address already has an account, so the
        endpoint cannot be used to find out which addresses are registered. What happened is told
        to the address itself instead: a verification email for a new one, a notice that someone
        tried to sign up for one that is taken.

        An invitation that cannot be applied is dropped rather than reported, for the same reason:
        only a free address ever gets as far as reading the token, so an error about it would say
        which addresses are registered. The invitation is settled before anything is written, so
        dropping one costs a signup no writes it would not have done anyway. The verification email
        says the invitation was not applied, so that every signup sends exactly one message: a
        second send would cost another blocking HTTPS call to the mail provider and make the two
        paths tell themselves apart by the clock.

        The password is hashed once, here, before anything is looked up, and that one hash is used
        by whichever path follows. Every signup therefore pays exactly one bcrypt hash — the
        dominant cost of the request — so the clock says no more than the reply does. Hashing
        inside each path instead would charge a dropped invitation two hashes and a taken address
        one, and the difference would answer the question the shared reply refuses.

        Args:
            user_register: The registration data.
            category_service: The category service, used to seed the default categories of the
                new household.
            household_service: The household service, used to provision the household of the new
                user in the same transaction.
            email_verification_service: The email verification service, used to ask a new address
                to verify itself.

        Returns:
            The same message either way.
        """
        # Pay for the hash before the answer is known, so that no path can be told apart by how
        # much bcrypt work it did. Nothing stores it when the address turns out to be taken.
        hashed_password = get_password_hash(user_register.password)

        existing_user = self.get_user_by_email(email=user_register.email)

        if existing_user:
            self._handle_taken_address(user_register=user_register)
            return Message(message=SIGNUP_MESSAGE)

        invite_unusable = self._invitation_is_unusable(user_register=user_register, household_service=household_service)

        try:
            user = self.create_user(
                user_create=user_register,
                category_service=category_service,
                household_service=household_service,
                hashed_password=hashed_password,
            )
        except (UserExistsError, IntegrityError):
            # Two signups for the same free address can both get past the lookup above; whichever
            # one loses lands here, either on the check inside create_user or on the unique index.
            # It is told what any other attempt on a taken address is told, rather than the 409 that
            # would answer the question the shared reply exists to refuse.
            self.session.rollback()

            if not self.get_user_by_email(email=user_register.email):
                # The address is still free, so the write failed for some other reason: a constraint
                # on the household, the membership or the seeded categories. Reporting that as a
                # taken address would mail "you already have an account" to somebody who has none,
                # and would hide a real failure behind a 200.
                logger.exception("Signup failed for a reason other than the address being taken")
                raise

            self._handle_taken_address(user_register=user_register)
            return Message(message=SIGNUP_MESSAGE)

        # One message per signup, whatever happened. Each send blocks on an HTTPS call to the mail
        # provider, which costs far more than the single bcrypt hash above, so a second message for
        # the dropped invitation would make a free address measurably slower than a taken one and
        # the clock would answer the question the shared reply refuses. The verification email
        # carries the news about the invitation instead.
        email_verification_service.send_verification_email(
            user_service=self, user_email=user.email, invite_unusable=invite_unusable
        )

        return Message(message=SIGNUP_MESSAGE)

    def _invitation_is_unusable(
        self,
        user_register: UserRegister,
        household_service: "HouseholdService",
    ) -> bool:
        """Say whether the invitation a signup came through has to be dropped.

        An invitation is only ever read for an address that is free: one that is taken answers
        before the token is looked at. So letting an unusable token raise out of a signup would
        answer 404, 400 or 403 for a free address and the shared 200 for a taken one, and anyone
        posting a bogus token could read off which addresses are registered — the disclosure the
        shared reply exists to refuse. The token is settled here instead, before the account is
        written, and an unusable one only decides what the verification email says.

        Checking first rather than letting the write fail also means a dropped invitation writes
        the user, the household and the seeded categories exactly once, like every other signup,
        so the two paths cannot be told apart by how long the request took either.

        Args:
            user_register: The registration data.
            household_service: The household service, which owns the invitations.

        Returns:
            Whether the signup carried an invitation that could not be applied.
        """
        if not user_register.invite_token:
            return False

        try:
            household_service.check_signup_invite(email=user_register.email, token=user_register.invite_token)
        except INVITE_UNUSABLE_ERRORS:
            logger.info("Signup carried an invitation that could not be applied; creating the account without it")
            return True

        return False

    def _handle_taken_address(self, user_register: UserRegister) -> None:
        """Answer a signup for an address that already has an account.

        Nothing is created and nothing is said back to the caller. The address itself is told about
        the attempt by email, so the holder of the account learns of it and nobody else does.

        The password was already hashed by the caller, before the address was looked up, so this
        path has paid the same bcrypt cost as one that goes on to create an account even though
        nothing here will store the result.

        Args:
            user_register: The registration data for the address that is already taken.
        """
        # The address, and only the address, is told that it is taken. The notice carries no token,
        # so it says nothing to whoever typed the address that they did not already know. When the
        # attempt came from an invitation, it says so too: the invitation cannot be accepted by an
        # unauthenticated caller, so the holder is told it is still waiting for them.
        if settings.emails_enabled:
            email_data = generate_signup_attempt_email(
                email=user_register.email, invited=user_register.invite_token is not None
            )
            EmailOutboxService.for_session(self.session).deliver_or_queue(
                email_to=user_register.email,
                subject=email_data.subject,
                html_content=email_data.html_content,
            )

    def get_authenticated_user(self, token_data: TokenPayload) -> User:
        """Get the authenticated user from a token.

        Args:
            token_data: The token payload.

        Returns:
            The authenticated user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserNotActiveError: If the user is not active.
        """
        user_id = uuid.UUID(token_data.sub) if token_data.sub else None
        if not user_id:
            raise UserNotFoundError from None
        user = self.user_repository.get_by_id(user_id)
        if not user:
            raise UserNotFoundError from None
        if not user.is_active:
            raise UserNotActiveError(user) from None

        return user

    def get_user_by_email(self, email: str) -> User | None:
        """Get a user by their email address.

        Args:
            email: The user's email address.

        Returns:
            The user if found, otherwise None.
        """
        return self.user_repository.get_by_email(email)

    def get_user_by_id(self, current_user: User, user_id: uuid.UUID) -> UserPublic:
        """Get a user by ID.

        Args:
            current_user: The current authenticated user.
            user_id: The ID of the user to get.

        Returns:
            The retrieved user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserNotAuthorizedError: If the user is not a superuser and is trying to access another user's data.
        """
        user = self.user_repository.get_by_id(user_id)

        if not user:
            raise UserNotFoundError from None
        if user == current_user:
            return UserPublic.model_validate(user)
        if not current_user.is_superuser:
            raise UserNotAuthorizedError(current_user) from None

        return UserPublic.model_validate(user)

    def get_users(self, skip: int = 0, limit: int = 100) -> UsersPublic:
        """Get a sequence of registered users.

        Args:
            skip: The number of users to skip.
            limit: The maximum number of users to return.

        Returns:
            A tuple containing a sequence of users and the total number of users.
        """
        users, count = self.user_repository.get_all_paginated(skip=skip, limit=limit)
        return UsersPublic(data=[UserPublic.model_validate(user) for user in users], count=count)

    def update_user_me(
        self,
        current_user: User,
        user_update: UserUpdateMe,
        email_verification_service: "EmailVerificationService",
    ) -> UserPublic:
        """Update the current user's information.

        A new address is not written here. It is held in a pending
        verification and mailed a token; the account moves to it only once that
        token comes back. Until then the account keeps the address it has
        proven, which is the only one a password reset or a verification can be
        delivered to.

        Args:
            current_user: The current authenticated user.
            user_update: The user data to update.
            email_verification_service: An email verification service instance,
                used to ask the new address to prove itself.

        Returns:
            The updated user, still holding its current address.

        Raises:
            UserExistsError: If a user with the same email already exists.
        """
        user_data = user_update.model_dump(exclude_unset=True)

        # The address is the one field here that needs proving, so it is kept
        # out of what gets written and handled on its own.
        new_email = user_data.pop("email", None)
        email_changed = bool(new_email) and new_email != current_user.email

        if email_changed:
            existing_user = self.get_user_by_email(email=new_email)
            if existing_user and existing_user.id != current_user.id:
                raise UserExistsError(user=existing_user) from None

        current_user.sqlmodel_update(user_data)
        current_user = self.user_repository.save(current_user)
        self.session.commit()

        if email_changed:
            email_verification_service.send_email_change_verification(user=current_user, new_email=new_email)

        return UserPublic.model_validate(current_user)

    def update_user(self, user_id: uuid.UUID, user_update: UserUpdate) -> UserPublic:
        """Update a user's information.

        Args:
            user_id: The ID of the user to update.
            user_update: The user data to update.

        Returns:
            The updated user.

        Raises:
            UserNotFoundError: If the user is not found.
            UserExistsError: If a user with the same email already exists.
        """
        db_user = self.user_repository.get_by_id(user_id)

        if not db_user:
            raise UserNotFoundError from None
        if user_update.email:
            existing_user = self.get_user_by_email(email=user_update.email)
            if existing_user and existing_user.id != user_id:
                raise UserExistsError(user=existing_user) from None

        user_data = user_update.model_dump(exclude_unset=True)

        extra_data = {}
        if "password" in user_data:
            password = user_data["password"]
            hashed_password = get_password_hash(password)
            extra_data["hashed_password"] = hashed_password

        db_user.sqlmodel_update(user_data, update=extra_data)
        db_user = self.user_repository.save(db_user)
        self.session.commit()

        return UserPublic.model_validate(db_user)

    def update_password(self, user: User, password_update: PasswordUpdate) -> Message:
        """Update a user's password.

        Args:
            user: The user to update the password for.
            password_update: The password update data.

        Returns:
            A message indicating that the password was updated successfully.

        Raises:
            PasswordIsWrongError: If the current password is not correct.
            PasswordUnmodifiedError: If the new password is the same as the current password.
        """
        if not verify_password(password_update.current_password, user.hashed_password):
            raise PasswordIsWrongError from None
        if password_update.current_password == password_update.new_password:
            raise PasswordUnmodifiedError from None

        hashed_password = get_password_hash(password_update.new_password)
        user.hashed_password = hashed_password

        self.user_repository.save(user)
        self.session.commit()

        return Message(message="Password updated successfully.")

    def delete_user_me(self, user: User, household_service: "HouseholdService | None" = None) -> Message:
        """Delete the current user.

        Args:
            user: The current authenticated user.
            household_service: Optional household service. When given, the
                household the user leaves behind is released in the same
                transaction, so no household is left without a member.

        Returns:
            A message indicating that the user was deleted successfully.

        Raises:
            DeleteSuperUserError: If a superuser tries to delete their own account.
        """
        if user.is_superuser:
            raise DeleteSuperUserError from None

        if household_service:
            household_service.release_for_user(user=user)

        self.user_repository.delete(user)
        self.user_repository.flush()
        self.session.commit()

        if household_service:
            # A shared household the deleted user owned now belongs to somebody
            # who never asked for it. Announced here rather than above, because
            # queuing the mail commits, and the account was still there then.
            household_service.notify_new_owners()

        return Message(message="User deleted successfully.")

    def delete_user(self, user_id: uuid.UUID, household_service: "HouseholdService | None" = None) -> Message:
        """Delete a user.

        Args:
            user_id: The ID of the user to delete.
            household_service: Optional household service. When given, the
                household the user leaves behind is released in the same
                transaction, so no household is left without a member.

        Returns:
            A message indicating that the user was deleted successfully.

        Raises:
            UserNotFoundError: If the user is not found.
            DeleteSuperUserError: If trying to delete any superuser account.
        """
        user = self.user_repository.get_by_id(user_id)

        if not user:
            raise UserNotFoundError from None
        if user.is_superuser:
            raise DeleteSuperUserError from None

        if household_service:
            household_service.release_for_user(user=user)

        self.user_repository.delete(user)
        self.user_repository.flush()
        self.session.commit()

        if household_service:
            household_service.notify_new_owners()

        return Message(message="User deleted successfully")
