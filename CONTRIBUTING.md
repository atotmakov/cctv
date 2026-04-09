# Contributing

Thank you for your interest in contributing to `cctv`!

## Getting started

1. Fork the repository and clone it locally.
2. Install development dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
3. Create a branch for your change:
   ```bash
   git checkout -b your-feature-or-fix
   ```

## Making changes

- Keep changes focused — one fix or feature per PR.
- Write or update tests for any changed behaviour.
- Run the test suite before submitting:
  ```bash
  pytest
  ```
- Follow existing code style (PEP 8).

## Submitting a pull request

1. Push your branch to your fork.
2. Open a pull request against `master`.
3. Describe what the PR does and why.
4. A maintainer will review and provide feedback.

## Reporting bugs

Open a [GitHub issue](https://github.com/atotmakov/cctv/issues) with:
- A clear description of the problem.
- Steps to reproduce.
- Expected vs actual behaviour.
- Python version and OS.

## Security issues

Do **not** open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for the responsible disclosure process.
