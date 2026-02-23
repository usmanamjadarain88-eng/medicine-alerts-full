"""
Data bus WebSocket client for desktop. Runs in a background thread; puts data_sync
payloads into a queue so the main thread can apply them (no DB load except when
Central API notifies the data bus on actual change).
"""
import asyncio
import json
import queue
import threading
import time


def run_databus_client(ws_url: str, access_code: str, out_queue: queue.Queue, stop_event: threading.Event):
    """
    Connect to data bus, register with access_code and client_type=desktop,
    and push every data_sync payload into out_queue. Runs until stop_event is set.
    ws_url: e.g. ws://127.0.0.1:5052 or wss://databus.onrender.com
    """
    if not ws_url or not access_code:
        return
    url = (ws_url or "").strip()
    if url.startswith("http://"):
        url = "ws://" + url[7:]
    elif url.startswith("https://"):
        url = "wss://" + url[8:]
    elif not url.startswith("ws"):
        url = "wss://" + url if "://" not in url else url
    url = url.rstrip("/")

    try:
        import websockets
    except ImportError:
        return

    code = (access_code or "").strip()
    if not code:
        return

    while not stop_event.is_set():
        try:
            asyncio.run(_connect_loop(url, code, out_queue, stop_event))
        except Exception:
            pass
        if stop_event.is_set():
            break
        time.sleep(5)


async def _connect_loop(ws_url: str, access_code: str, out_queue: queue.Queue, stop_event: threading.Event):
    import websockets
    async with websockets.connect(ws_url, close_timeout=2, open_timeout=10) as ws:
        await ws.send(json.dumps({"access_code": access_code, "client_type": "desktop"}))
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            try:
                obj = json.loads(msg)
                if obj.get("action") == "data_sync" and "payload" in obj:
                    out_queue.put(obj["payload"])
            except Exception:
                pass
