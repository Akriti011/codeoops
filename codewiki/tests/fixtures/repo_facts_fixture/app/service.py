"""Greeting service."""


class Greeter:
    """Says hello."""

    def greet(self, name: str) -> str:
        return f"Hello, {name}!"

    def _internal_helper(self) -> None:
        return None
