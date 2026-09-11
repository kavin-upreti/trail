"""The local viewer (SPEC 13).

Server-rendered Jinja2 with a little vanilla JS. No CDN, no framework, no network
access at all — it has to work on a train. Binds 127.0.0.1 only, escapes every
recorded string, and renders recorded HTML exclusively inside sandboxed iframes
(hard rule 7). Everything on these pages came out of the user's notebook and is
treated as hostile input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trail import config as config_mod
from trail._version import __version__
from trail.analysis import store
from trail.common.paths import ProjectPaths
from trail.common.paths import projects as list_projects
from trail.engine import overrides as overrides_mod
from trail.engine.build import Build, EngineConfig, build_cached
from trail.engine.build import write as write_build
from trail.engine.grouping import Version
from trail.engine.metrics import primary_name
from trail.viewer import diffs
from trail.viewer.jobs import JobQueue

HERE = Path(__file__).resolve().parent
BLOB_NAME = re.compile(r"^[0-9a-f]{64}\.(png|jpg|jpeg|svg)$")


def _engine_config() -> EngineConfig:
    settings = config_mod.load().engine
    return EngineConfig(
        minor_max_chars=int(settings.get("minor_max_chars", 12)),
        fuzzy_threshold=float(settings.get("fuzzy_threshold", 0.5)),
        extra_metric_patterns=list(settings.get("extra_metric_patterns") or []),
    )


def create_app(root: Path) -> FastAPI:
    app = FastAPI(title="Trail", docs_url=None, redoc_url=None)
    jobs = JobQueue()

    templates = Jinja2Templates(directory=str(HERE / "templates"))
    templates.env.filters["metric_name"] = primary_name

    def _markdown(text: str, inline: bool = False) -> str:
        """Render Claude's prose. HTML is disabled (SPEC 13.1) — this text is data.

        why: the analysis is written in Markdown, so without this the page showed
        literal backticks around every `variable` and `function()`.
        """
        if not text:
            return ""
        try:
            from markdown_it import MarkdownIt

            md = MarkdownIt("commonmark", {"html": False, "linkify": False})
            return md.renderInline(text) if inline else md.render(text)
        except ImportError:
            import html as html_mod

            return html_mod.escape(text)

    templates.env.filters["md"] = _markdown
    templates.env.filters["md_inline"] = lambda text: _markdown(text, inline=True)

    def _concept_lookup(concept_id: str):
        from trail.analysis import concepts as concepts_mod

        return concepts_mod.get(concept_id)

    templates.env.filters["concept_lookup"] = _concept_lookup
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    app.state.root = root
    app.state.jobs = jobs

    # -- helpers ----------------------------------------------------------

    def paths_for(project: str) -> ProjectPaths:
        if project not in list_projects(root):
            raise HTTPException(404, f"No project called {project!r}")
        return ProjectPaths(root, project)

    def build_for(project: str, force: bool = False) -> tuple[Build, ProjectPaths]:
        paths = paths_for(project)
        result = build_cached(paths, _engine_config(), force=force)
        result.analysis_state = store.states(paths, result.steps)
        if force:
            write_build(paths, result, result.analysis_state)
        return result, paths

    def stamp(project: str) -> float:
        runs = root / project / "runs"
        if not runs.is_dir():
            return 0.0
        times = [p.stat().st_mtime for p in runs.glob("*.jsonl")]
        return max(times) if times else 0.0

    def page(request: Request, template: str, **context: Any) -> HTMLResponse:
        base = {
            "trail_version": __version__,
            "pygments_css": diffs.pygments_css(),
        }
        base.update(context)
        return templates.TemplateResponse(request, template, base)

    def cell_or_404(result: Build, identity: str):
        cell = result.cell(identity)
        if cell is None:
            raise HTTPException(404, f"No cell {identity!r}")
        return cell

    def version_metrics(version: Version) -> dict[str, Any]:
        name = primary_name(version.metrics)
        return {
            "name": name,
            "final": version.metrics.get(name, {}).get("final") if name else None,
            "duration": version.metrics.get("duration_s", {}).get("final"),
        }

    def spine(cell, result: Build, paths: ProjectPaths) -> list[dict[str, Any]]:
        """One entry per version: the dots down the left of the cell page."""
        out: list[dict[str, Any]] = []
        previous: Version | None = None
        titles = {
            (s.identity, s.end_n): (
                store.load(paths, s).analysis.get("title") if store.load(paths, s) else None
            )
            for s in result.steps
        }
        for version in cell.versions:
            info = version_metrics(version)
            delta = None
            within_noise = False
            if previous is not None and info["name"]:
                before = previous.metrics.get(info["name"], {}).get("final")
                if isinstance(before, (int, float)) and isinstance(info["final"], (int, float)):
                    delta = info["final"] - before
                    noise = version.loss_std or previous.loss_std
                    within_noise = bool(noise and abs(delta) <= noise)
            out.append(
                {
                    "n": version.n,
                    "marked": version.marked,
                    "minor": version.minor,
                    "note": version.note,
                    "metric": info,
                    "delta": delta,
                    "within_noise": within_noise,
                    "runs": len(version.runs),
                    "attempts": len(version.attempts),
                    "loss_std": version.loss_std,
                    "spread": (
                        [min(version.run_finals), max(version.run_finals)]
                        if len(version.run_finals) > 1
                        and min(version.run_finals) != max(version.run_finals)
                        else None
                    ),
                    "title": titles.get((cell.key, version.n)),
                    "sparkline": diffs.sparkline(
                        version.metrics.get(info["name"], {}).get("series", [])
                        if info["name"]
                        else []
                    ),
                }
            )
            previous = version
        return out

    def outputs_for(version: Version, project: str) -> dict[str, Any]:
        run = version.latest_ok or (version.runs[-1] if version.runs else None)
        if run is None:
            return {"stdout": "", "result": None, "images": [], "html": [], "error": None}
        images = [f"/blobs/{project}/{d['blob']}" for d in run.displays if d.get("blob")]
        html_displays = [d.get("html", "") for d in run.displays if d.get("mime") == "text/html"]
        return {
            "stdout": run.stdout,
            "result": run.raw.get("result_repr"),
            "images": images,
            "html": html_displays,
            "error": run.raw.get("error"),
            "duration": run.duration_s,
            "ts": run.ts_start,
        }

    def step_for(result: Build, cell, a: int, b: int):
        for step in result.steps:
            if step.identity == cell.key and step.start_n == a and step.end_n == b:
                return step
        return None

    # -- pages ------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        rows = []
        for name in list_projects(root):
            try:
                result, paths = build_for(name)
            except HTTPException:
                continue
            explained = sum(1 for s in result.steps if result.analysis_state.get(s.key) == "fresh")
            rows.append(
                {
                    "name": name,
                    "cells": len([c for c in result.cells if not c.hidden]),
                    "versions": sum(len(c.versions) for c in result.cells),
                    "steps": len(result.steps),
                    "explained": explained,
                    "last": result.cells[-1].last_ts if result.cells else "",
                    "runs": len(result.runs),
                }
            )
        rows.sort(key=lambda r: r["last"], reverse=True)
        return page(request, "projects.html", projects=rows)

    @app.get("/p/{project}", response_class=HTMLResponse)
    def overview(request: Request, project: str) -> HTMLResponse:
        result, paths = build_for(project)
        cells = []
        for cell in result.cells:
            info = version_metrics(cell.versions[-1]) if cell.versions else {"name": None}
            series = [
                v.metrics.get(info["name"], {}).get("final")
                for v in cell.versions
                if info["name"]
                and isinstance(v.metrics.get(info["name"], {}).get("final"), (int, float))
            ]
            cells.append(
                {
                    "key": cell.key,
                    "name": cell.name,
                    "hidden": cell.hidden,
                    "versions": len(cell.versions),
                    "checkpoints": sum(1 for v in cell.versions if v.marked),
                    "metric": info,
                    "sparkline": diffs.sparkline([s for s in series if s is not None]),
                    "last": cell.last_ts,
                }
            )
        return page(
            request,
            "overview.html",
            section="cells",
            project=project,
            result=result,
            cells=cells,
            sessions=sorted(result.loaded.sessions.values(), key=lambda s: s.start),
            steps=result.steps,
            stamp=stamp(project),
        )

    @app.get("/p/{project}/cell/{identity:path}", response_class=HTMLResponse)
    def cell_page(request: Request, project: str, identity: str, a: int = 0, b: int = 0):
        result, paths = build_for(project)
        cell = cell_or_404(result, identity)
        numbers = [v.n for v in cell.versions]

        # Default to the latest step, which is what you almost always want to see.
        if b not in numbers:
            b = numbers[-1]
        if a not in numbers or a >= b:
            a = numbers[-2] if len(numbers) > 1 else numbers[0]

        by_n = {v.n: v for v in cell.versions}
        left, right = by_n[a], by_n[b]
        step = step_for(result, cell, a, b)
        saved = store.load(paths, step) if step else None

        return page(
            request,
            "cell.html",
            section="cells",
            wide=True,
            project=project,
            cell=cell,
            spine=spine(cell, result, paths),
            a=a,
            b=b,
            left=left,
            right=right,
            rows=diffs.side_by_side(left.code, right.code),
            unified=diffs.unified(left.code, right.code, f"v{a}", f"v{b}"),
            left_out=outputs_for(left, project),
            right_out=outputs_for(right, project),
            left_metrics=version_metrics(left),
            right_metrics=version_metrics(right),
            step=step,
            analysis=saved.analysis if saved else None,
            analysis_meta=saved.meta if saved else None,
            stamp=stamp(project),
        )

    @app.get("/p/{project}/story", response_class=HTMLResponse)
    def story(request: Request, project: str, all: int = 0) -> HTMLResponse:
        result, paths = build_for(project)
        sections = []
        for step in result.steps:
            cell = result.cell(step.identity)
            if cell is None:
                continue
            by_n = {v.n: v for v in cell.versions}
            left, right = by_n.get(step.start_n), by_n.get(step.end_n)
            if left is None or right is None:
                continue
            saved = store.load(paths, step)
            sections.append(
                {
                    "step": step,
                    "cell": cell,
                    "left": left,
                    "right": right,
                    "rows": diffs.side_by_side(left.code, right.code),
                    "unified": diffs.unified(
                        left.code, right.code, f"v{step.start_n}", f"v{step.end_n}"
                    ),
                    "left_out": outputs_for(left, project),
                    "right_out": outputs_for(right, project),
                    "left_metrics": version_metrics(left),
                    "right_metrics": version_metrics(right),
                    "analysis": saved.analysis if saved else None,
                    "first": step.start_n == step.end_n,
                }
            )
        return page(
            request,
            "story.html",
            project=project,
            sections=sections,
            result=result,
            stamp=stamp(project),
        )

    @app.get("/p/{project}/concepts", response_class=HTMLResponse)
    def project_concepts(request: Request, project: str) -> HTMLResponse:
        from trail.analysis import concepts as concepts_mod

        result, paths = build_for(project)
        used: dict[str, list[dict[str, Any]]] = {}
        for step in result.steps:
            saved = store.load(paths, step)
            if not saved:
                continue
            cell = result.cell(step.identity)
            for concept_id in saved.analysis.get("concepts") or []:
                used.setdefault(concept_id, []).append(
                    {
                        "project": project,
                        "cell": cell.name if cell else step.identity,
                        "identity": step.identity,
                        "a": step.start_n,
                        "b": step.end_n,
                        "title": saved.analysis.get("title", ""),
                    }
                )
        entries = [
            {"concept": concepts_mod.get(cid), "uses": uses}
            for cid, uses in sorted(used.items())
            if concepts_mod.get(cid)
        ]
        return page(request, "concepts.html", section="concepts", project=project, entries=entries)

    @app.get("/p/{project}/qa", response_class=HTMLResponse)
    def qa(request: Request, project: str) -> HTMLResponse:
        paths = paths_for(project)
        files = sorted(paths.qa.glob("*.md")) if paths.qa.is_dir() else []
        return page(
            request,
            "qa.html",
            section="qa",
            project=project,
            answers=[{"name": p.stem, "text": p.read_text(encoding="utf-8")} for p in files],
        )

    # -- API --------------------------------------------------------------

    @app.get("/api/p/{project}/stamp")
    def api_stamp(project: str) -> JSONResponse:
        return JSONResponse({"stamp": stamp(project)})

    @app.post("/api/p/{project}/rebuild")
    def api_rebuild(project: str) -> JSONResponse:
        build_for(project, force=True)
        return JSONResponse({"ok": True})

    @app.post("/api/p/{project}/analyze")
    async def api_analyze(project: str, request: Request) -> JSONResponse:
        body = await request.json()
        result, paths = build_for(project)
        wanted = body.get("steps") or []
        if body.get("all_pending"):
            targets = [s for s in result.steps if result.analysis_state.get(s.key) != "fresh"]
        else:
            targets = [s for s in result.steps if s.key in wanted]
        if not targets:
            return JSONResponse({"error": "nothing to analyse"}, status_code=400)

        label = f"Explaining {len(targets)} step" + ("s" if len(targets) != 1 else "")
        job = jobs.submit(label, lambda j: _analyze_job(j, project, [s.key for s in targets]))
        return JSONResponse({"job": job.as_dict()})

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "no such job")
        return JSONResponse(job.as_dict())

    @app.post("/api/p/{project}/cells/{identity:path}")
    async def api_cell_action(project: str, identity: str, request: Request) -> JSONResponse:
        body = await request.json()
        action = body.get("action")
        paths = paths_for(project)
        current = overrides_mod.load(paths.overrides)

        if action == "rename" and body.get("name"):
            current.renames[identity] = str(body["name"])[:80]
        elif action == "hide":
            if identity not in current.hidden:
                current.hidden.append(identity)
            if identity in current.unhidden:
                current.unhidden.remove(identity)
        elif action == "unhide":
            if identity not in current.unhidden:
                current.unhidden.append(identity)
            if identity in current.hidden:
                current.hidden.remove(identity)
        elif action == "merge" and body.get("into"):
            current.merges.append([identity, str(body["into"])])
        else:
            return JSONResponse({"error": f"unknown action {action!r}"}, status_code=400)

        overrides_mod.save(paths.overrides, current)
        build_for(project, force=True)
        return JSONResponse({"ok": True})

    @app.get("/blobs/{project}/{name}")
    def blob(project: str, name: str) -> FileResponse:
        # Validate hard: this is a user-supplied path segment.
        if not BLOB_NAME.match(name):
            raise HTTPException(404, "not found")
        paths = paths_for(project)
        target = (paths.blobs / name).resolve()
        if not target.is_file() or paths.blobs.resolve() not in target.parents:
            raise HTTPException(404, "not found")
        return FileResponse(target)

    @app.get("/concepts", response_class=HTMLResponse)
    def all_concepts(request: Request) -> HTMLResponse:
        from trail.analysis import concepts as concepts_mod

        return page(
            request,
            "concepts.html",
            project=None,
            entries=[{"concept": c, "uses": []} for c in concepts_mod.load().values()],
        )

    # -- job bodies -------------------------------------------------------

    def _analyze_job(job, project: str, step_keys: list[str]) -> None:
        from trail.analysis import project_claude_md
        from trail.analysis.bundle import build_bundle
        from trail.analysis.render import render
        from trail.analysis.runner import AuthProblem, ClaudeNotFound, UsageLimit
        from trail.cli import _analyse_one  # reuse the CLI's single-step logic

        settings = config_mod.load().claude
        result, paths = build_for(project, force=True)
        targets = [s for s in result.steps if s.key in step_keys]

        for index, step in enumerate(targets, start=1):
            job.progress = f"{index}/{len(targets)}"
            cell = result.cell(step.identity)
            job.detail.append(
                f"{cell.name if cell else step.identity} v{step.start_n}→v{step.end_n}"
            )
            try:
                bundle = build_bundle(
                    result, step, paths, include_images=bool(settings.get("include_images", True))
                )
                analysis, meta = _analyse_one(bundle, paths, settings)
            except (ClaudeNotFound, AuthProblem) as exc:
                job.status = "failed"
                job.message = str(exc)
                return
            except UsageLimit:
                job.status = "failed"
                job.message = (
                    f"Hit your usage limit. {len(targets) - index + 1} step(s) still pending — "
                    "they'll be waiting next time."
                )
                return
            except Exception as exc:
                job.detail.append(f"failed: {exc}")
                continue

            saved = store.save(paths, step, analysis, meta)
            saved.with_suffix(".md").write_text(render(analysis, meta), encoding="utf-8")
            job.detail.append(f"✓ {analysis['title']}")

        rebuilt, _ = build_for(project, force=True)
        project_claude_md.write(paths, rebuilt)
        job.message = "done"
        job.result_url = f"/p/{project}/story"

    return app


def serve(root: Path, port: int = 8765, open_browser: bool = True) -> None:
    """Run the viewer. Binds 127.0.0.1 only (hard rule 7)."""
    import threading
    import webbrowser

    import uvicorn

    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(root), host="127.0.0.1", port=port, log_level="warning")


def _json_default(value: Any) -> Any:  # pragma: no cover
    return json.dumps(value, default=str)
