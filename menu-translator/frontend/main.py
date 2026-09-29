"""FastAPI proxy for deployed A2A agent on Agent Runtime."""

import base64
import json
import logging
import os
import uuid
from pathlib import Path

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("uvicorn.error")

RESOURCE = os.environ.get("AGENT_ENGINE_RESOURCE_NAME", "")
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")

if not RESOURCE:
    metadata_path = Path(__file__).resolve().parent.parent / "deployment_metadata.json"
    if metadata_path.exists():
        try:
            with open(metadata_path) as f:
                data = json.load(f)
                RESOURCE = data.get("remote_agent_runtime_id", "")
                AGENT_DIRECTORY = data.get("agent_directory", "app")
        except Exception:
            pass

LOCATION = RESOURCE.split("/locations/")[1].split("/")[0] if "/locations/" in RESOURCE else "us-east1"

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"
_A2UI_MIME = "application/json+a2ui"

# One set of ADC credentials, refreshed per request
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


app = FastAPI(title="Menu Translator Frontend")

_contexts: dict[str, str] = {}


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    logger.exception("Server error:")
    return JSONResponse(
        status_code=200,
        content={
            "parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]
        },
    )


def _extract_parts_from_raw(raw_parts: list) -> list[dict]:
    """Turn raw A2A/JSON-RPC parts into structured parts for the chat UI."""
    out: list[dict] = []

    def _unwrap_a2ui(val):
        while isinstance(val, dict) and ("surfaceUpdate" not in val and "beginRendering" not in val):
            if "data" in val and isinstance(val["data"], dict):
                val = val["data"]
            else:
                break
        return val

    for p in raw_parts:
        if isinstance(p, dict):
            if p.get("kind") == "text" or "text" in p:
                text_val = p.get("text", "")
                if text_val:
                    out.append({"kind": "text", "text": text_val})
            elif p.get("kind") == "data" or "data" in p:
                meta = p.get("metadata", {}) or {}
                mime = meta.get("mimeType") if isinstance(meta, dict) else None
                data_val = _unwrap_a2ui(p.get("data"))
                if mime == _A2UI_MIME or isinstance(data_val, (dict, list)):
                    out.append({"kind": "a2ui", "data": data_val})
            elif p.get("kind") == "file" or "file" in p:
                file_obj = p.get("file", {})
                uri = file_obj.get("uri") if isinstance(file_obj, dict) else None
                if uri:
                    out.append({"kind": "text", "text": uri})
        else:
            root = getattr(p, "root", p)
            if hasattr(root, "text") and root.text:
                out.append({"kind": "text", "text": root.text})
            elif getattr(root, "data", None) is not None:
                meta = getattr(root, "metadata", None) or {}
                mime = meta.get("mimeType") if isinstance(meta, dict) else None
                data_val = _unwrap_a2ui(root.data)
                if mime == _A2UI_MIME or isinstance(data_val, (dict, list)):
                    out.append({"kind": "a2ui", "data": data_val})
            elif hasattr(root, "file") and getattr(root.file, "uri", None):
                out.append({"kind": "text", "text": root.file.uri})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "").strip()
    image_data_url = body.get("image")
    user_id = body.get("user_id") or "web-user"

    if not message and image_data_url:
        message = "Please translate this menu, describe each dish, and categorize into [Non-Vegetarian], [Vegetarian], and [Vegan]."

    if not message and not image_data_url:
        return JSONResponse({"parts": [{"kind": "text", "text": "Please provide a message or an image."}]})

    parts: list[dict] = []
    headers = _auth_headers()
    context_id = _contexts.get(user_id)

    client_used = False
    try:
        from a2a.client import ClientConfig, ClientFactory
        from a2a.types import AgentCard, Message, Role, TransportProtocol
        try:
            from a2a.types import Part, TextPart
            use_pydantic_parts = True
        except ImportError:
            from a2a.types import Part
            TextPart = None
            use_pydantic_parts = False

        async with httpx.AsyncClient(headers=headers, timeout=120) as client:
            resp = await client.get(A2A_CARD_URL)
            resp.raise_for_status()
            card = AgentCard(**resp.json())
            card.url = A2A_BASE

            factory = ClientFactory(
                ClientConfig(
                    supported_transports=[
                        TransportProtocol.jsonrpc,
                        TransportProtocol.http_json,
                    ],
                    httpx_client=client,
                )
            )
            a2a_client = factory.create(card)

            if use_pydantic_parts and TextPart is not None:
                msg_parts = [Part(root=TextPart(text=message))] if message else []
            else:
                msg_parts = [Part(text=message)] if message else []

            if image_data_url and "base64," in image_data_url:
                try:
                    from a2a.types import FilePart, FileWithBytes
                    mime = image_data_url.split(";")[0].replace("data:", "")
                    b64_data = image_data_url.split("base64,")[1]
                    msg_parts.append(Part(root=FilePart(file=FileWithBytes(bytes=b64_data, mime_type=mime))))
                except Exception:
                    pass

            msg = Message(
                message_id=str(uuid.uuid4()),
                role=Role.user,
                parts=msg_parts,
                context_id=context_id,
            )

            last_task = None
            from a2a.types import TaskArtifactUpdateEvent
            async for event in a2a_client.send_message(msg):
                if isinstance(event, tuple):
                    task, update = event
                    if task is not None:
                        last_task = task
                        if getattr(task, "context_id", None):
                            _contexts[user_id] = task.context_id
                    if isinstance(update, TaskArtifactUpdateEvent):
                        parts.extend(_extract_parts_from_raw(update.artifact.parts))
            if not parts and last_task is not None:
                for art in getattr(last_task, "artifacts", None) or []:
                    parts.extend(_extract_parts_from_raw(art.parts))
            client_used = True
    except Exception as e:
        logger.info(f"A2A Client SDK path fell back to direct JSON-RPC: {e}")

    # Direct JSON-RPC fallback (always reliable over Agent Runtime HTTP passthrough)
    if not client_used or not parts:
        user_parts = [{"text": message}] if message else []
        if image_data_url and "base64," in image_data_url:
            mime = image_data_url.split(";")[0].replace("data:", "")
            b64_data = image_data_url.split("base64,")[1]
            user_parts.append({
                "kind": "file",
                "file": {
                    "bytes": b64_data,
                    "mimeType": mime,
                }
            })

        rpc_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": str(uuid.uuid4()),
                    "role": "user",
                    "parts": user_parts,
                }
            },
        }
        if context_id:
            rpc_payload["params"]["message"]["contextId"] = context_id

        async with httpx.AsyncClient(headers=headers, timeout=120) as client:
            resp = await client.post(A2A_BASE, json=rpc_payload)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", {})
                if result.get("contextId"):
                    _contexts[user_id] = result["contextId"]
                
                # Check status.message
                status_msg = result.get("status", {}).get("message", {})
                if status_msg and "parts" in status_msg:
                    parts.extend(_extract_parts_from_raw(status_msg["parts"]))
                
                # Check artifacts
                for art in result.get("artifacts", []) or []:
                    if "parts" in art:
                        parts.extend(_extract_parts_from_raw(art["parts"]))

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]

    return JSONResponse({"parts": parts})


STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
