# Changelog

All notable changes to grace-orchestrator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial extraction from astro-project
- Core orchestration framework
- Multi-agent coordination (planner, worker, reviewer)
- Prefect workflow integration
- CLI tool (`gracectl`)
- Docker worker image
- Project initialization (`grace init`)
- Slice-based verification
- Evidence collection and reporting
- Live traffic replay support
- Observability monitoring integration

### Documentation
- Comprehensive README with examples
- Migration guide for existing projects
- Contributing guidelines
- API documentation

## [0.1.0] - 2026-05-30

### Added
- Initial release of grace-orchestrator
- Extracted from production astro-project implementation
- Artifact-driven verification framework
- Support for backend, frontend, and replay verification
- YAML-based configuration system
- Docker Compose integration
- Template system for project initialization

### Features
- **CLI Commands**:
  - `gracectl slice verify` - Run full verification
  - `gracectl slice replay` - Replay slice commands
  - `gracectl slice list` - List available slices
  - `gracectl watch start/stop` - Monitor flows
  - `gracectl evidence collect/show/export` - Manage evidence
  - `gracectl env show/validate` - Environment management

- **Orchestration**:
  - Prefect-based workflow engine
  - Multi-agent coordination
  - Work packet management
  - Progress tracking
  - Error handling and retry logic

- **Configuration**:
  - `grace/project.yaml` - Project and slice definitions
  - `grace/agent_profiles.yaml` - Agent configuration
  - `grace/requirements.xml` - System requirements
  - `grace/technology.xml` - Technology constraints
  - `grace/development-plan.xml` - Module structure
  - `grace/knowledge-graph.xml` - Semantic code map

- **Docker Support**:
  - Worker container image
  - Docker Compose fragment for easy integration
  - Volume management for persistent state

### Dependencies
- Python 3.12+
- Prefect 3.6.25+
- Pydantic 2.12+
- Typer for CLI
- Rich for terminal output
- Structlog for logging

### Known Limitations
- Requires Prefect server for workflow orchestration
- Docker required for containerized workers
- Limited to Python-based projects initially

## [0.0.1] - 2026-05-25

### Added
- Initial project structure
- Core abstractions and interfaces
- Basic CLI skeleton

---

## Release Notes

### v0.1.0 - Initial Public Release

This is the first public release of grace-orchestrator, extracted from a production implementation in the astro-project. The framework has been battle-tested in a real-world environment and is now available as a standalone package.

**Highlights**:
- Complete artifact-driven verification framework
- Multi-agent orchestration with Prefect
- Comprehensive CLI tooling
- Docker-based deployment
- Production-proven architecture

**Migration**: Existing projects using embedded GRACE can migrate using the provided MIGRATION.md guide.

**Next Steps**: We're working on:
- Enhanced documentation and tutorials
- Additional agent types and strategies
- Integration with more CI/CD platforms
- Performance optimizations
- Community feedback incorporation

---

[Unreleased]: https://github.com/yourusername/grace-orchestrator/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yourusername/grace-orchestrator/releases/tag/v0.1.0
[0.0.1]: https://github.com/yourusername/grace-orchestrator/releases/tag/v0.0.1
