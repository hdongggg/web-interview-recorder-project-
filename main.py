from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
from datetime import datetime
import google.generativeai as genai
#Bổ sung gg cloud API
from google.cloud import speech_v1p1beta1 as speech
from google.cloud import storage
from google.api_core import exceptions as gcp_exceptions


app = FastAPI(title="Interview System")

# --- GEMINI CONFIGURATION ---
# Get API Key: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" # <--- PASTE YOUR KEY HERE
genai.configure(api_key=GOOGLE_API_KEY)

# CORS & Directories
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Error: index.html missing."

@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    try:
        return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Error: examiner.html missing."

# --- API: UPLOAD VIDEO ---
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    filename = file.filename
    # Clean filename, remove timestamp logic to allow overwrites (Re-record)
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"File save error: {e}")

    return {"ok": True, "filename": safe_filename, "url": f"/uploads/{safe_filename}?v={datetime.now().timestamp()}"}

# --- API: GET LIST ---
@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        if f.is_file():
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size/1024/1024:.2f} MB",
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            })
    return videos

# --- API: DELETE ONE ---
@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists(): raise HTTPException(status_code=404, detail="File not found")
    file_path.unlink()
    return {"ok": True}

# --- API: DELETE ALL ---
@app.delete("/api/nuke-all-videos")
async def delete_all_videos():
    if not UPLOAD_DIR.is_dir(): return {"ok": False}
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            try: os.remove(f)
            except: pass
    return {"ok": True}

# --- API: TRANSCRIBE (GEMINI) ---
@app.post("/api/transcribe/{filename}")
async def transcribe_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        # 1. Upload to Google
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # 2. Wait for processing
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED":
            raise ValueError("Google failed to process video.")

        # 3. Request Transcription (English Prompt)
        model = genai.GenerativeModel(model_name="gemini-1.5-flash-001")
        response = model.generate_content(
            [video_file, "Listen to the video and provide a full transcript of the speech. Output only the text content, no introductory phrases."],
            request_options={"timeout": 600}
        )

        # 4. Cleanup
        genai.delete_file(video_file.name)

        return {"ok": True, "text": response.text}

    except Exception as e:
        print(f"AI Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI Error: {e}")


