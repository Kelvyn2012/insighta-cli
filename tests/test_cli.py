"""Basic smoke tests for Insighta CLI."""

from insighta_cli import __version__


def test_version():
    assert __version__ == "0.1.0"
