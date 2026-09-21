"""Attach a secret-safe LLM route fingerprint to a retained replay artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.workflow_evaluation import (
    ReplayArtifact,
    load_replay_artifact,
    replay_configuration_fingerprint,
    replay_model_routes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    args = parser.parse_args()

    config = LlmConfig.from_env()
    if config is None:
        raise SystemExit("no replay LLM configuration is available")
    path = Path(args.artifact)
    artifact = load_replay_artifact(path)
    fingerprint = replay_configuration_fingerprint(config)
    if artifact.configuration_fingerprint not in {None, fingerprint}:
        raise SystemExit("artifact already contains a different configuration fingerprint")
    stamped = ReplayArtifact(
        provider=artifact.provider,
        configuration_fingerprint=fingerprint,
        model_routes=replay_model_routes(config),
        observations=artifact.observations,
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(stamped.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    print(fingerprint)


if __name__ == "__main__":
    main()
