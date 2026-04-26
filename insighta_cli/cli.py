"""Entry point for the Insighta CLI."""

import argparse


def main():
    parser = argparse.ArgumentParser(
        prog="insighta",
        description="Insighta Labs+ CLI tool",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    main()
