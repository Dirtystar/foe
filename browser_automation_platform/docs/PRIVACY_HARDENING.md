# Privacy & source hardening

Goal: nothing anywhere ties this project to your real name, your game nick, or your game
account — not in the code, the website, the installer, or **git**.

## Done in the repo

- All source, docs, samples and tests scrubbed of the nick / name / personal paths
  (`git grep` for them returns nothing).
- `pyproject.toml` carries no author name or email.
- Local git identity set to a neutral `dev <dev@localhost>` so **new** commits don't stamp you.

## You must still do these (outside the tools' reach)

### 1. Make the repo private — now
GitHub → repo → **Settings → General → Danger Zone → Change visibility → Private**.
This is the single most important step and takes 10 seconds.

### 2. The two leaks the file-scrub can't fix

**a) Git history has your email.** Past commits were authored by your real email — it's baked
into every old commit's metadata and is public in the history. **b) The repo is named after your
nick** (`<nick>/foe`). Renaming the file contents doesn't change either.

The clean, low-risk fix is to **start a fresh repo with no history**, under a neutral account:

```bash
# 1) make a NEW GitHub account/org with a neutral name (not your nick), create a PRIVATE repo
# 2) from a clean checkout of the current code:
rm -rf .git                     # drop all history (and its author metadata)
git init
git config user.name "dev"
git config user.email "dev@localhost"
git add .
git commit -m "Initial commit"
git remote add origin git@github.com:<neutral-name>/<neutral-repo>.git
git branch -M main
git push -u origin main
```

Then **delete the old `<nick>/foe` repo** (or keep it private and unused). New name, one commit,
no author history, no nick.

> Alternative if you must keep history: `git filter-repo --email-callback` to rewrite the author
> email everywhere, then force-push. It's heavier and still leaves the repo name — the fresh repo
> above is simpler and cleaner.

### 3. The shipped app & website
- **Change the licence secret** before building: set `FOE_LICENSE_SECRET` (and the Worker's
  `LICENSE_SECRET`) to a private value — not the `CHANGE-ME` default.
- Ship **obfuscated / compiled** builds, not raw `.py` (e.g. PyInstaller one-file, optionally a
  bytecode obfuscator). Source stays in the private repo; users get only the installer.
- The website (`shop/`) and app strings carry no personal identifiers — keep it that way; don't
  add an "about"/author line.
- Register the store (Lemon Squeezy/Gumroad) and domain under a neutral name/business, not your
  game identity.

### 4. Operational separation
- Don't use the seller identity (store, domain, support email) anywhere near your **game account**.
- Keep the game nick out of any support chat, changelog, or screenshots you publish.

## Quick self-check before publishing anything
```bash
git grep -niE "<your-nick>|<your-name>|<your-email>"   # must be empty
git log --format='%ae' | sort -u                        # must show only the neutral email
```
