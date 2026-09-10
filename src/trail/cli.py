"""The `trail` command (SPEC 14).

Only the Mac side lives here, so it may use the `[mac]` extras freely. The notebook
package must never import this module.
"""

from __future__ import annotations

import sys
from pathlib import Path

MISSING_EXTRAS = "The trail command needs the Mac extras: uv tool install -e '.[mac]'"

try:
    import typer
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - exercised by hand, not in CI

    def app() -> None:
        print(MISSING_EXTRAS, file=sys.stderr)
        raise SystemExit(1)
else:
    from trail import config as config_mod
    from trail._version import __version__
    from trail.common.paths import ProjectPaths
    from trail.common.paths import projects as list_projects
    from trail.engine import overrides as overrides_mod
    from trail.engine.build import Build, EngineConfig, build_cached
    from trail.engine.grouping import Version
    from trail.engine.metrics import primary_name

    app = typer.Typer(
        add_completion=False, help="Record and revise how your notebook code evolved."
    )
    console = Console()

    GREEN, RED, AMBER, DIM = "green", "red", "yellow", "dim"

    # -- shared helpers ----------------------------------------------------

    def _fail(message: str, hint: str | None = None) -> None:
        console.print(f"[red]{message}[/red]")
        if hint:
            console.print(f"  {hint}")
        raise typer.Exit(1)

    def _root(logs: str | None = None) -> Path:
        root = config_mod.resolve_root(logs)
        if root is None or not root.is_dir():
            _fail(
                "I can't find your logs folder.",
                "Run `trail init`, or set TRAIL_ROOT, or pass --logs PATH.",
            )
        assert root is not None
        return root

    def _pick_project(root: Path, project: str | None) -> str:
        found = list_projects(root)
        if not found:
            _fail(
                f"No projects in {root}.",
                'Record one first: trail.start("my-project") in a notebook.',
            )
        if project:
            if project in found:
                return project
            _fail(f"No project called {project!r}.", f"Found: {', '.join(found)}")
        # Default to whatever was touched most recently, and say which.
        newest = max(found, key=lambda name: _last_activity(root / name))
        if len(found) > 1:
            console.print(f"[dim]Using the most recent project: {newest}[/dim]")
        return newest

    def _last_activity(project_dir: Path) -> float:
        runs = project_dir / "runs"
        if not runs.is_dir():
            return 0.0
        times = [p.stat().st_mtime for p in runs.glob("*.jsonl")]
        return max(times) if times else 0.0

    def _engine_config() -> EngineConfig:
        settings = config_mod.load().engine
        return EngineConfig(
            minor_max_chars=int(settings.get("minor_max_chars", 12)),
            fuzzy_threshold=float(settings.get("fuzzy_threshold", 0.5)),
            extra_metric_patterns=list(settings.get("extra_metric_patterns") or []),
        )

    def _build(root: Path, project: str, force: bool = False) -> tuple[Build, ProjectPaths]:
        paths = ProjectPaths(root, project)
        return build_cached(paths, _engine_config(), force=force), paths

    # -- formatting --------------------------------------------------------

    def _metric_text(version: Version, previous: Version | None) -> Text:
        name = primary_name(version.metrics)
        if name is None or name == "duration_s":
            return Text(f"{version.metrics.get('duration_s', {}).get('final', 0):.2f}s", style=DIM)

        value = version.metrics[name]["final"]
        text = Text(f"{name} {value:.4g}")
        if previous is None or name not in previous.metrics:
            return text

        before = previous.metrics[name]["final"]
        delta = value - before
        noise = version.loss_std or previous.loss_std
        if delta == 0:
            text.append("  unchanged", style=DIM)
        elif noise and abs(delta) <= noise:
            text.append(f"  ≈{abs(delta):.4g} (within noise)", style=DIM)
        elif delta < 0:
            text.append(f"  ↓{abs(delta):.4g}", style=GREEN)
        else:
            text.append(f"  ↑{abs(delta):.4g}", style=RED)
        return text

    def _plural(count: int, noun: str) -> str:
        return f"{count} {noun}" if count == 1 else f"{count} {noun}s"

    def _one_line_change(before: Version | None, after: Version) -> str:
        """Describe a tiny edit inline, e.g. "lr = 1.5 → lr = 0.5".

        why: collapsing minor versions to "2 small edits" can hide the whole point of
        a lecture — a learning rate going 1.5 → 0.5 is three characters and the entire
        lesson. Show the change, stay on one line.
        """
        if before is None:
            return ""
        import difflib

        old = [ln.strip() for ln in before.code.split("\n") if ln.strip()]
        new = [ln.strip() for ln in after.code.split("\n") if ln.strip()]
        pairs = [
            (old[i1:i2], new[j1:j2])
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new).get_opcodes()
            if op != "equal"
        ]
        # A replace block of equal length is a line-for-line edit; pair them up so
        # "lr = 1.5 / steps = 60" → "lr = 0.5 / steps = 120" reads as two changes.
        edits: list[tuple[list[str], list[str]]] = []
        for removed, added in pairs:
            if removed and added and len(removed) == len(added):
                edits.extend(([r], [a]) for r, a in zip(removed, added, strict=True) if r != a)
            else:
                edits.append((removed, added))

        described: list[str] = []
        for removed, added in edits[:2]:
            if len(removed) == 1 and len(added) == 1:
                described.append(f"{removed[0][:30]} → {added[0][:30]}")
            elif not removed and len(added) == 1:
                described.append(f"+ {added[0][:40]}")
            elif not added and len(removed) == 1:
                described.append(f"- {removed[0][:40]}")
            else:
                return ""
        if len(edits) > 2:
            described.append("…")
        return ", ".join(described)

    def _run_spread(version: Version) -> str:
        """Flag a version whose identical code produced very different numbers.

        why: version metrics come from the latest ok run (SPEC 10.7), so a cell that
        diverged at 3.9e+47 and later converged at 0.26 would silently show only 0.26.
        The same code behaving differently is a fact worth seeing — usually it means
        another cell changed in between.
        """
        finals = version.run_finals
        if len(finals) < 2:
            return ""
        low, high = min(finals), max(finals)
        if low == high:
            return ""
        scale = max(abs(low), abs(high)) or 1.0
        if (high - low) / scale < 0.01:
            return ""
        return f"was {finals[0]:.4g} on the first run"

    def _version_line(version: Version, previous: Version | None) -> Text:
        marker = "◆" if version.marked else ("·" if version.minor else "●")
        style = AMBER if version.marked else ("dim" if version.minor else "")
        line = Text(f"  {marker} v{version.n:<3}", style=style)
        line.append_text(_metric_text(version, previous))

        extras: list[str] = []
        if len(version.runs) > 1:
            extras.append(_plural(len(version.runs), "run"))
        if version.attempts:
            errors = ", ".join(sorted({a.error_type or "error" for a in version.attempts}))
            extras.append(f"{_plural(len(version.attempts), 'failed attempt')} ({errors})")
        if version.failed_runs:
            extras.append(_plural(len(version.failed_runs), "later failure"))
        if version.loss_std:
            extras.append(f"noise ±{version.loss_std:.4g}")
        spread = _run_spread(version)
        if spread:
            extras.append(spread)
        if extras:
            line.append(f"   {' · '.join(extras)}", style=DIM)
        if version.marked and version.note:
            line.append(f"\n      ↳ {version.note}", style=AMBER)
        return line

    # -- commands ----------------------------------------------------------

    @app.command()
    def version() -> None:
        """Show versions of Trail, Python and claude."""
        import platform
        import shutil
        import subprocess

        console.print(f"trail  {__version__}")
        console.print(f"python {platform.python_version()}")
        binary = shutil.which("claude")
        if binary is None:
            console.print("claude [dim]not on PATH[/dim]")
            return
        try:
            out = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=15
            ).stdout.strip()
            console.print(f"claude {out or binary}")
        except (OSError, subprocess.SubprocessError):
            console.print(f"claude [dim]{binary} (couldn't run --version)[/dim]")

    @app.command()
    def projects(logs: str = typer.Option(None, "--logs", help="Logs root")) -> None:
        """List recorded projects."""
        import datetime as dt

        root = _root(logs)
        found = list_projects(root)
        if not found:
            console.print(f"No projects yet in {root}.")
            return

        table = Table(title=f"Projects in {root}", title_style="", box=None, pad_edge=False)
        table.add_column("project")
        table.add_column("last activity")
        table.add_column("cells", justify="right")
        table.add_column("versions", justify="right")
        table.add_column("checkpoints", justify="right")

        for name in sorted(found, key=lambda n: -_last_activity(root / n)):
            result, _ = _build(root, name)
            stamp = _last_activity(root / name)
            when = dt.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M") if stamp else "never"
            visible = [c for c in result.cells if not c.hidden]
            table.add_row(
                name,
                when,
                str(len(visible)),
                str(sum(len(c.versions) for c in visible)),
                str(len(result.steps)),
            )
        console.print(table)

    @app.command()
    def log(
        project: str = typer.Argument(None, help="Project name (default: most recent)"),
        cell: str = typer.Option(None, "--cell", help="Only this cell"),
        show_all: bool = typer.Option(
            False, "--all", help="Include minor versions and setup cells"
        ),
        sessions: bool = typer.Option(False, "--sessions", help="Show the session strip"),
        logs: str = typer.Option(None, "--logs", help="Logs root"),
    ) -> None:
        """Print the history of a project as a timeline."""
        root = _root(logs)
        name = _pick_project(root, project)
        result, paths = _build(root, name)

        if not result.cells:
            console.print(f"[dim]{name} has no recorded runs yet.[/dim]")
            return

        total_runs = len(result.runs)
        console.print()
        console.print(
            f"[bold]{name}[/bold]  {_plural(total_runs, 'run')} · "
            f"{_plural(len(result.cells), 'cell')} · "
            f"{_plural(len(result.steps), 'checkpoint')}"
        )

        if sessions:
            console.print()
            for session in sorted(result.loaded.sessions.values(), key=lambda s: s.start):
                state = "clean" if session.clean else "[yellow]ended by restart/crash[/yellow]"
                console.print(
                    f"  [dim]{session.start[:19]}[/dim]  {session.frontend or '?':<8} {state}"
                )

        cells = result.cells if cell is None else [c for c in result.cells if _matches(c, cell)]
        if cell is not None and not cells:
            _fail(
                f"No cell matching {cell!r}.",
                f"Try one of: {', '.join(c.name for c in result.cells[:8])}",
            )

        hidden_count = 0
        for item in cells:
            if item.hidden and not show_all and cell is None:
                hidden_count += 1
                continue
            _print_cell(item, show_all)

        if hidden_count:
            console.print(
                f"\n[dim]{_plural(hidden_count, 'setup cell')} hidden — use --all to show.[/dim]"
            )

        if result.warnings:
            console.print("\n[yellow]Warnings[/yellow]")
            for warning in result.warnings:
                console.print(f"  • {warning}")

        if result.steps:
            console.print(
                f"\n[dim]{_plural(len(result.steps), 'checkpoint')} ready to explain — "
                f"`trail analyze {name}` arrives in M5.[/dim]"
            )
        console.print(f"[dim]built from {paths.runs}[/dim]\n")

    def _matches(cell_obj, needle: str) -> bool:
        return needle in (cell_obj.key, cell_obj.name) or cell_obj.key.split(":", 1)[-1] == needle

    def _print_cell(cell_obj, show_all: bool) -> None:
        header = Text(f"\n{cell_obj.name}", style="bold")
        header.append(f"  [{cell_obj.key}]", style=DIM)
        if cell_obj.hidden:
            header.append("  setup", style=DIM)
        console.print(header)

        previous: Version | None = None
        collapsed: list[Version] = []
        before_collapse: Version | None = None

        def flush() -> None:
            nonlocal collapsed, before_collapse
            if not collapsed:
                return
            change = _one_line_change(before_collapse, collapsed[-1])
            label = _plural(len(collapsed), "small edit")
            suffix = f"  ({change})" if change else ""
            console.print(f"    [dim]· {label}{suffix}[/dim]")
            collapsed, before_collapse = [], None

        for version in cell_obj.versions:
            if version.minor and not show_all and not version.marked:
                if not collapsed:
                    before_collapse = previous
                collapsed.append(version)
                previous = version
                continue
            flush()
            console.print(_version_line(version, previous))
            previous = version
        flush()

    @app.command()
    def rebuild(
        project: str = typer.Argument(None),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Force the engine to rebuild derived/versions.json."""
        root = _root(logs)
        name = _pick_project(root, project)
        result, paths = _build(root, name, force=True)
        console.print(
            f"Rebuilt {name}: {len(result.cells)} cells, "
            f"{sum(len(c.versions) for c in result.cells)} versions, "
            f"{_plural(len(result.steps), 'checkpoint')} → {paths.derived / 'versions.json'}"
        )

    @app.command()
    def show(
        project: str = typer.Argument(None),
        cell: str = typer.Argument(..., help="Cell name or identity"),
        a: int = typer.Argument(None, help="Version A (default: step start)"),
        b: int = typer.Argument(None, help="Version B (default: latest)"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Diff two versions of a cell in the terminal."""
        import difflib

        root = _root(logs)
        name = _pick_project(root, project)
        result, _ = _build(root, name)
        target = result.cell(cell)
        if target is None:
            _fail(
                f"No cell matching {cell!r}.", f"Try: {', '.join(c.name for c in result.cells[:8])}"
            )
        assert target is not None

        numbers = {v.n: v for v in target.versions}
        b_n = b if b is not None else target.versions[-1].n
        a_n = (
            a
            if a is not None
            else (target.versions[0].n if len(target.versions) == 1 else target.versions[-2].n)
        )
        if a_n not in numbers or b_n not in numbers:
            _fail(f"Versions are 1..{target.versions[-1].n}.")

        left, right = numbers[a_n], numbers[b_n]
        console.print(f"\n[bold]{target.name}[/bold]  v{a_n} → v{b_n}\n")

        for line in difflib.unified_diff(
            left.code.split("\n"),
            right.code.split("\n"),
            fromfile=f"v{a_n}",
            tofile=f"v{b_n}",
            lineterm="",
        ):
            style = ""
            if line.startswith("+") and not line.startswith("+++"):
                style = GREEN
            elif line.startswith("-") and not line.startswith("---"):
                style = RED
            elif line.startswith("@@"):
                style = DIM
            console.print(Text(line, style=style))

        console.print()
        console.print(_metric_text(right, left))
        console.print()

    cells_app = typer.Typer(help="Fix how cells were identified.")
    app.add_typer(cells_app, name="cells")

    @cells_app.callback(invoke_without_command=True)
    def cells_list(
        ctx: typer.Context,
        project: str = typer.Option(None, "--project", help="Project name"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """List the cells Trail found. why: a positional argument here would be
        consumed as the subcommand name, so the project is an option."""
        if ctx.invoked_subcommand is not None:
            return
        root = _root(logs)
        name = _pick_project(root, project)
        result, _ = _build(root, name)
        table = Table(box=None, pad_edge=False)
        table.add_column("identity")
        table.add_column("name")
        table.add_column("versions", justify="right")
        table.add_column("")
        for item in result.cells:
            table.add_row(
                item.key, item.name, str(len(item.versions)), "setup" if item.hidden else ""
            )
        console.print(table)

    def _edit_overrides(project: str | None, logs: str | None, mutate) -> None:
        root = _root(logs)
        name = _pick_project(root, project)
        paths = ProjectPaths(root, name)
        current = overrides_mod.load(paths.overrides)
        mutate(current)
        overrides_mod.save(paths.overrides, current)
        console.print(f"Updated {paths.overrides}. Run `trail log {name}` to see the result.")

    @cells_app.command("rename")
    def cells_rename(
        old: str,
        new: str,
        project: str = typer.Option(None, "--project"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Give a cell a friendlier name."""
        _edit_overrides(project, logs, lambda o: o.renames.update({old: new}))

    @cells_app.command("merge")
    def cells_merge(
        source: str,
        into: str,
        project: str = typer.Option(None, "--project"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Merge one identity into another (they were the same cell)."""
        _edit_overrides(project, logs, lambda o: o.merges.append([source, into]))

    @cells_app.command("hide")
    def cells_hide(
        name: str,
        project: str = typer.Option(None, "--project"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Collapse a cell out of the way."""

        def mutate(o):
            o.hidden.append(name)
            if name in o.unhidden:
                o.unhidden.remove(name)

        _edit_overrides(project, logs, mutate)

    @cells_app.command("unhide")
    def cells_unhide(
        name: str,
        project: str = typer.Option(None, "--project"),
        logs: str = typer.Option(None, "--logs"),
    ) -> None:
        """Bring a hidden cell back."""

        def mutate(o):
            o.unhidden.append(name)
            if name in o.hidden:
                o.hidden.remove(name)

        _edit_overrides(project, logs, mutate)
