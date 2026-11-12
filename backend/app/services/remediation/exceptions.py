"""Remediation workflow and safe execution exceptions."""


class RemediationError(Exception):
    """Base exception for all remediation domain errors."""
    pass


class RemediationNotFoundError(RemediationError):
    """Raised when a remediation recommendation cannot be found."""
    pass


class InvalidRemediationStateError(RemediationError):
    """Raised when an invalid state transition is requested."""
    pass


class ActionNotAllowlistedError(RemediationError):
    """Raised when an unapproved or disallowed action name is requested."""
    pass


class ParameterValidationError(RemediationError):
    """Raised when action parameters fail validation rules."""
    pass


class DuplicateExecutionError(RemediationError):
    """Raised when an execution is attempted on an already executing recommendation."""
    pass


class RemediationExecutionError(RemediationError):
    """Raised when an execution fails at runtime."""
    pass


class RemediationTimeoutError(RemediationExecutionError):
    """Raised when execution exceeds the bounded safety timeout."""
    pass

