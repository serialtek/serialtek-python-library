# SerialTek Python Library

[![Documentation Status](https://app.readthedocs.org/projects/serialtek-python-library/badge/?version=latest)](https://serialtek-python-library.readthedocs.io/en/latest/?badge=latest)
[![PyPI - Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://github.com/serialtek/serialtek-python-library)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](/LICENSE)

The SerialTek Python library provides functions for automating work with Kodiak
analyzers and testers.

## Installation and Usage

To install, run

```shell
pip install git+https://github.com/serialtek/serialtek-python-library
```

Once installed, log into a Kodiak by running the following command:

```shell
stcli login (kodiak ip address)
```

Then you can use `Kodiak` to make API calls:

```py
from serialtek import Kodiak

kodiak = Kodiak()

kodiak.get("/kodiak/v1/status")
```

See the documentation on your kodiak for API usage, and this libraries
documentation for additional sdk functionality.

## Development

To set up a development environment:

1. [install uv](https://docs.astral.sh/uv/getting-started/installation/)
2. run `uv sync` from within this directory. This creates a
   virtual environment in `.venv` with all dependencies and the application
   installed. Use this virtual environment in vs code or other editors.

You can run commands inside the development environment with `uv run`, e.g.
`uv run stcli` to access the CLI or `uv run python` for a REPL where you can
`import serialtek`. Alternatively, activate the environment directly by sourcing
`.venv/bin/activate` (or `.venv\Scripts\activate` on Windows).

Common development tasks are defined as [poe](https://poethepoet.natn.io/)
tasks and can be run with `uv run poe <task>` (e.g. `uv run poe test`,
`uv run poe typecheck`, `uv run poe lint`). Run `uv run poe` to list them.

## License

Licensed under the Apache 2.0 license, see [LICENSE](/LICENSE). See
[NOTICE](/NOTICE) for copyright information.
