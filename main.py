import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from marketplace_app.db import (
    get_policy_catalog,
    initialize_database,
    list_decisions,
    list_recent_submissions,
)
from marketplace_app.engine import evaluate_listing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(title="TikTok Shop Listing Safety Triage Engine", lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "listing_safety_triage_engine"}


@app.get("/api/listings/history")
async def listing_history(limit: int = 10):
    safe_limit = max(1, min(limit, 500))
    return {
        "submissions": list_recent_submissions(limit=safe_limit),
        "decisions": list_decisions(limit=safe_limit),
    }


@app.get("/api/policies")
async def policy_catalog():
    return get_policy_catalog()


@app.post("/api/listings/stream")
async def stream_listing_evaluation(request: Request):
    payload: dict[str, Any] = await request.json()
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def report_step(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def run_evaluation() -> dict[str, Any]:
        try:
            return evaluate_listing(payload, report_step)
        finally:
            loop.call_soon_threadsafe(event_queue.put_nowait, {"stream_end": True})

    evaluation = asyncio.create_task(asyncio.to_thread(run_evaluation))

    async def event_stream():
        while True:
            event = await event_queue.get()
            if event.get("stream_end"):
                break
            yield f"data: {json.dumps({'type': 'step', **event}, ensure_ascii=False)}\n\n"

        try:
            result = await evaluation
        except Exception:
            logger.exception("Listing evaluation failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'The listing could not be evaluated. Check the server log for details.'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'complete', 'result': result}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/listings/submit")
async def submit_listing(request: Request):
    payload = await request.json()
    result = await asyncio.to_thread(evaluate_listing, payload)

    return JSONResponse(
        content={
            "submission_id": result["submission_id"],
            "vendor_id": result["vendor_id"],
            "decision": result["decision"],
            "status": result["status"],
            "policy_version": result["policy_version"],
            "matched_rule_ids": result["matched_rule_ids"],
            "reason_codes": result["reason_codes"],
            "review_queue_id": result["review_queue_id"],
            "extracted_payload": result["extracted_payload"],
            "trace": result["trace"],
            "raw_payload": payload,
            "history": {
                "submissions": list_recent_submissions(limit=8),
                "decisions": list_decisions(limit=8),
            },
        },
        status_code=422 if result["decision"] == "reject" else 200,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)





