from pathlib import Path

import yaml


WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
)


def load_workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_ci_workflow_matches_repo_toolchain() -> None:
    workflow = load_workflow()

    assert workflow["name"] == "CI"
    assert workflow["on"] == {
        "pull_request": None,
        "push": {"branches": ["main"]},
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}",
        "cancel-in-progress": True,
    }

    job = workflow["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest"

    steps = job["steps"]
    assert steps[0] == {"uses": "actions/checkout@v6"}
    assert steps[1] == {
        "uses": "actions/setup-python@v6",
        "with": {"python-version": "3.12.12"},
    }
    assert steps[2] == {
        "uses": "astral-sh/setup-uv@v7",
        "with": {"enable-cache": True},
    }
    assert steps[3] == {"run": "uv sync --locked --all-groups"}
    assert steps[4] == {"run": "uv run ruff format --check ."}
    assert steps[5] == {"run": "uv run ruff check ."}
    assert steps[6] == {"run": "uv run pytest"}
