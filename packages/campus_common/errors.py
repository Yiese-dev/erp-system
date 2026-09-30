class DomainError(Exception):
    """A business-rule failure that is safe to show to the user."""

    def __init__(self, message: str, status: int = 409, details: list | dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details
