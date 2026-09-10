# Windows Installation Checklist (Beta)

A step-by-step checklist for installing and validating the Browser Automation
Platform on a clean **Windows 10/11 (64-bit)** machine — **no Python, Git, or
command line required**. Tick each box; if any step fails, export diagnostics
(step 9) and attach them to your report.

> Everything here is done with the mouse. The optional command-line notes are
> only for testers who want them.

## A. Before you start

- [ ] Windows 10 or 11, 64-bit.
- [ ] ~1 GB free disk space (more if you install the real browser: +~400 MB).
- [ ] You have the installer file **`BAP-Setup-0.1.0.exe`** and (optionally) its
      **`.sha256`** checksum file.

## B. (Optional) Verify the download

- [ ] Right-click `BAP-Setup-0.1.0.exe` → *Properties* to confirm the size looks
      right, **or** in PowerShell:
      `Get-FileHash .\BAP-Setup-0.1.0.exe -Algorithm SHA256` and compare to the
      `.sha256` file.

## C. Install

- [ ] Double-click **`BAP-Setup-0.1.0.exe`**.
- [ ] If **SmartScreen** appears ("Windows protected your PC"), click
      **More info → Run anyway** (this is an unsigned beta).
- [ ] The installer runs **without asking for an administrator password**
      (it installs just for you).
- [ ] Finish the wizard. Leave **"Launch Browser Automation Platform"** ticked.

## D. First launch & the welcome wizard

- [ ] The app opens and a **Welcome** dialog appears on first run.
- [ ] Read it: the app starts in safe **demo (stub) mode** — no browser, no
      network.
- [ ] Click **Continue** (or **Install browser now…** if you want real
      automation right away — see step F).

## E. Confirm it works (demo mode, no browser)

- [ ] In the main window click **Start** — rows update and the **Status** shows
      *ready*.
- [ ] Click **Stop** — Status returns to *stopped*.
- [ ] Click **Tick once** — a single round runs and the log shows activity.

## F. (Optional) Install the real browser — no command line

- [ ] Menu **Tools → Install browser…**.
- [ ] Click **Install now**. A progress log appears; wait for
      **"Browser installed successfully."** (~300–450 MB download).
- [ ] Close the dialog. Real automation (`--real`) can now launch a browser.

## G. (Optional) Run a real example

- [ ] Menu **Tools → Open data folder** to find your config at
      `config\app.yaml` (edit it with Notepad to point at a real site if you
      like).
- [ ] Testers only (command line): from `%LOCALAPPDATA%\Programs\BAP`,
      `bap.exe run "%LOCALAPPDATA%\BAP\config\app.yaml" --real --seconds 30`.

## H. Persistence check

- [ ] Menu **Tools → Open data folder**; confirm a **`logs`** folder exists with
      a log file.
- [ ] Testers only: run with `--store "%LOCALAPPDATA%\BAP\data\history.db"` and
      confirm the `.db` file is created and grows.

## I. Diagnostics export (for reporting issues)

- [ ] Menu **Tools → Export diagnostics…**.
- [ ] Confirm a **`bap-diagnostics-<date>.zip`** is saved (to your Desktop by
      default) and click **Open folder** to see it.
- [ ] The zip contains logs, any crash reports, your config, and system info —
      and nothing leaves your machine.

## J. Uninstall (clean removal)

- [ ] **Settings → Apps → Browser Automation Platform → Uninstall**, or Start
      Menu → *Uninstall Browser Automation Platform*.
- [ ] When asked whether to also remove your data (`%LOCALAPPDATA%\BAP`), choose
      **Yes** to remove everything or **No** to keep your config/history.
- [ ] Confirm the Start Menu entry and `%LOCALAPPDATA%\Programs\BAP` are gone.

---

### If something goes wrong

1. Menu **Tools → Export diagnostics…** (or, if the app won't open, zip
   `%LOCALAPPDATA%\BAP\logs` and `%LOCALAPPDATA%\BAP\data\crashes`).
2. Note which step above failed and what you saw.
3. Send the diagnostics zip with your report.

See **[WINDOWS_BETA.md](WINDOWS_BETA.md)** for the full user guide and a
troubleshooting table.
