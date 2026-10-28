# Contributing to CutStock

Thanks for your interest in improving CutStock!

## How you can help

- **Bugs and ideas:** open an [issue](https://github.com/orohde/CutStock/issues/new/choose).
  A precise description, screenshots, or an exported project help a lot.
- **Questions:** use [Discussions](https://github.com/orohde/CutStock/discussions).
- **Translations and wording:** suggest corrections in an issue.

English or German is fine.

## Pull requests

CutStock is offered under a non-commercial license **and** a separate commercial
license. To keep the licensing clear, **code contributions (pull requests) are
currently not accepted.** Pull requests will be closed without merging.

If you've found a fix, please describe the problem and the cause in an issue.
The fix will then be implemented in the main codebase.

**Commercial licensing** is not handled on GitHub. Please use the contact form at
[worldgate.de/cutstock](https://worldgate.de/en/cutstock-en/) instead of opening
an issue or discussion.

## Running from source

Prerequisites: Python 3.12+

```bash
git clone https://github.com/orohde/CutStock.git
cd CutStock
./setup.sh   # creates venv, installs dependencies
./run.sh     # starts the app (local web server + browser)
./test.sh    # runs the test suite (pytest)
```

You're welcome to modify CutStock for your own non-commercial use within the
terms of the [license](LICENSE).
