import asyncio

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.core.config import settings
from app.realtime.events import CHANNEL

router = APIRouter()


@router.websocket("/ws")
async def events_socket(ws: WebSocket):
    await ws.accept()
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(CHANNEL)

    async def forward():
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                await ws.send_text(msg["data"])

    task = asyncio.create_task(forward())
    try:
        while True:
            await ws.receive_text()      # returns only when client sends or disconnects
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await client.aclose()


LIVE_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>CrisisGrid live events</title>
<style>
 body{font-family:system-ui,sans-serif;margin:24px;background:#0f1419;color:#e6e6e6}
 #status{padding:4px 10px;border-radius:12px;font-size:13px}
 .on{background:#1f6f3f}.off{background:#8a2b2b}
 li{font-family:ui-monospace,monospace;font-size:13px;padding:6px 0;border-bottom:1px solid #222;list-style:none}
 .t{color:#7fd1ff}
</style></head><body>
<h2>CrisisGrid live events <span id="status" class="off">connecting</span></h2>
<ul id="log"></ul>
<script>
const logEl = document.getElementById('log'), st = document.getElementById('status');
function connect(){
  const ws = new WebSocket('ws://' + location.host + '/ws');
  ws.onopen  = () => { st.textContent='connected'; st.className='on'; };
  ws.onclose = () => { st.textContent='reconnecting'; st.className='off'; setTimeout(connect, 1500); };
  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    const lagMs = Date.now() - new Date(e.ts).getTime();
    const li = document.createElement('li');
    li.innerHTML = '<span class="t">' + e.type + '</span> ' + JSON.stringify(e.data) + ' <i>(' + lagMs + ' ms)</i>';
    logEl.prepend(li);
  };
}
connect();
</script></body></html>"""


@router.get("/live", response_class=HTMLResponse, include_in_schema=False)
def live_page():
    return LIVE_PAGE