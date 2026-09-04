from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class BudgetNotFoundError(NotFoundError):
    """Signal that a budget does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a BudgetNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Budget", message, exc)


class BudgetExistsError(ConflictError):
    """Signal that the category already has a budget for that month."""

    def __init__(self, identifier: str, message: str | None = None, exc: Exception | None = None):
        """Initialize a BudgetExistsError.

        Args:
            identifier: The category and month that already have a budget.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Budget", identifier, message, exc)


class BudgetOverlapError(ServiceError):
    """Signal that a parent category and its subcategory cannot both be budgeted.

    A limit on a parent already covers everything filed under it, so budgeting
    both would count the same spending twice.
    """

    def __init__(self, parent_name: str, child_name: str, exc: Exception | None = None):
        """Initialize a BudgetOverlapError.

        Args:
            parent_name: The name of the parent category.
            child_name: The name of the subcategory.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = (
            f"'{parent_name}' already covers '{child_name}', so budgeting both would count the same "
            "spending twice. Budget the parent, or its subcategories, but not both."
        )
        super().__init__(msg, exc)
        self.parent_name = parent_name
        self.child_name = child_name


class BudgetCategoryKindError(ValidationError):
    """Signal that only expense categories can be budgeted."""

    def __init__(self, name: str, exc: Exception | None = None):
        """Initialize a BudgetCategoryKindError.

        Args:
            name: The name of the category.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"'{name}' is an income category. A budget is a spending limit, so it needs an expense category."
        super().__init__(msg, exc)


class DuplicateBudgetCategoryError(ValidationError):
    """Signal that a bulk update names the same category twice."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a DuplicateBudgetCategoryError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Each category can appear only once in a set of budgets."
        super().__init__(msg, exc)
