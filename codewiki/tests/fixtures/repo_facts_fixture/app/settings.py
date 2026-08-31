"""Configuration for the fixture app."""

import os

API_KEY = os.environ["API_KEY"]
DEBUG = os.getenv("DEBUG", "false")
