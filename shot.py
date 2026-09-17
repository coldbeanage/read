#!/usr/bin/env python3
"""shot.py URL OUT.png [--dark] [--width N] [--full] — CDP screenshot via headless Chrome on :9222"""
import asyncio, base64, json, sys, urllib.request
import websockets


async def shot(url, out, dark=False, width=1440, height=1100, full=False):
    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
    page = next(t for t in tabs if t["type"] == "page")
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=80 * 1024 * 1024) as ws:
        i = 0

        async def cmd(method, **params):
            nonlocal i
            i += 1
            await ws.send(json.dumps({"id": i, "method": method, "params": params}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == i:
                    if "error" in msg:
                        raise RuntimeError(msg["error"])
                    return msg.get("result", {})

        await cmd("Page.enable")
        await cmd("Emulation.setDeviceMetricsOverride",
                  width=width, height=height, deviceScaleFactor=2, mobile=False)
        if dark:
            await cmd("Emulation.setEmulatedMedia",
                      features=[{"name": "prefers-color-scheme", "value": "dark"}])
        await cmd("Page.navigate", url=url)
        await asyncio.sleep(2.2)
        if full:
            m = await cmd("Page.getLayoutMetrics")
            h = min(int(m["cssContentSize"]["height"]), 14000)
            await cmd("Emulation.setDeviceMetricsOverride",
                      width=width, height=h, deviceScaleFactor=2, mobile=False)
            await asyncio.sleep(0.8)
        r = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        open(out, "wb").write(base64.b64decode(r["data"]))
    print(out)


if __name__ == "__main__":
    a = sys.argv[1:]
    url, out = a[0], a[1]
    w = int(a[a.index("--width") + 1]) if "--width" in a else 1440
    h = int(a[a.index("--height") + 1]) if "--height" in a else 1100
    asyncio.run(shot(url, out, "--dark" in a, w, h, "--full" in a))
