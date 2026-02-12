"""Sample main module for testing."""

from sample_project.utils import format_name


def hello(name: str) -> str:
    """Says hello to someone.

    Args:
        name: The person's name.

    Returns:
        Greeting string.
    """
    return f"Hello, {format_name(name)}"


def goodbye(name: str) -> str:
    """Says goodbye."""
    return f"Goodbye, {name}"


class Greeter:
    """A greeting machine."""

    def __init__(self, prefix: str = "Hi") -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        """Generate a greeting."""
        return f"{self.prefix}, {name}!"

    def farewell(self, name: str) -> str:
        """Generate a farewell."""
        return f"Farewell, {name}."
