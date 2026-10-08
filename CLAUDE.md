# CLAUDE.md

## Python environment

- Always use the project's virtual environment in `.venv/` — never install packages into the global Python.
- If `.venv/` doesn't exist yet, create it and install the project with dev dependencies:
  ```bash
  python -m venv .venv
  .venv/Scripts/python -m pip install -e ".[dev]"   # Windows; on Linux/macOS: .venv/bin/python
  ```
- Shell state doesn't persist between commands, so call the venv's executables directly instead of relying on `activate`:
  ```bash
  .venv/Scripts/python -m pytest -q
  .venv/Scripts/python -m flake8 .
  .venv/Scripts/python -m streamlit run app.py
  ```
