# Browser Automation Platform

> **Helping collect Forge data? Start here:** [CONTRIBUTOR_QUICKSTART.md](CONTRIBUTOR_QUICKSTART.md)
> (printable PDF: [docs/contributor/CONTRIBUTOR_QUICKSTART.pdf](docs/contributor/CONTRIBUTOR_QUICKSTART.pdf)).
> On Windows the whole workflow is five double-click scripts — `install.bat`,
> `update.bat`, `start-chrome.bat`, `run.bat`, `push.bat`. No commands needed after
> the one-time clone.

A generic, site-agnostic visual browser automation platform in Python, built on
Playwright with a hexagonal (ports & adapters) architecture. It drives multiple
browser tabs on a configurable tick, captures what is on screen, runs pluggable
vision analyzers, evaluates a rule engine, and executes actions — all described
by a YAML configuration rather than code.

It is **not** specific to any website or game: capture targets, analyzers,
rules, and actions are all configuration, and new analyzers/actions install as
plugins.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .                 # core runtime (stubs; safe to run offline)
pip install -e ".[production]"   # real vision + resource monitoring + plugins
pip install -e ".[gui]"          # PySide6 monitoring GUI
playwright install chromium      # once, for --real runs
```

Optional extras: `vision`, `gui`, `monitoring`, `plugins`, `production`, `dev`.

**Windows beta users**: download the installer and follow
**[docs/WINDOWS_BETA.md](docs/WINDOWS_BETA.md)** — no Python needed. Build details
in [docs/PACKAGING.md](docs/PACKAGING.md).

## Commands

```bash
bap validate-config config/app.example.yaml   # check a config, exit 0/2, no browser
bap run config/production.example.yaml --dry-run   # resolve everything, launch nothing
bap run config/production.example.yaml --real --real-vision --store history.db
bap-run config/app.example.yaml               # equivalent to `bap run`
bap-gui config/app.example.yaml               # PySide6 monitor
bap --version
```

Key flags: `--config PATH`, `--store PATH`, `--log-format {plain,json}`,
`--dry-run`, `--real`, `--real-vision`, `--seconds N`.

See **[docs/OPERATIONS.md](docs/OPERATIONS.md)** for installation, first run,
configuration structure, persistence, health states, plugins, and
troubleshooting.

## Development

```bash
pip install -e ".[dev]"
pytest               # unit + component suite
pytest -m load       # multi-session load scenarios
pytest -m stress     # recovery/persistence stress
pytest -m integration  # real Playwright (needs a browser)
```

Architecture, risk, and hardening notes live in `docs/`.
