# =============================
# Cloud Browser - Production Grade (WebRTC + Multi User)
# =============================
# Tech Stack:
# Backend: FastAPI + WebRTC (aiortc)
# Browser: Playwright (Chromium)
# Isolation: Per-user browser session
# Streaming: WebRTC (low latency)
# =============================

# ----------- REQUIREMENTS -----------
# pip install fastapi uvicorn playwright aiortc opencv-python numpy
# playwright install

# ----------- BACKEND (server.py) -----------

import asyncio
import json
import uuid

from aiortc.sdp import candidate_from_sdp
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, RTCIceCandidate
import cv2
import numpy as np

app = FastAPI()

sessions = {}

# ----------- VIDEO TRACK -----------
class BrowserVideoTrack(VideoStreamTrack):
    def __init__(self, page):
        super().__init__()
        self.page = page

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # Take screenshot from browser
        img_bytes = await self.page.screenshot()
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

        from av import VideoFrame
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame

# ----------- HTML -----------
HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Cloud Browser - WebRTC</title>
</head>
<body>
    <h2>Cloud Browser (WebRTC)</h2>
    <input id="url" placeholder="Enter URL" />
    <button onclick="openUrl()">Go</button>
    <br><br>
    <video id="video" autoplay playsinline width="900" tabindex="0"></video>

<script>
let pc = new RTCPeerConnection();
let ws = new WebSocket("ws://localhost:8000/ws");

pc.ontrack = (event) => {
    document.getElementById("video").srcObject = event.streams[0];
};

ws.onmessage = async (event) => {
    let msg = JSON.parse(event.data);

    if (msg.type === 'offer') {
        await pc.setRemoteDescription(msg);
        let answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        ws.send(JSON.stringify(pc.localDescription));
    }
};

pc.onicecandidate = (event) => {
    if (event.candidate) {
        ws.send(JSON.stringify({
            type: "candidate",
            candidate: {
                candidate: event.candidate.candidate,
                sdpMid: event.candidate.sdpMid,
                sdpMLineIndex: event.candidate.sdpMLineIndex
            }
        }));
    }
};

function openUrl() {
    let url = document.getElementById("url").value;
    ws.send(JSON.stringify({type: 'navigate', url: url}));
}
const video = document.getElementById("video");

video.addEventListener("click", function(e) {
    video.focus();   // 🔥 VERY IMPORTANT

    let rect = video.getBoundingClientRect();
    let x = e.clientX - rect.left;
    let y = e.clientY - rect.top;

    ws.send(JSON.stringify({type: 'click', x: x, y: y}));
});

let buffer = "";

video.addEventListener('keydown', (e) => {
    e.preventDefault(); // stop browser default behavior

    ws.send(JSON.stringify({
        type: "type",
        key: e.key
    }));
});
</script>
</body>
</html>
"""

@app.get("/")
async def index():
    return HTMLResponse(HTML)

# ----------- SESSION MANAGER -----------
async def create_browser():
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page(viewport={"width": 1280, "height": 720})
    await page.goto("https://example.com")
    return p, browser, page

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    session_id = str(uuid.uuid4())
    p, browser, page = await create_browser()

    pc = RTCPeerConnection()
    video_track = BrowserVideoTrack(page)
    pc.addTrack(video_track)

    sessions[session_id] = {
        "pc": pc,
        "browser": browser,
        "page": page
    }

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    await ws.send_text(json.dumps({
        "type": "offer",
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "answer":
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=msg["sdp"], type=msg["type"])
                )



            elif msg.get("type") == "candidate":

                c = msg["candidate"]

                ice = candidate_from_sdp(c["candidate"])

                ice.sdpMid = c["sdpMid"]

                ice.sdpMLineIndex = c["sdpMLineIndex"]

                await pc.addIceCandidate(ice)

            elif msg.get("type") == "navigate":
                await page.goto(msg["url"])


            elif msg.get("type") == "click":

                x = msg["x"]

                y = msg["y"]

                # frontend video size (adjust if needed)

                video_width = 900

                video_height = 506

                browser_width = 1280

                browser_height = 720

                scaled_x = x * browser_width / video_width

                scaled_y = y * browser_height / video_height

                await page.mouse.click(scaled_x, scaled_y)
            elif msg.get("type") == "text":
                await page.keyboard.type(msg["value"])
            elif msg.get("type") == "type":
                print("Hr")
                key = msg["key"]

                special_keys = [

                    "Shift", "Control", "Alt", "Meta",

                    "Backspace", "Enter", "Tab",

                    "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"

                ]

                if key in special_keys:

                    await page.keyboard.press(key)

                else:

                    await page.keyboard.insert_text(key)

    except Exception as e:
        print("Session closed", e)

    finally:
        await browser.close()
        await pc.close()
        del sessions[session_id]

# ----------- RUN -----------
# uvicorn server:app --reload

# ----------- PRODUCTION NOTES -----------
# 1. Use TURN server (coturn) for NAT traversal
# 2. Run browsers in Docker containers
# 3. Add Redis for session store
# 4. Use HTTPS (required for WebRTC)
# 5. Scale using Kubernetes

# ----------- DOCKER IDEA -----------
# Each session -> 1 container with Chrome
# Use queue system to allocate instances

# ----------- NEXT IMPROVEMENTS -----------
# - Clipboard sync
# - File upload/download
# - DevTools streaming
# - Recording sessions
