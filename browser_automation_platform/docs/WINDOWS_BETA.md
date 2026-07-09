# Windows Beta Guide

For beta users installing the Browser Automation Platform on **Windows 10/11
(64-bit)**. No Python or developer tools required — the installer bundles
everything.

---

## 1. Installation

1. Download **`BAP-Setup-0.1.0.exe`**.
2. (Recommended) Verify the download matches its published checksum. In
   PowerShell:
   ```powershell
   Get-FileHash .\BAP-Setup-0.1.0.exe -Algorithm SHA256
   ```
   Compare the result to `BAP-Setup-0.1.0.exe.sha256`.
3. Run the installer. It installs **per-user** (no administrator rights) to
   `%LOCALAPPDATA%\Programs\BAP` and adds a **Start Menu** entry,
   *Browser Automation Platform*.
4. Windows SmartScreen may warn about a new publisher — choose *More info →
   Run anyway*.

---

## 2. First run

Launch **Browser Automation Platform** from the Start Menu. On first run the app:

- creates its data folders under `%LOCALAPPDATA%\BAP` (see below), and
- seeds `config\app.yaml` from a bundled example.

The GUI opens in **monitoring mode running on built-in stubs** — it exercises
the full loop (capture → analyze → rules → actions → report) with no browser and
no network, so you can see it working immediately. Use **Start / Stop / Tick**
and watch the session table, live log, and operational **Status**
(*starting → ready → degraded → stopping → stopped*).

To use a real browser, see **Real automation** below.

### The CLI

A console tool `bap.exe` ships alongside the GUI (Start Menu → *BAP (CLI)*, or
run it from `%LOCALAPPDATA%\Programs\BAP\bap.exe`):

```powershell
bap --version
bap validate-config "%LOCALAPPDATA%\BAP\config\app.yaml"
bap run "%LOCALAPPDATA%\BAP\config\app.yaml" --seconds 10 --store "%LOCALAPPDATA%\BAP\data\history.db"
```

`validate-config` checks a config and exits without launching anything;
`run --dry-run` resolves everything (including plugins) but starts nothing.

---

## 3. Folder locations

Everything the app writes lives under **`%LOCALAPPDATA%\BAP`**
(typically `C:\Users\<you>\AppData\Local\BAP`):

| Folder | Contents |
|---|---|
| `config\` | your configuration (`app.yaml`, seeded on first run) |
| `logs\` | rotating log files (`bap.log`, `bap-gui.log`) |
| `data\` | persistence databases (when you pass `--store`) and crash reports |
| `data\crashes\` | local crash bundles (JSON) — see Troubleshooting |
| `plugins\` | drop-in location for future plugin packages |

The application itself is installed separately under
`%LOCALAPPDATA%\Programs\BAP` and is removed on uninstall; your data folders are
kept unless you opt to remove them.

You can relocate the whole tree by setting a `BAP_HOME` environment variable
before launching.

---

## 4. Real automation (Playwright browser)

The installer is intentionally small and does **not** include a browser; the GUI
runs on stubs by default. To drive a real browser (the `--real` option), install
Chromium once:

```powershell
powershell -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Programs\BAP\install-browser.ps1"
```

- **Disk usage:** ~300–450 MB for Chromium, downloaded to
  `%LOCALAPPDATA%\BAP\data\ms-playwright`.
- **Update behavior:** the browser is pinned to the Playwright version bundled
  with this release. It is **not** auto-updated; a future app update that bumps
  Playwright will prompt you to re-run the installer above to fetch a matching
  Chromium. Old versions can be deleted from the `ms-playwright` folder.
- **Troubleshooting:** if a real run reports it cannot find a browser, re-run
  `install-browser.ps1`; confirm `%LOCALAPPDATA%\BAP\data\ms-playwright` exists
  and is non-empty. Behind a corporate proxy, set `HTTPS_PROXY` before running it.

Then, from the CLI:

```powershell
bap run "%LOCALAPPDATA%\BAP\config\app.yaml" --real --seconds 30
```

---

## 5. Troubleshooting

| Symptom | What to do |
|---|---|
| App won't start | Open `%LOCALAPPDATA%\BAP\logs\bap-gui.log` — the last lines usually explain why. |
| A config error on launch | Run `bap validate-config <your config>`; the message names the file, field, and a suggested fix. |
| Real run: "no browser" | Run `install-browser.ps1` (section 4). |
| It crashed | Look in `%LOCALAPPDATA%\BAP\data\crashes\` for a `crash-*.json` bundle (section 7) and attach it to your report. |
| SmartScreen blocks it | *More info → Run anyway* (unsigned beta build). |
| Nothing is persisted | Persistence is opt-in — pass `--store <path>`; without it the app only logs. |
| Want machine-readable logs | Run the CLI with `--log-format json`. |

---

## 6. Collecting logs

To send a report, gather:

- `%LOCALAPPDATA%\BAP\logs\` — `bap.log` and/or `bap-gui.log` (plus rotated
  `.1`, `.2` files).
- `%LOCALAPPDATA%\BAP\data\crashes\` — any `crash-*.json` from around the time
  of the problem.

Quick way to zip them (PowerShell):

```powershell
Compress-Archive -Path "$env:LOCALAPPDATA\BAP\logs\*","$env:LOCALAPPDATA\BAP\data\crashes\*" `
    -DestinationPath "$env:USERPROFILE\Desktop\bap-logs.zip"
```

Logs contain ids, timings, statuses, and error categories — **not** the text
you type, page contents, selectors, or URLs.

---

## 7. Crash reports (local only)

On a fatal error the app writes a self-contained JSON **crash bundle** to
`%LOCALAPPDATA%\BAP\data\crashes\crash-<timestamp>.json`. It contains: the time,
app version, OS/runtime info, the exception and traceback, the last operational
status, and a tail of recent log lines. **Nothing is sent anywhere** — there is
no telemetry; the file is yours to inspect or attach to a report.

---

## 8. Uninstall

Uninstall from **Settings → Apps → Browser Automation Platform → Uninstall**, or
Start Menu → *Uninstall Browser Automation Platform*. The uninstaller removes the
application files and shortcuts, then asks whether to also remove your data
(`%LOCALAPPDATA%\BAP`: config, logs, history, crashes). Choose **No** to keep
your configuration and history for a future reinstall.
