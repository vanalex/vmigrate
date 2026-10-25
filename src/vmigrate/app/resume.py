from __future__ import annotations

from vmigrate.app.engine import MigrationError
from vmigrate.app.run import RunMigration, RunReport
from vmigrate.domain.mapping import CollectionMapping
from vmigrate.ports import CheckpointStore


class ResumeMigration:
    """Continue a previous run from its checkpoints. Refuses if the mapping config changed."""

    def __init__(self, run: RunMigration, checkpoints: CheckpointStore):
        self._run = run
        self._checkpoints = checkpoints

    def execute(
        self, mappings: list[CollectionMapping], config_hash: str, run_id: str
    ) -> RunReport:
        info = self._checkpoints.get_run(run_id)
        if info is None:
            raise MigrationError(f"run '{run_id}' not found")
        if info.config_hash != config_hash:
            raise MigrationError(
                f"run '{run_id}' was started with a different collection config; "
                "start a new run instead"
            )
        return self._run.execute(mappings, config_hash, run_id=run_id)
