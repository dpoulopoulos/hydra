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
