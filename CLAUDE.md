# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository nature

A grab-bag of personal utility scripts — no build, no tests, no shared library. Each file is a standalone tool. Treat additions as independent scripts; don't introduce a package layout, dependency manifest, or test harness unless asked.

## Notes on existing files

- `setup.csh` is **csh/tcsh syntax** (uses `setenv`), sourced into a Synopsys VCS environment. Do not rewrite as bash without being asked — the target shell is intentional.
- `vm_disk_usage.sh` shells out to `ssh vm`. The git history shows the `vm` remote/host was removed (`ff7c798 remove vm remote`), so this script may no longer work without the user reconfiguring their SSH config.
- `README.md` is stale — it only documents the two `*disk_usage.sh` scripts and predates `huffman.py`, `log_meal.py`, and `setup.csh`. If editing README, expect to add entries rather than just tweak existing ones.
- Python scripts (`huffman.py`, `log_meal.py`) use only the standard library and target `python3` directly via shebang. No virtualenv assumed.
