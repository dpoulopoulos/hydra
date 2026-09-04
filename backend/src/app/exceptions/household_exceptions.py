from app.models.household import HouseholdRole

from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class HouseholdNotFoundError(NotFoundError):
    """Signal that a household does not exist in the database."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household", message, exc)


class HouseholdMembershipNotFoundError(NotFoundError):
    """Signal that a user does not belong to any household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdMembershipNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household membership", message, exc)


class HouseholdMemberNotFoundError(NotFoundError):
    """Signal that a household has no member with the given user."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdMemberNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household member", message, exc)


class HouseholdMemberExistsError(ConflictError):
    """Signal that a user already belongs to a household."""

    def __init__(self, email: str, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdMemberExistsError.

        Args:
            email: The email address of the user that already belongs to a household.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household member", email, message, exc)


class LastHouseholdOwnerError(ValidationError):
    """Signal that the last owner of a household cannot be demoted or removed."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a LastHouseholdOwnerError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "A household must always have at least one owner. Promote another member first."
        super().__init__(msg, exc)


class HouseholdRoleRequiredError(ServiceError):
    """Signal that an action requires a household role the user does not have."""

    def __init__(self, role: HouseholdRole, exc: Exception | None = None):
        """Initialize a HouseholdRoleRequiredError.

        Args:
            role: The role the action requires.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"This action requires the '{role.value}' role in the household."
        super().__init__(msg, exc)


class HouseholdInviteNotFoundError(NotFoundError):
    """Signal that an invite does not exist, or its token is not recognised."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdInviteNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household invite", message, exc)


class HouseholdInviteExistsError(ConflictError):
    """Signal that the address already has an outstanding invite."""

    def __init__(self, email: str, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdInviteExistsError.

        Args:
            email: The address that was invited twice.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Household invite", email, message, exc)


class HouseholdInviteExpiredError(ValidationError):
    """Signal that an invite is past its expiry."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a HouseholdInviteExpiredError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This invitation has expired. Ask for a new one."
        super().__init__(msg, exc)


class HouseholdInviteUsedError(ValidationError):
    """Signal that an invite has already been accepted or was revoked."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a HouseholdInviteUsedError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This invitation is no longer valid. It has already been used, or it was withdrawn."
        super().__init__(msg, exc)


class HouseholdInviteEmailMismatchError(ServiceError):
    """Signal that an invite was accepted by someone it was not addressed to.

    Without this check a leaked link would hand a stranger full access to the
    household's finances.
    """

    def __init__(self, exc: Exception | None = None):
        """Initialize a HouseholdInviteEmailMismatchError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This invitation was sent to a different email address."
        super().__init__(msg, exc)


class HouseholdNotEmptyError(ConflictError):
    """Signal that a household with data cannot be abandoned to join another."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a HouseholdNotEmptyError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = message or (
            "Your current household already has accounts or transactions in it. Joining another "
            "household would leave that data behind, so it has to be dealt with first."
        )
        super().__init__("Household", "current", msg, exc)
