
# Modern uv Project Workflow (Recommended)

uv can manage project dependencies natively via pyproject.toml, eliminating the need for requirements.txt and manual venv activation altogether:

Initialize the project:

```
uv init
```

Add dependencies:
Create env & uv.lock, install dependencies.

```
uv add -r requirements.txt
# or
uv add typesafe-sdk yt-dlp pandas python-dotenv
```

uv run ensures the env is locked and up-to-date before launch
`--env-file` `.env` ensures `TYPESAFE_API_KEY` is present in `os.environ` even before `load_dotenv()` executes in Python.

```
uv run --env-file .env python jev_classify.py
```


---


## What Happens Under the Hood

1. `uv init` generates:

    - `pyproject.toml`: The standard modern Python configuration file.

    - `.python-version`: Pins your active Python version (e.g., 3.12).

    - `.gitignore`: Configured to ignore .venv/ and build artifacts.

2. `uv add -r requirements.txt`:

    - Parses `typesafe-sdk`, `yt-dlp`, `pandas`, and `python-dotenv` from file.

    - Writes them under dependencies = [...] in `pyproject.toml`.

    - Resolves dependencies in parallel and creates a deterministic `uv.lock`.

    - Automatically builds and populates the `.venv` directory.

3. Once migrated, you can delete `requirements.txt` (`rm requirements.txt`) as `pyproject.toml` and `uv.lock` now manage project dependencies.


---


## Later just commit and distribute:

- `pyproject.toml`: Defines the project declaration (dependencies, metadata, build tool).

- `uv.lock`: Locks every sub-dependency to exact versions, hashes, and platform markers.

For an application or automation script (like this YouTube classifier), distributing uv.lock ensures that anyone else—or your deployment server/Docker container—installs the exact same dependencies byte-for-byte.

Install exact pinned versions without re-resolving or modifying the lockfile

on the target machine or in CI/CD, reproduce the environment instantly with:

```
uv sync --frozen --no-dev
```


---
---


# Legacy venv & pip Project Workflow (using uv for speed)

Create the virtual environment:
```
uv venv
```

Install dependencies:
```
uv pip install -r requirements.txt
```

Run your script with .env loaded automatically
uv loads .env vars directly without env activate:
```
uv run --env-file .env python jev_classify.py
```
