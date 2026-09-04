class ServiceError(Exception):
    """Signal that a service-related error occurred."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a ServiceError.

        Args:
            message: The error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(message)
        self.message = message
        self.exc = exc

    def _append_message(self, existing: str, message: str | None) -> str:
        """Append a message to an existing message if it exists.

        Args:
            existing: The existing message.
            message: The message to append.

        Returns:
            The combined message, joined by a colon.
        """
        return f"{existing}{f': {message}' if message else ''}"


class NotFoundError(ServiceError):
    """Signal that a resource cannot be found."""

    def __init__(
        self,
        resource: str,
        message: str | None = None,
        exc: Exception | None = None,
    ):
        """Initialize a NotFoundError.

        Args:
            resource: The resource that was not found.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"{resource} not found."
        super().__init__(self._append_message(msg, message), exc)
        self.resource = resource


class ValidationError(ServiceError):
    """Signal that a validation-related error occurred."""

    def __init__(self, message: str, exc: Exception | None = None):
        """Initialize a ValidationError.

        Args:
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        super().__init__(message, exc)


class ConflictError(ServiceError):
    """Signal that a conflict occurred due to non-unique constraints or existing resources."""

    def __init__(
        self,
        resource: str,
        identifier: str,
        message: str | None = None,
        exc: Exception | None = None,
    ):
        """Initialize a ConflictError.

        Args:
            resource: The resource that caused the conflict.
            identifier: The identifier of the conflicting resource.
            message: An optional error message.
            exc: An optional exception. If provided, `from exc` will be used to preserve the original traceback.
        """
        msg = f"Conflict: {resource} with unique identifier '{identifier}' already exists."
        super().__init__(self._append_message(msg, message), exc)
        self.resource = resource
        self.identifier = identifier
