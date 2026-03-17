---
title: Contributing
layout: default
nav_order: 7
---

# Contributing
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Prerequisites

- Python 3.10+
- [Poetry](https://python-poetry.org/) for dependency management
- [tox](https://tox.wiki/) for test automation
- Docker (for integration tests)

## Setup

```bash
# Clone the repository
git clone https://github.com/startreedata/pinot-dbapi.git
cd pinot-dbapi

# Install dependencies
make init
```

## Running Tests

### Unit Tests

Unit tests don't require a running Pinot instance:

```bash
make test-unit
```

### Integration Tests

Integration tests require a running Pinot cluster:

```bash
# Start Pinot (in a separate terminal)
make run-pinot

# Run integration tests
make test-integration
```

### All Tests

```bash
make test
```

### Coverage

```bash
make coverage
```

## Linting

```bash
make lint
```

## Project Structure

```
pinotdb/
├── __init__.py       # Entry points: connect(), connect_async()
├── db.py             # DB-API 2.0 implementation
├── sqlalchemy.py     # SQLAlchemy dialect
├── exceptions.py     # Exception classes
└── keywords.py       # Pinot SQL keywords
```

## Release Process

The preferred release method is the [Pinotdb Pypi Publisher](https://github.com/startreedata/pinot-dbapi/actions/workflows/pinotdb-pypi-publisher.yml) GitHub Actions workflow.

It handles version bumping, changelog generation, tagging, GitHub Release creation, and PyPI publishing automatically.

### Workflow Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `ref` | Branch to release from | `master` |
| `version` | Version to release (e.g. `9.0.1`) | -- |

### Required Secrets

| Secret | Description |
|--------|-------------|
| `RELEASE_PAT` | GitHub PAT with push access to protected branches |
| `PYPI_USERNAME` | PyPI username (or `__token__` for API token auth) |
| `PYPI_PASSWORD` | PyPI password or API token |
