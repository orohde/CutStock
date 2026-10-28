# Contributing to CutStock

Thanks for your interest in improving CutStock!

## Before you start

- **Bugs and ideas:** open an [issue](https://github.com/orohde/CutStock/issues/new/choose).
- **Questions:** use [Discussions](https://github.com/orohde/CutStock/discussions).
- **Pull requests:** please open an issue first to discuss what you'd like to
  change. CutStock is maintained by one person, so small, focused PRs are much
  easier to review than large ones.

English or German is fine for issues and PRs.

## Development setup

Prerequisites: Python 3.12+

```bash
git clone https://github.com/orohde/CutStock.git
cd CutStock
./setup.sh   # creates venv, installs dependencies
./run.sh     # starts the app (local web server + browser)
./test.sh    # runs the test suite (pytest)
```

See the [README](README.md#project-structure) for an overview of the code layout.

## Guidelines

- Keep changes in `core/` GUI-independent -- it is shared by the desktop and web variants.
- Add or update tests in `tests/` when you change optimization logic.
- New UI texts need translations in `ui/i18n.py` for all languages (EN/DE/FR/IT).
  If you can't translate a language, use English and mention it in the PR.

## Adding a language

Add your language code to `LANGUAGES` in `ui/i18n.py` and a translation for
each key in `TRANSLATIONS`.

## License

CutStock is licensed under [CC BY-NC-SA 4.0](LICENSE). By submitting a
contribution, you agree that it is published under this license.
