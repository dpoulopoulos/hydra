import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlmodel import Session

from app.core.config import settings
from app.core.security import TokenType, create_typed_token
from app.exceptions import (
    HouseholdInviteEmailMismatchError,
    HouseholdInviteExistsError,
    HouseholdInviteExpiredError,
    HouseholdInviteNotFoundError,
    HouseholdInviteUnclaimedError,
    HouseholdInviteUsedError,
    HouseholdMemberExistsError,
    HouseholdMemberNotFoundError,
    HouseholdMembershipNotFoundError,
    HouseholdNotEmptyError,
    HouseholdNotFoundError,
    LastHouseholdOwnerError,
)
from app.models import (
    EmailOutboxStatus,
    Household,
    HouseholdContext,
    HouseholdInvite,
    HouseholdInviteCreate,
    HouseholdInvitePreview,
    HouseholdInvitePublic,
    HouseholdInvitesPublic,
    HouseholdInviteStatus,
    HouseholdMember,
    HouseholdMemberPublic,
    HouseholdMembersPublic,
    HouseholdMemberUpdate,
    HouseholdPublic,
    HouseholdRole,
    HouseholdUpdate,
    Message,
    User,
)
from app.repositories.email_verification import EmailVerificationRepository
from app.repositories.household import (
    HouseholdInviteRepository,
    HouseholdMemberRepository,
    HouseholdRepository,
)
from app.repositories.user import UserRepository
from app.services.email_outbox import EmailOutboxService
from app.utils import generate_household_invite_email, generate_household_ownership_email, mask_email

# Every way an invitation offered at signup can turn out to be unusable. Kept next to
# `HouseholdService.check_signup_invite`, which is the only thing that raises them, so a refusal
# added there cannot go missing from the callers that must not report it back.
INVITE_UNUSABLE_ERRORS = (
    HouseholdInviteNotFoundError,
    HouseholdInviteUsedError,
    HouseholdInviteExpiredError,
    HouseholdInviteEmailMismatchError,
)


@dataclass(frozen=True, slots=True)
class OwnerPromotion:
    """A member the household was handed to, waiting to be told about it.

    Held as plain values rather than as rows: the notice goes out after the
    promotion is committed, and by then the membership it came from may have
    been expired from the session.
    """

    email: str
    household_name: str
    # Who left, when the promotion followed somebody's departure. The startup
    # repair finds households that were already ownerless and has nobody to name.
    former_owner_name: str | None


class CategorySeeder(Protocol):
    """The part of the category service that household provisioning depends on.

    Typed as a protocol so this service does not import the category service,
    which would make the two mutually dependent.
    """

    def seed_defaults(self, household_id: uuid.UUID) -> None:
        """Create the default categories of a household, without committing.

        Args:
            household_id: The ID of the household to seed.
        """
        ...


def default_household_name(user: User) -> str:
    """Build the name of the household provisioned for a new user.

    Args:
        user: The user the household is created for.

    Returns:
        A display name based on the user's name, or their email if they have none.
    """
    return f"{user.full_name or user.email}'s household"


class HouseholdService:
    """Provide services for household and membership management."""

    def __init__(
        self,
        session: Session,
        household_repository: HouseholdRepository,
        household_member_repository: HouseholdMemberRepository,
        household_invite_repository: HouseholdInviteRepository,
        user_repository: UserRepository,
        email_verification_repository: EmailVerificationRepository,
    ) -> None:
        """Initialize the household service.

        Args:
            session: The database session.
            household_repository: The household repository instance.
            household_member_repository: The household member repository instance.
            household_invite_repository: The household invite repository instance.
            user_repository: The user repository instance, used to resolve invited addresses to accounts.
            email_verification_repository: The email verification repository instance, used to tell
                an address somebody has proved they hold from one they have only claimed.
        """
        self.session = session
        self.household_repository = household_repository
        self.household_member_repository = household_member_repository
        self.household_invite_repository = household_invite_repository
        self.user_repository = user_repository
        self.email_verification_repository = email_verification_repository
        # Promotions made in this session that nobody has been told about yet.
        # Queuing the mail writes to the outbox and commits, so a notice sent
        # from inside `_ensure_an_owner` would commit whatever transaction its
        # caller is still building - the deletion of a user, say, before the
        # user row itself is gone.
        self._promotions: list[OwnerPromotion] = []

    def get_context(self, user: User) -> HouseholdContext:
        """Resolve the household scope of a user.

        Args:
            user: The authenticated user.

        Returns:
            The household context of the request.

        Raises:
            HouseholdMembershipNotFoundError: If the user belongs to no household.
        """
        membership = self.household_member_repository.get_by_user_id(user.id)

        if not membership:
            raise HouseholdMembershipNotFoundError from None

        return HouseholdContext(
            user=user,
            household_id=membership.household_id,
            membership_id=membership.id,
            role=membership.role,
        )

    def provision_for_user(
        self,
        user: User,
        category_service: CategorySeeder,
        name: str | None = None,
    ) -> HouseholdPublic:
        """Create a household for a user and make them its owner.

        Called at signup, so a user always has a household from the moment their
        account exists. That keeps `household_id` non-nullable everywhere and
        spares the frontend an "onboarding required" state.

        Args:
            user: The user to provision a household for.
            category_service: The category service, used to seed the default
                categories in the same transaction. A household is never
                observable without its categories, so this is required.
            name: An optional household name. Defaults to a name based on the user.

        Returns:
            The created household.

        Raises:
            HouseholdMemberExistsError: If the user already belongs to a household.
        """
        if self.household_member_repository.get_by_user_id(user.id):
            raise HouseholdMemberExistsError(email=user.email) from None

        household = self.create_for_user(user=user, name=name, category_service=category_service)
        self.session.commit()

        return self._to_public(household=household, member_count=1)

    def get_household(self, household: HouseholdContext) -> HouseholdPublic:
        """Get the household of the current request.

        Args:
            household: The household context.

        Returns:
            The household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        return self._to_public(
            household=self._require_household(household),
            member_count=self.household_repository.count_members(household.household_id),
        )

    def update_household(self, household: HouseholdContext, household_update: HouseholdUpdate) -> HouseholdPublic:
        """Rename the household.

        Args:
            household: The household context.
            household_update: The fields to update.

        Returns:
            The updated household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        entity = self._require_household(household)
        entity.sqlmodel_update(household_update.model_dump(exclude_unset=True))
        self.household_repository.save(entity)
        self.session.commit()

        return self._to_public(
            household=entity,
            member_count=self.household_repository.count_members(household.household_id),
        )

    def list_members(self, household: HouseholdContext) -> HouseholdMembersPublic:
        """List the members of the household.

        Args:
            household: The household context.

        Returns:
            The members, with the email and name of each.
        """
        rows = self.household_member_repository.list_with_users(household.household_id)
        data = [self._member_to_public(membership=membership, user=user) for membership, user in rows]

        return HouseholdMembersPublic(data=data, count=len(data))

    def update_member(
        self, household: HouseholdContext, user_id: uuid.UUID, member_update: HouseholdMemberUpdate
    ) -> HouseholdMemberPublic:
        """Change the role of a household member.

        Args:
            household: The household context.
            user_id: The ID of the user whose role changes.
            member_update: The new role.

        Returns:
            The updated membership.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
            LastHouseholdOwnerError: If the change would leave the household with no owner.
        """
        membership, user = self._require_member(household=household, user_id=user_id)

        if membership.role is HouseholdRole.OWNER and member_update.role is not HouseholdRole.OWNER:
            self._require_another_owner(household=household)

        membership.role = member_update.role
        # Somebody chose this role for them, so the household is no longer
        # running on the member it fell to, whichever way the role went.
        membership.promoted_to_owner_at = None
        self.household_member_repository.save(membership)
        self.session.commit()

        return self._member_to_public(membership=membership, user=user)

    def remove_member(
        self, household: HouseholdContext, user_id: uuid.UUID, category_service: CategorySeeder
    ) -> Message:
        """Remove a member from the household.

        The removed member keeps their account and is given a fresh, empty
        household, so the "every user has a household" invariant still holds.

        Args:
            household: The household context.
            user_id: The ID of the user to remove.
            category_service: The category service, used to seed the categories
                of the replacement household.

        Returns:
            A confirmation message.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
            LastHouseholdOwnerError: If the removal would leave the household with no owner.
        """
        membership, user = self._require_member(household=household, user_id=user_id)

        if membership.role is HouseholdRole.OWNER:
            self._require_another_owner(household=household)

        self._detach(membership=membership, user=user, category_service=category_service)

        return Message(message="Member removed from the household.")

    def leave_household(self, household: HouseholdContext, category_service: CategorySeeder) -> Message:
        """Leave the household.

        Args:
            household: The household context.
            category_service: The category service, used to seed the categories
                of the replacement household.

        Returns:
            A confirmation message.

        Raises:
            HouseholdMemberNotFoundError: If the membership no longer exists.
            LastHouseholdOwnerError: If the caller is the household's only owner.
        """
        if household.is_owner:
            self._require_another_owner(household=household)

        membership, user = self._require_member(household=household, user_id=household.user_id)
        self._detach(membership=membership, user=user, category_service=category_service)

        return Message(message="You have left the household.")

    def release_for_user(self, user: User) -> None:
        """Give up the household of a user who is being deleted, without committing.

        The caller owns the transaction, so the user row and everything their
        household held go in one go.

        Deleting the user would cascade their membership away on its own, but
        never the household: accounts, transactions, budgets and recurring
        rules are keyed on the household, not on the user, so a sole member's
        ledger would survive with nobody left who could reach it. Their
        household therefore leaves with them, and its financial data cascades
        with it, which is what deleting an account promises.

        A household with other members in it stays: the data is theirs too,
        and if the departing user was its last owner one of them is promoted,
        so the household never ends up with nobody who can run it. Telling that
        member is left to `notify_new_owners`, which the caller runs once the
        deletion is committed, so the news never goes out for a deletion that
        did not happen.

        Args:
            user: The user whose account is being deleted.
        """
        membership = self.household_member_repository.get_by_user_id(user.id)

        if not membership:
            return

        self._release_membership(membership, departing=user)

    def ensure_every_user_has_a_household(self, category_service: CategorySeeder) -> int:
        """Provision a household for every user that does not have one.

        Run at startup. Accounts that existed before households did, and any
        account whose provisioning failed part way, are repaired here rather
        than from a migration, so the default categories are seeded by the same
        business logic that seeds them at signup.

        Args:
            category_service: The category service, used to seed the default categories.

        Returns:
            The number of households created.
        """
        users = self.household_member_repository.list_users_without_a_household()

        if not users:
            return 0

        for user in users:
            self.create_for_user(user=user, category_service=category_service)

        self.session.commit()

        return len(users)

    def ensure_every_household_has_an_owner(self) -> int:
        """Give an owner back to every household that has members but none.

        Run at startup, next to the household repair. A household that lost
        its last owner before the deletion path promoted a successor is stuck
        for good: renaming it, inviting, promoting and removing members are
        all owner-only, so no request its members can make repairs it.

        Returns:
            The number of households given an owner.
        """
        household_ids = self.household_member_repository.list_ownerless_household_ids()

        if not household_ids:
            return 0

        for household_id in household_ids:
            self._ensure_an_owner(household_id=household_id)

        self.session.commit()
        self.notify_new_owners()

        return len(household_ids)

    def create_for_user(
        self,
        user: User,
        category_service: CategorySeeder,
        name: str | None = None,
    ) -> Household:
        """Give a user a household, without committing.

        The caller owns the transaction, so signing up can create the user, the
        household and its categories together. A user is therefore never
        observable without a household.

        A user who registered through an invitation gets a household of their
        own here like anybody else. Signing up proves nothing about the address
        it was signed up with, so the invitation stays pending and is
        attributed when the address is verified, which is the moment the
        mailbox stops being a claim. Whether the invitation could be applied at
        all is settled by `check_signup_invite`, before anything is written.

        Args:
            user: The user to give a household to.
            category_service: The category service, used to seed the default
                categories. Required, so a household cannot be created without
                them by forgetting an argument.
            name: An optional household name. Defaults to a name based on the user.

        Returns:
            The household the user now belongs to.
        """
        household = Household(name=name or default_household_name(user))
        self.household_repository.save(household)

        membership = HouseholdMember(household_id=household.id, user_id=user.id, role=HouseholdRole.OWNER)
        self.household_member_repository.save(membership)

        category_service.seed_defaults(household_id=household.id)

        return household

    def _detach(self, membership: HouseholdMember, user: User, category_service: CategorySeeder) -> None:
        """Remove a membership and provision a replacement household, in one transaction.

        Args:
            membership: The membership to remove.
            user: The user the membership belongs to.
            category_service: The category service, used to seed the default categories.
        """
        self._release_membership(membership, departing=user)
        self.create_for_user(user=user, category_service=category_service)
        self.session.commit()
        self.notify_new_owners()

    def _release_membership(self, membership: HouseholdMember, departing: User | None = None) -> None:
        """Remove a membership and leave its household in a usable state.

        Every way out of a household comes through here, so the household is
        locked first: two members going at the same time would otherwise each
        see the other still in place, and the household they both left would
        survive with nobody in it.

        With the lock held, the household is re-read after the membership is
        gone. An empty one is deleted, since nothing could reach it or its
        ledger again. One that still has members but lost its last owner gets
        a new one, or every owner-only route would fail forever and the
        members left could only leave, stranding it after all.

        Args:
            membership: The membership to remove.
            departing: The member who is leaving, so a promotion made here can
                name whose exit caused it.
        """
        household = self.household_repository.get_by_id_for_update(membership.household_id)
        self.household_member_repository.delete(membership)
        self.household_member_repository.flush()

        if not household:
            return

        if self.household_repository.count_members(household.id) == 0:
            self.household_repository.delete(household)
            self.household_repository.flush()
            return

        self._ensure_an_owner(household_id=household.id, departing=departing)

    def _ensure_an_owner(self, household_id: uuid.UUID, departing: User | None = None) -> None:
        """Promote the longest-standing member if the household has no owner.

        The promotion is noted so the member can be told about it once it is
        committed. Nobody asked them, and an owner who is not aware of it
        finds out from buttons that were not there the day before.

        Args:
            household_id: The ID of the household.
            departing: The member whose exit left the household ownerless, when
                there is one. The startup repair has nobody to name.
        """
        if self.household_member_repository.count_by_role(household_id, HouseholdRole.OWNER) > 0:
            return

        successor = self.household_member_repository.get_longest_standing(household_id)

        if not successor:
            return

        successor.role = HouseholdRole.OWNER
        successor.promoted_to_owner_at = datetime.now(UTC)
        self.household_member_repository.save(successor)
        self._record_promotion(household_id=household_id, successor=successor, departing=departing)

    def _record_promotion(self, household_id: uuid.UUID, successor: HouseholdMember, departing: User | None) -> None:
        """Note a promotion so `notify_new_owners` can announce it after the commit.

        Args:
            household_id: The ID of the household that was handed over.
            successor: The membership that was given the owner role.
            departing: The member whose exit left it ownerless, when there is one.
        """
        promoted = self.household_member_repository.get_user(successor.user_id)
        household = self.household_repository.get_by_id(household_id)

        if not promoted or not household:
            return

        self._promotions.append(
            OwnerPromotion(
                email=promoted.email,
                household_name=household.name,
                former_owner_name=(departing.full_name or departing.email) if departing else None,
            )
        )

    def notify_new_owners(self) -> None:
        """Tell the members this session promoted that their household is now theirs.

        Called by whoever owns the transaction, once it is committed: the
        outbox commits the session to write a message down, so announcing a
        promotion any earlier would also commit the half-built write that
        caused it.

        Nothing is raised here. The mail is queued through the outbox, which
        keeps a message the provider refused and retries it, and a promotion
        that happened is not undone because the news about it did not leave.
        """
        promotions, self._promotions = self._promotions, []

        if not settings.emails_enabled:
            return

        outbox = EmailOutboxService.for_session(self.session)

        for promotion in promotions:
            email_data = generate_household_ownership_email(
                email=promotion.email,
                household_name=promotion.household_name,
                former_owner_name=promotion.former_owner_name,
            )
            outbox.deliver_or_queue(
                email_to=promotion.email, subject=email_data.subject, html_content=email_data.html_content
            )

    def _require_household(self, household: HouseholdContext) -> Household:
        """Load the household of the current request.

        Args:
            household: The household context.

        Returns:
            The household.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        entity = self.household_repository.get_by_id(household.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        return entity

    def _require_member(self, household: HouseholdContext, user_id: uuid.UUID) -> tuple[HouseholdMember, User]:
        """Load a membership within the household of the current request.

        Args:
            household: The household context.
            user_id: The ID of the user whose membership to load.

        Returns:
            The membership and the user it belongs to.

        Raises:
            HouseholdMemberNotFoundError: If the user is not a member of the household.
        """
        row = self.household_member_repository.get_with_user(household_id=household.household_id, user_id=user_id)

        if not row:
            raise HouseholdMemberNotFoundError from None

        return row

    def _require_another_owner(self, household: HouseholdContext) -> None:
        """Check that the household would still have an owner.

        Args:
            household: The household context.

        Raises:
            LastHouseholdOwnerError: If the household has only one owner.
        """
        if self.household_member_repository.count_by_role(household.household_id, HouseholdRole.OWNER) <= 1:
            raise LastHouseholdOwnerError from None

    def _to_public(self, household: Household, member_count: int) -> HouseholdPublic:
        """Build the public representation of a household.

        Args:
            household: The household.
            member_count: The number of members it has.

        Returns:
            The public household.
        """
        return HouseholdPublic.model_validate(household, update={"member_count": member_count})

    def _member_to_public(self, membership: HouseholdMember, user: User) -> HouseholdMemberPublic:
        """Build the public representation of a membership.

        Args:
            membership: The membership.
            user: The user it belongs to.

        Returns:
            The public membership.
        """
        return HouseholdMemberPublic.model_validate(
            membership, update={"email": user.email, "full_name": user.full_name}
        )

    def create_invite(self, household: HouseholdContext, invite_create: HouseholdInviteCreate) -> HouseholdInvitePublic:
        """Invite someone to share the household, and email them a link.

        Args:
            household: The household context.
            invite_create: The address to invite and the role to give them.

        Returns:
            The created invite.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
            HouseholdInviteExistsError: If that address already has an outstanding invite.
            HouseholdMemberExistsError: If that address is already a member.
        """
        entity = self._require_household(household)
        email = invite_create.email.lower()

        if self.household_invite_repository.get_pending_for_email(household_id=household.household_id, email=email):
            raise HouseholdInviteExistsError(email=email) from None

        if any(
            user.email.lower() == email
            for _, user in self.household_member_repository.list_with_users(household.household_id)
        ):
            raise HouseholdMemberExistsError(email=email) from None

        expire_hours = settings.HOUSEHOLD_INVITE_TOKEN_EXPIRE_HOURS
        invite = HouseholdInvite(
            household_id=household.household_id,
            email=email,
            role=invite_create.role,
            expires_at=datetime.now(UTC) + timedelta(hours=expire_hours),
            token=create_typed_token(
                subject=household.household_id,
                token_type=TokenType.HOUSEHOLD_INVITE,
                expires_hours=expire_hours,
            ),
        )
        invite.invited_by_user_id = household.user_id
        # Whoever has proved they hold the address is who the invitation is
        # for. Recording it makes the invitation redeemable by that account
        # alone, rather than by anybody who can put the address in their
        # profile. The proof matters: an address on a profile is a claim, and
        # `PATCH /users/me` hands out any unclaimed one without asking for
        # anything, so binding on the profile alone would record whoever
        # squatted the address ahead of the invitation as its recipient. An
        # invitation that binds to nobody here is attributed later, when the
        # address is verified.
        invited_user = self.user_repository.get_by_email_ignoring_case(email)
        invite.invited_user_id = (
            invited_user.id
            if invited_user and self.email_verification_repository.has_verified(user_id=invited_user.id, email=email)
            else None
        )
        self.household_invite_repository.save(invite)
        self.session.commit()

        # The invite is committed and valid whether or not the mail leaves, and
        # reporting it as failed would only send the owner into the pending
        # invite guard above. Queue the message and return the invite.
        delivery: EmailOutboxStatus | None = None

        if settings.emails_enabled:
            email_data = generate_household_invite_email(
                email=email,
                token=invite.token,
                household_name=entity.name,
                inviter_name=household.user.full_name or household.user.email,
            )
            entry = EmailOutboxService.for_session(self.session).record_and_attempt(
                email_to=email, subject=email_data.subject, html_content=email_data.html_content
            )
            # Keep which message carried this invitation. Without it, an
            # invitation the provider never accepted is indistinguishable from
            # one the recipient is simply slow to answer.
            invite.email_outbox_id = entry.id
            self.household_invite_repository.save(invite)
            self.session.commit()
            delivery = entry.status

        return HouseholdInvitePublic.model_validate(invite, update={"delivery_status": delivery})

    def list_invites(
        self,
        household: HouseholdContext,
        status: HouseholdInviteStatus | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> HouseholdInvitesPublic:
        """List the invites of the household.

        Args:
            household: The household context.
            status: An optional status to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The invites on the page, newest first, and how many match in total.
        """
        invites, count = self.household_invite_repository.list_for_household(
            household_id=household.household_id, status=status, skip=skip, limit=limit
        )
        data = [
            HouseholdInvitePublic.model_validate(invite, update={"delivery_status": delivery})
            for invite, delivery in invites
        ]

        return HouseholdInvitesPublic(data=data, count=count)

    def revoke_invite(self, household: HouseholdContext, invite_id: uuid.UUID) -> Message:
        """Withdraw an invite that has not been accepted.

        The row is kept, marked revoked, rather than deleted. The token stays
        recognised, so someone following an old link is told it was withdrawn
        instead of that it never existed.

        Args:
            household: The household context.
            invite_id: The ID of the invite to withdraw.

        Returns:
            A confirmation message.

        Raises:
            HouseholdInviteNotFoundError: If the invite does not exist in the household.
            HouseholdInviteUsedError: If the invite was already accepted or withdrawn.
        """
        invite = self.household_invite_repository.get_for_household(
            entity_id=invite_id, household_id=household.household_id
        )

        if not invite:
            raise HouseholdInviteNotFoundError from None

        if invite.status is not HouseholdInviteStatus.PENDING:
            raise HouseholdInviteUsedError from None

        invite.status = HouseholdInviteStatus.REVOKED
        self.household_invite_repository.save(invite)
        self.session.commit()

        return Message(message="Invitation withdrawn.")

    def preview_invite(self, token: str) -> HouseholdInvitePreview:
        """Describe an invite for the join page.

        Public, so it deliberately carries only what somebody needs to decide
        whether to accept, and nothing about the household's money.

        Args:
            token: The invite token.

        Returns:
            The household name, who invited them, the invited address masked,
            and when it expires.

        Raises:
            HouseholdInviteNotFoundError: If no invite has that token.
            HouseholdInviteUsedError: If the invite was already accepted or withdrawn.
            HouseholdInviteExpiredError: If the invite is past its expiry.
            HouseholdNotFoundError: If the household the invite points at is gone.
        """
        invite = self._require_pending_invite(token)
        entity = self.household_repository.get_by_id(invite.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        inviter = (
            self.household_member_repository.get_user(invite.invited_by_user_id) if invite.invited_by_user_id else None
        )

        return HouseholdInvitePreview(
            household_name=entity.name,
            invited_by=inviter.email if inviter else invite.email,
            masked_email=mask_email(invite.email),
            role=invite.role,
            expires_at=invite.expires_at,
        )

    def claim_invites_for_verified_email(self, user: User) -> None:
        """Point the invites sent to a user's address at their account, without committing.

        Called once the address has been proved to be theirs. Until then the
        invitation names no account, and the accept path refuses it: an address
        alone is a claim anybody can make, and honouring it would let whoever
        holds a leaked link rename themselves into the invitation.

        The caller owns the transaction, so verifying an address and handing
        over its invitations happen together.

        Args:
            user: The user who has just proved they hold the address.
        """
        for invite in self.household_invite_repository.list_pending_for_email(user.email):
            invite.invited_user_id = user.id
            self.household_invite_repository.save(invite)

    def accept_invite(self, user: User, token: str) -> HouseholdPublic:
        """Join a household using an invite.

        The caller already has a household, created when they signed up. If it
        is still empty it is discarded, since nothing would be lost. If they
        have started using it, joining is refused rather than silently
        abandoning their data. A household they share with others stays, with
        a new owner if they were its last one.

        Args:
            user: The user accepting the invite.
            token: The invite token.

        Returns:
            The household they joined.

        Raises:
            HouseholdInviteNotFoundError: If no invite has that token.
            HouseholdInviteUsedError: If the invite was already accepted or withdrawn.
            HouseholdInviteExpiredError: If the invite is past its expiry.
            HouseholdInviteEmailMismatchError: If the invite was issued to another account.
            HouseholdInviteUnclaimedError: If the invited address has not been proved to belong to anyone.
            HouseholdNotFoundError: If the household the invite points at is gone.
            HouseholdMemberExistsError: If the caller already belongs to that household.
            HouseholdNotEmptyError: If the caller's current household holds data.
        """
        invite = self._require_pending_invite(token)

        # Compared by identity, not by address. An address is a profile field
        # its owner can change to anything unclaimed, and the invited address
        # is readable from the public preview, so comparing the two would let
        # whoever holds a leaked link rename themselves into the invitation and
        # walk into the household's finances.
        if invite.invited_user_id is None:
            raise HouseholdInviteUnclaimedError from None

        if invite.invited_user_id != user.id:
            raise HouseholdInviteEmailMismatchError from None

        entity = self.household_repository.get_by_id(invite.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        membership = self.household_member_repository.get_by_user_id(user.id)

        if membership:
            if membership.household_id == invite.household_id:
                raise HouseholdMemberExistsError(email=user.email) from None

            if self.household_repository.has_financial_data(membership.household_id):
                raise HouseholdNotEmptyError from None

            # Moving out is one more way of leaving a household, so it takes
            # the same exit as the others: an empty one is discarded, since it
            # held nothing but seeded categories, and one that keeps its
            # members is left with an owner.
            self._release_membership(membership, departing=user)

        self.household_member_repository.save(
            HouseholdMember(household_id=entity.id, user_id=user.id, role=invite.role)
        )
        invite.status = HouseholdInviteStatus.ACCEPTED
        self.household_invite_repository.save(invite)
        self.session.commit()
        self.notify_new_owners()

        return self._to_public(household=entity, member_count=self.household_repository.count_members(entity.id))

    def check_signup_invite(self, email: str, token: str) -> None:
        """Refuse a registration the invitation it came through could never be redeemed by.

        Nothing is joined and nothing is consumed here. A registration is a
        claim on an address, not a proof of it: anybody who reads a leaked link
        can sign up with the address it names. Taking the membership then would
        put a stranger in the household and burn the invitation, so the real
        recipient could never join and the owner would be left with a member
        who never arrives.

        The address is still compared, because the sign-up form asks the
        recipient to type the invited address and telling them now that they
        mistyped it is kinder than letting them find out after verifying. It is
        a courtesy, not the guard: the guard is that the invitation is
        attributed only when the address is verified, and redeemed only by the
        account it was attributed to.

        No account is created here, so a signup can settle the invitation before it writes
        anything and never has to undo a write to drop one it cannot apply. An invitation found
        past its expiry is marked as such, in the caller's transaction, as it always was.

        Args:
            email: The address registering.
            token: The invite token the registration came through.

        Raises:
            HouseholdInviteNotFoundError: If the token is not recognised.
            HouseholdInviteUsedError: If the invite was already used or withdrawn.
            HouseholdInviteExpiredError: If the invite has expired.
            HouseholdInviteEmailMismatchError: If the invite was sent to a different address.
        """
        invite = self._require_pending_invite(token)

        if invite.email.lower() != email.lower():
            raise HouseholdInviteEmailMismatchError from None

    def _require_pending_invite(self, token: str) -> HouseholdInvite:
        """Load an invite that can still be acted on.

        Args:
            token: The invite token.

        Returns:
            The invite.

        Raises:
            HouseholdInviteNotFoundError: If no invite has that token.
            HouseholdInviteUsedError: If the invite was already accepted or withdrawn.
            HouseholdInviteExpiredError: If the invite is past its expiry.
        """
        invite = self.household_invite_repository.get_by_token(token)

        if not invite:
            raise HouseholdInviteNotFoundError from None

        if invite.status is not HouseholdInviteStatus.PENDING:
            raise HouseholdInviteUsedError from None

        if invite.expires_at < datetime.now(UTC):
            invite.status = HouseholdInviteStatus.EXPIRED
            # Flushed, not committed: this runs inside the caller's
            # transaction, which may be signing a user up.
            self.household_invite_repository.save(invite)
            raise HouseholdInviteExpiredError from None

        return invite
