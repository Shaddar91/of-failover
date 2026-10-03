"""Runs the handler with your AWS credentials: python -m app '{"action":"status"}' [--secret-arn <arn>]."""

import argparse
import json
import os
import sys

from app.config import SECRET_ARN_ENV
from app.handler import lambda_handler


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description=__doc__)
    parser.add_argument("event", nargs="?", default='{"action":"status"}', help="JSON event, default a status read")
    parser.add_argument("--secret-arn", help=f"config secret ARN, default ${SECRET_ARN_ENV}")
    args = parser.parse_args(argv)
    if args.secret_arn:
        os.environ[SECRET_ARN_ENV] = args.secret_arn
    result = lambda_handler(json.loads(args.event))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
