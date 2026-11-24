"""FoE Alerting — a small, self-contained subproject.

It reuses the GBG "brain" (``bap.forge.gbg_data``) **read-only** to answer one question:
*which provinces open, when, and is that an attack or a defence for us?* — and posts that
to a WhatsApp group as one plain line per province::

    16:25 🔵 A1X

Nothing here clicks, fights or writes to the game. It only listens to the data the game
already sends to the browser, and sends text to a messaging gateway.

Layout:

- :mod:`bap.alerting.clock`      — server-clock drift + Europe/Prague ``HH:MM``
- :mod:`bap.alerting.labels`     — province id → the guild's own coordinate ("A1X")
- :mod:`bap.alerting.schedule`   — snapshot → upcoming :class:`UnlockEvent` list
- :mod:`bap.alerting.render`     — events → the message text
- :mod:`bap.alerting.notifiers`  — Green API / console / null transports
- :mod:`bap.alerting.state`      — "already announced" memory (survives restarts)
- :mod:`bap.alerting.config`     — the JSON config + env-var secrets
- :mod:`bap.alerting.engine`     — snapshot in → messages out (browser-free, testable)
- :mod:`bap.alerting.watcher`    — the thin CDP wiring that feeds the engine
"""

from __future__ import annotations

__all__ = ["clock", "labels", "schedule", "render", "notifiers", "state", "config", "engine"]
