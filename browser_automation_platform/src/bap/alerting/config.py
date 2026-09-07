"""Configuration: one small JSON file, secrets preferably from the environment.

    {
      "world": "cz8",
      "scope": "relevant",
      "trigger_lead_minutes": 4,
      "window_minutes": 30,
      "labels_file": "province_labels.cz8.json",
      "notifier": "green_api",
      "green_api": {"chat_id": "120363000000000000@g.us"},
      "quiet_hours": [23, 7]
    }

``green_api.id_instance`` / ``api_token`` are read from ``GREEN_API_ID_INSTANCE`` /
``GREEN_API_TOKEN`` (and ``GREEN_API_CHAT_ID``) when present, so the credentials never have
to sit in a file that might get shared or committed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from bap.alerting.notifiers import GREEN_API_BASE
from bap.alerting.render import DEFAULT_TEMPLATE
from bap.alerting.schedule import SCOPES, SIDE_RULES

DEFAULT_CONFIG_PATH = "alerting.json"


@dataclass
class GreenApiConfig:
    id_instance: str = ""
    api_token: str = ""
    chat_id: str = ""
    base_url: str = GREEN_API_BASE

    @classmethod
    def from_dict(cls, d: dict | None) -> "GreenApiConfig":
        d = d or {}
        return cls(
            id_instance=str(os.environ.get("GREEN_API_ID_INSTANCE")
                            or d.get("id_instance") or ""),
            api_token=str(os.environ.get("GREEN_API_TOKEN") or d.get("api_token") or ""),
            chat_id=str(os.environ.get("GREEN_API_CHAT_ID") or d.get("chat_id") or ""),
            base_url=str(d.get("base_url") or GREEN_API_BASE),
        )


@dataclass
class AlertConfig:
    """Everything the watcher needs. Every field has a working default except the chat id."""

    world: str = "cz8"                     # the ONE world this alerter watches
    tab: str = ""                          # tab match; defaults to "<world>.forgeofempires"
    cdp: str = ""                          # Chrome CDP endpoint; "" → the app default
    scope: str = "relevant"                # labeled | relevant | mine | all
    trigger_lead_minutes: float = 4.0      # speak when the soonest opening is this close
    window_minutes: float = 30.0           # …and then list everything opening within this
    side_rule: str = "battle_type"         # battle_type | owner — see schedule.side_of
    show_attrition: bool = True            # append the map's "[20%]" badge
    message_template: str = DEFAULT_TEMPLATE   # one line's layout; see render.PLACEHOLDERS
    stale_minutes: float = 5.0             # never announce an opening older than this
    poll_seconds: float = 30.0             # how often the engine re-checks the schedule
    horizon_hours: float = 12.0            # ignore openings further out than this
    quiet_hours: tuple[int, int] | None = None   # e.g. (23, 7) Prague — stay silent overnight
    header: str = ""                       # optional first line of the message
    labels_file: str = ""
    state_file: str = "alert_state.json"
    notifier: str = "console"              # console | green_api | webhook | null
    webhook_url: str = ""
    green_api: GreenApiConfig = field(default_factory=GreenApiConfig)

    @property
    def tab_match(self) -> str:
        return self.tab or f"{self.world}.forgeofempires"

    @property
    def trigger_lead_seconds(self) -> int:
        return int(self.trigger_lead_minutes * 60)

    @property
    def window_seconds(self) -> int:
        return int(self.window_minutes * 60)

    @property
    def stale_seconds(self) -> int:
        return int(self.stale_minutes * 60)

    @property
    def horizon_seconds(self) -> int:
        return int(self.horizon_hours * 3600)

    @classmethod
    def from_dict(cls, d: dict | None) -> "AlertConfig":
        d = dict(d or {})
        quiet = d.get("quiet_hours")
        if isinstance(quiet, (list, tuple)) and len(quiet) == 2:
            try:
                quiet = (int(quiet[0]) % 24, int(quiet[1]) % 24)
            except (TypeError, ValueError):
                quiet = None
        else:
            quiet = None
        scope = str(d.get("scope") or cls.scope)
        if scope not in SCOPES:
            scope = cls.scope
        side_rule = str(d.get("side_rule") or cls.side_rule)
        if side_rule not in SIDE_RULES:
            side_rule = cls.side_rule
        def _num(key, default):
            try:
                return float(d[key])
            except (KeyError, TypeError, ValueError):
                return default
        # "lead_minutes" was the pre-batching name for the trigger lead; still accepted.
        lead = _num("trigger_lead_minutes", _num("lead_minutes", cls.trigger_lead_minutes))
        return cls(
            world=str(d.get("world") or cls.world),
            tab=str(d.get("tab") or ""),
            cdp=str(d.get("cdp") or ""),
            scope=scope,
            trigger_lead_minutes=lead,
            window_minutes=_num("window_minutes", cls.window_minutes),
            side_rule=side_rule,
            show_attrition=bool(d.get("show_attrition", cls.show_attrition)),
            message_template=str(d.get("message_template") or cls.message_template),
            stale_minutes=_num("stale_minutes", cls.stale_minutes),
            poll_seconds=_num("poll_seconds", cls.poll_seconds),
            horizon_hours=_num("horizon_hours", cls.horizon_hours),
            quiet_hours=quiet,
            header=str(d.get("header") or ""),
            labels_file=str(d.get("labels_file") or ""),
            state_file=str(d.get("state_file") or cls.state_file),
            notifier=str(d.get("notifier") or cls.notifier),
            webhook_url=str(d.get("webhook_url") or ""),
            green_api=GreenApiConfig.from_dict(d.get("green_api")),
        )

    @classmethod
    def load(cls, path=DEFAULT_CONFIG_PATH) -> "AlertConfig":
        """Read the config file; a missing file is fine (defaults + env still apply)."""
        p = Path(path)
        if not p.is_file():
            return cls.from_dict({})
        try:
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return cls.from_dict({})

    def in_quiet_hours(self, hour: int) -> bool:
        """True when Prague ``hour`` falls inside the configured silence window
        (wrapping over midnight)."""
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        if start == end:
            return False
        return start <= hour < end if start < end else (hour >= start or hour < end)


__all__ = ["AlertConfig", "GreenApiConfig", "DEFAULT_CONFIG_PATH"]
