"""The composition root: assembles runtime objects from configuration.

This is the ONLY module that knows how every layer fits together. It resolves
config type-strings to port implementations, translates config models into
runtime objects, builds the per-profile SessionFactory, and wires the
SessionManager and Scheduler. Construction (`create_application`) is separate
from execution (`Application.start`): building never starts a browser or a
tick, and an invalid mapping fails during construction, before any runtime
resource exists.

No global state: everything is created fresh per call, so two applications
built from the same config are fully independent.
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.app.errors import CompositionError
from bap.app.registries import ActionHandlerRegistry, AnalyzerRegistry
from bap.app.stubs import (
    StubBrowser,
    StubCapturePort,
    default_action_registry,
    default_analyzer_registry,
)
from bap.app.translation import build_capture_binding, build_rule, build_tab_profile
from bap.config.config_models import ApplicationConfig
from bap.core.actions.action_executor import ActionExecutor
from bap.core.engine.browser_controller import BrowserController
from bap.core.engine.scheduler import ReportCallback, Scheduler, SleepFn
from bap.core.engine.session_manager import SessionManager, SessionSpec, TabProvider
from bap.core.engine.tab_session import TabSession
from bap.core.ports.browser_port import BrowserPort
from bap.core.ports.capture_port import CapturePort
from bap.core.rules.rule_engine import RuleEngine
from bap.core.vision.aggregator import Aggregator


@dataclass
class Application:
    """A fully wired but not-yet-running system.

    `session_specs` is the plan (one per profile); `create_sessions` realizes
    it through the manager, and `start` additionally begins ticking. Holding
    the parts as attributes keeps them injectable and inspectable in tests.
    """

    config: ApplicationConfig
    browser: BrowserPort
    browser_controller: BrowserController
    scheduler: Scheduler
    manager: SessionManager
    # The runtime session plan. A list (not a tuple) because Forge edits it live
    # via add/remove/edit World, with no application restart. All mutations go
    # through the async methods below so they happen on the runtime loop thread.
    session_specs: list[SessionSpec]
    vision_executor: object = None  # ThreadPoolExecutor when vision is offloaded

    async def open_browser(self) -> None:
        """Open the browser window (idempotent). Explicit browser lifecycle,
        independent of automation — the user's Open Browser action."""
        await self.browser_controller.open()

    async def close_browser(self) -> None:
        """Close the browser window (idempotent). The user's Close Browser
        action; also the browser half of a full shutdown."""
        await self.browser_controller.close()

    async def create_sessions(self) -> None:
        for spec in list(self.session_specs):
            await self.manager.create_session(spec)

    # --- live session-plan edits (Forge hot CRUD; no restart) ---------------

    def _upsert_spec(self, spec: SessionSpec) -> None:
        for i, existing in enumerate(self.session_specs):
            if existing.profile_id == spec.profile_id:
                self.session_specs[i] = spec
                return
        self.session_specs.append(spec)

    def _drop_spec(self, profile_id: str) -> None:
        self.session_specs[:] = [s for s in self.session_specs if s.profile_id != profile_id]

    async def add_world_session(self, spec: SessionSpec) -> None:
        """Add a world to the plan. It becomes live on the next Start (it has no
        assigned tab yet), so this only updates the plan — never opens a tab."""
        self._upsert_spec(spec)

    async def remove_world_session(self, profile_id: str) -> None:
        """Remove a world from the plan and stop its live session if running.
        The browser tab is untouched (attended close_tab is a no-op)."""
        self._drop_spec(profile_id)
        if profile_id in self.manager.profile_ids:
            await self.manager.close_session(profile_id)

    async def edit_world_session(self, spec: SessionSpec) -> None:
        """Apply edited world settings. If the world is running, its session is
        rebuilt in place (same still-assigned tab) so e.g. a new cadence takes
        effect immediately — without closing the browser."""
        self._upsert_spec(spec)
        if self.scheduler.running and spec.profile_id in self.manager.profile_ids:
            await self.manager.close_session(spec.profile_id)
            await self.manager.create_session(spec)

    async def start(self) -> None:
        """Start automation. Ensures the browser is open first (a no-op if the
        user already opened it in attended mode), then creates sessions and
        begins ticking."""
        await self.browser_controller.open()
        await self.create_sessions()
        await self.scheduler.start()

    async def stop_automation(self) -> tuple[tuple[str, Exception], ...]:
        """Stop automation only. The browser window and its tabs stay open —
        this is what the Stop button does. The vision executor is left running
        because automation may be started again."""
        return await self.manager.stop_automation()

    async def stop(self) -> tuple[tuple[str, Exception], ...]:
        """Full graceful teardown: stop automation, close the browser, and
        release the vision executor. This is the Exit path (and the headless
        runner's shutdown)."""
        errors = list(await self.manager.stop_automation())
        try:
            await self.browser_controller.close()
        except Exception as exc:  # best-effort: report, don't propagate
            errors.append(("__browser__", exc))
        if self.vision_executor is not None:
            # Wait for in-flight analyzers so no worker thread is leaked.
            self.vision_executor.shutdown(wait=True)
        return tuple(errors)


def create_application(
    config: ApplicationConfig,
    *,
    browser: BrowserPort | None = None,
    capture_port: CapturePort | None = None,
    analyzer_registry: AnalyzerRegistry | None = None,
    action_registry: ActionHandlerRegistry | None = None,
    scheduler: Scheduler | None = None,
    sleep: SleepFn | None = None,
    on_report: ReportCallback | None = None,
    vision_workers: int | None = None,
    tab_provider: "TabProvider | None" = None,
    dynamic_profiles: bool = False,
) -> Application:
    """Assemble an Application from validated configuration.

    All collaborators are injectable (defaulting to dev stubs) so real
    adapters — or test doubles — drop in without touching this function.

    `vision_workers` (>0) offloads analyzer execution to a shared
    ThreadPoolExecutor so CPU-bound vision does not block the event loop;
    None keeps vision inline (default).
    """
    if scheduler is not None and (on_report is not None or sleep is not None):
        # An injected scheduler carries its own on_report/sleep; accepting them
        # here too would silently drop these. Fail loudly instead.
        raise ValueError(
            "pass either a pre-built scheduler OR on_report/sleep, not both — "
            "an injected scheduler already carries its own configuration"
        )

    analyzer_registry = analyzer_registry or default_analyzer_registry()
    action_registry = action_registry or default_action_registry()

    _validate_referenced_types(config, analyzer_registry, action_registry)

    # Eager, pure translation — fails here (before any runtime resource) on a
    # bad mapping. Rules are immutable and shared across a pack's sessions;
    # each session gets its own RuleEngine so cooldowns stay per-tab.
    rules_by_pack = {
        name: tuple(build_rule(rule) for rule in rules)
        for name, rules in config.rule_packs.items()
    }
    vision_executor = None
    if vision_workers:
        from concurrent.futures import ThreadPoolExecutor

        if vision_workers <= 0:
            raise ValueError("vision_workers must be > 0")
        vision_executor = ThreadPoolExecutor(
            max_workers=vision_workers, thread_name_prefix="bap-vision"
        )

    bindings_by_profile = {
        profile.id: tuple(
            build_capture_binding(profile.id, binding, analyzer_registry, executor=vision_executor)
            for binding in profile.capture_bindings
        )
        for profile in config.profiles
    }
    profiles_by_id = {profile.id: profile for profile in config.profiles}
    session_specs = [
        SessionSpec(
            tab_profile=build_tab_profile(profile),
            interval_ms=profile.session.interval_ms,
            jitter_ms=profile.session.jitter_ms,
        )
        for profile in config.profiles
    ]

    browser = browser if browser is not None else StubBrowser()
    capture_port = capture_port if capture_port is not None else StubCapturePort()
    scheduler = scheduler if scheduler is not None else Scheduler(sleep=sleep, on_report=on_report)

    def session_factory(spec: SessionSpec, tab) -> TabSession:
        profile = profiles_by_id.get(spec.profile_id)
        if profile is None:
            if not dynamic_profiles:
                raise KeyError(spec.profile_id)
            # A world added at runtime (Forge hot CRUD) that the launch config
            # never had. Build the same uniform capture-only session the Forge
            # config produces: full-canvas capture, no analyzers, no rules, no
            # actions — observe-only, and provably read-only.
            from bap.core.engine.tab_session import CaptureBinding
            from bap.core.vision.pipeline import VisionPipeline

            return TabSession(
                profile_id=spec.profile_id,
                tab=tab,
                capture_port=capture_port,
                bindings=(CaptureBinding(target=None, pipeline=VisionPipeline([])),),
                aggregator=Aggregator(),
                rule_engine=RuleEngine(()),
                action_executor=ActionExecutor([]),
            )
        return TabSession(
            profile_id=spec.profile_id,
            tab=tab,
            capture_port=capture_port,
            bindings=bindings_by_profile[spec.profile_id],
            aggregator=Aggregator(),
            rule_engine=RuleEngine(rules_by_pack[profile.rule_pack]),
            action_executor=ActionExecutor(action_registry.create_all()),
        )

    manager = SessionManager(
        browser=browser,
        scheduler=scheduler,
        session_factory=session_factory,
        max_sessions=config.settings.max_sessions,
        tab_provider=tab_provider,
    )
    browser_controller = BrowserController(browser)

    return Application(
        config=config,
        browser=browser,
        browser_controller=browser_controller,
        scheduler=scheduler,
        manager=manager,
        session_specs=session_specs,
        vision_executor=vision_executor,
    )


def _validate_referenced_types(
    config: ApplicationConfig,
    analyzers: AnalyzerRegistry,
    actions: ActionHandlerRegistry,
) -> None:
    """Fail fast if config names an analyzer or action no registry provides.
    Also instantiates each referenced action handler once and type-checks it,
    so an invalid (e.g. plugin) handler fails during composition — before the
    browser starts — rather than lazily in session_factory. Analyzers are
    validated equivalently when their bindings are built (build_capture_binding)."""
    from bap.core.ports.action_handler_port import ActionHandlerPort

    referenced_actions = {
        action.type
        for rules in config.rule_packs.values()
        for rule in rules
        for action in rule.actions
    }
    for action_type in sorted(referenced_actions):
        if not actions.knows(action_type):
            raise CompositionError(f"no handler registered for action type '{action_type}'")

    # Build every handler once (the ActionExecutor requires one per type) and
    # type-check them, so a bad handler factory is caught here.
    for handler in actions.create_all():
        if not isinstance(handler, ActionHandlerPort):
            raise CompositionError(
                f"action handler for '{handler}' is not an ActionHandlerPort"
            )

    for profile in config.profiles:
        for binding in profile.capture_bindings:
            for analyzer in binding.analyzers:
                if not analyzers.knows(analyzer.type):
                    raise CompositionError(
                        f"profile '{profile.id}', binding '{binding.name}': "
                        f"no analyzer registered for type '{analyzer.type}'"
                    )


__all__ = ["Application", "create_application"]
