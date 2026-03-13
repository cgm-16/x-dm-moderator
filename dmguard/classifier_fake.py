from argparse import ArgumentParser
from pathlib import Path
from typing import Sequence
import sys

from dmguard.classifier_contract import ClassifierResponse, load_classifier_request


def build_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("input_path", type=Path)

    force_group = parser.add_mutually_exclusive_group()
    force_group.add_argument("--force-safe", action="store_true")
    force_group.add_argument("--force-unsafe", action="store_true")

    return parser


def build_response(input_path: Path, *, force_unsafe: bool) -> ClassifierResponse:
    request = load_classifier_request(input_path)

    if force_unsafe:
        return ClassifierResponse(
            policy=request.policy,
            rating="unsafe",
            category="O2: Violence, Harm, or Cruelty",
            rationale="Forced unsafe for testing",
            trigger_index=0,
        )

    return ClassifierResponse(
        policy=request.policy,
        rating="safe",
        category="NA: None applying",
        rationale="Forced safe for testing",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    response = build_response(args.input_path, force_unsafe=args.force_unsafe)
    print(response.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
