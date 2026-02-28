"""Project schema and migration exports."""

from music_create.project.migration import migrate_to_v2
from music_create.project.schema import MCPJProjectV2

__all__ = ["MCPJProjectV2", "migrate_to_v2"]
