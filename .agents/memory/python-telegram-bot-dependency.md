---
name: Python Telegram dependency compatibility
description: Dependency constraint when installing python-telegram-bot in imported Python projects
---

Never install the separate PyPI package named `telegram` alongside `python-telegram-bot`; both use the `telegram` import namespace and the former can overwrite or remove files from the latter.

**Why:** The imported requirements caused an import failure after the packages shared the namespace, requiring a clean uninstall and reinstall of the supported package.

**How to apply:** Keep only `python-telegram-bot` in requirements for this bot and verify imports from `telegram.ext` after dependency changes.