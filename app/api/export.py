"""Exporting the open event's loops: WMVs, review MP4s and PNG stills, as background jobs."""

import threading
import time
import uuid

from fastapi import HTTPException

from loopgen import existing_exports, export_loop, export_pngs, run_checks
from loopgen.slides import Renderer

from app.api.state import keep_version
from app.api.models import ExportBody


def register(app, ctx):
    """The export routes."""
    s, jobs = ctx.s, ctx.jobs

    @app.post("/api/export/existing")
    def export_existing(body: ExportBody):
        """Files an export with these choices would replace, newest first, so the editor can ask first."""
        with s.lock:
            loops = [s.loop(i) for i in body.loops]
        found = [p for lp in loops for p in existing_exports(lp, body.out_dir, body.formats, body.preview_mp4)]
        found.sort(key=lambda p: (p.suffix == ".png", -p.stat().st_mtime))  # the videos first: they matter most
        return {"files": [{"name": p.name, "modified": p.stat().st_mtime} for p in found]}

    @app.post("/api/export")
    def export(body: ExportBody):
        if body.preview_mp4 and "wmv" not in body.formats:
            body.formats = ["wmv", *body.formats]  # the review MP4 is made alongside the WMV
        if not body.loops:
            raise HTTPException(422, "pick at least one loop to export")
        with s.lock:  # checked and registered together, so two clicks can't both start one
            if any(job["state"] == "running" for job in jobs.values()):  # two at once would write the same files
                raise HTTPException(409, "An export is still running. Wait for it to finish, then export again.")
            errors = [i for i in run_checks(s.event, [s.loop(i) for i in body.loops]) if i.level == "error"]
            if errors:  # errors block an export; warnings don't
                raise HTTPException(
                    422, "Fix these first: " + "; ".join(str(e).removeprefix("error: ") for e in errors)
                )
            job = {
                "id": uuid.uuid4().hex[:8],
                "state": "running",
                "done": [],
                "error": None,
                "total": len(body.loops),
                "started": time.time(),
            }
            jobs[job["id"]] = job
            keep_version(s.path)

        def work():
            try:
                with s.lock:
                    event, loops = s.event, [s.loop(i) for i in body.loops]
                renderer = Renderer(event)  # its own renderer, so previews keep working meanwhile
                for loop in loops:
                    job["current"], job["fraction"] = loop.name, 0.0
                    paths, skipped = [], []
                    if "wmv" in body.formats:  # how far through this loop's frames, for the editor's progress line
                        paths += export_loop(
                            event, loop, body.out_dir, body.preview_mp4, renderer, lambda f: job.update(fraction=f)
                        )
                    if "png" in body.formats:
                        if body.replace:  # an earlier, longer loop's extra stills would mix two meets in one folder
                            for old in existing_exports(loop, body.out_dir, ("png",)):
                                old.unlink()
                        pngs, skipped = export_pngs(event, loop, body.out_dir, renderer)
                        paths += pngs
                    job["done"].append(
                        {
                            "loop": loop.name,
                            "files": [str(p) for p in paths],
                            "bytes": sum(p.stat().st_size for p in paths),
                            "skipped": [{"slide": n, "reason": why} for n, why in skipped],
                        }
                    )
                job["state"] = "done"
            except Exception as exc:  # pylint: disable=broad-except  # reported to the editor
                job["state"], job["error"] = "failed", str(exc)
            job["seconds"] = round(time.time() - job["started"], 1)

        threading.Thread(target=work, daemon=True).start()
        return job

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        if job_id not in jobs:
            raise HTTPException(404, "no such job")
        return jobs[job_id]
