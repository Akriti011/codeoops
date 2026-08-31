"""Fixture entry point."""

from app.service import Greeter


def main():
    greeter = Greeter()
    print(greeter.greet("world"))


if __name__ == "__main__":
    main()
