from .base_exceptions import ConflictError, NotFoundError, ServiceError, ValidationError


class CategoryNotFoundError(NotFoundError):
    """Signal that a category does not exist in the household."""

    def __init__(self, message: str | None = None, exc: Exception | None = None):
        """Initialize a CategoryNotFoundError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Category", message, exc)


class CategoryExistsError(ConflictError):
    """Signal that a category with the same name already exists under the same parent."""

    def __init__(self, name: str, message: str | None = None, exc: Exception | None = None):
        """Initialize a CategoryExistsError.

        Args:
            name: The conflicting category name.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__("Category", name, message, exc)


class CategoryInUseError(ServiceError):
    """Signal that a category cannot be deleted because something still references it.

    A conflict, but not the "already exists" kind ConflictError describes, so
    the message is written out rather than composed from that template.
    """

    def __init__(self, name: str, reason: str | None = None, exc: Exception | None = None):
        """Initialize a CategoryInUseError.

        Args:
            name: The name of the category in use.
            reason: What is still referencing the category, phrased to follow the name. Omit for the
                generic wording.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        blocker = f"still {reason}" if reason else "still in use"
        msg = f"Category '{name}' {blocker}. Archive it instead, so past reports keep their history."
        super().__init__(msg, exc)
        self.name = name
        self.reason = reason


class CategoryDepthExceededError(ValidationError):
    """Signal that a category tree may not be deeper than two levels."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a CategoryDepthExceededError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "Categories are two levels deep. A subcategory cannot itself have subcategories."
        super().__init__(msg, exc)


class CategorySelfParentError(ValidationError):
    """Signal that a category cannot be its own parent."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a CategorySelfParentError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "A category cannot be its own parent."
        super().__init__(msg, exc)


class CategoryKindMismatchError(ValidationError):
    """Signal that a subcategory must have the same kind as its parent."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a CategoryKindMismatchError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "A subcategory must be the same kind, expense or income, as its parent."
        super().__init__(msg, exc)


class SystemCategoryError(ValidationError):
    """Signal that a system category cannot be changed or removed."""

    def __init__(self, exc: Exception | None = None):
        """Initialize a SystemCategoryError.

        Args:
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = "This category is built in. It is the fallback for uncategorized spending and cannot be removed."
        super().__init__(msg, exc)


class CategoryLimitReachedError(ServiceError):
    """Signal that a household already holds as many categories as it may.

    The category endpoints hand back the whole tree in one response, because a
    picker and a two level tree have no use for half of it. The ceiling is
    therefore here, on what a household can create, rather than on what the
    listing will return.
    """

    def __init__(self, limit: int, exc: Exception | None = None):
        """Initialize a CategoryLimitReachedError.

        Args:
            limit: The largest number of categories a household may hold.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = (
            f"This household already has {limit} categories, which is the most it can hold. "
            "Delete or reuse one before adding another."
        )
        super().__init__(msg, exc)
        self.limit = limit
