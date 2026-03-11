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

    response = ClassifierResponse(
        policy=request.policy,
        yes_prob=0.99 if force_unsafe else 0.01,
    )

    if request.mode == "video" and force_unsafe:
        response.trigger_frame_index = 0
        response.trigger_time_sec = 1.0

    return response


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    response = build_response(args.input_path, force_unsafe=args.force_unsafe)
    print(response.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
