"""Failures shared by execution stages and their resource accounting."""


class ExecutionUnavailable(RuntimeError):
    """Execution cannot safely continue; an operation may not be confirmed stopped."""
