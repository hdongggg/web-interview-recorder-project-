from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
from datetime import datetime, timedelta  # <--- Thêm timedelta vào đây
import google.generativeai as genai
#Bổ sung gg cloud API
# from google.cloud import speech_v1p1beta1 as speech
# from google.cloud import storage
# from google.api_core import exceptions as gcp_exceptions


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
    # Lấy danh sách file và sắp xếp mới nhất lên đầu
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file():
            # 1. Lấy thời gian gốc (UTC) từ file
            utc_time = datetime.utcfromtimestamp(f.stat().st_mtime)
            
            # 2. Cộng thêm 7 giờ để thành giờ Việt Nam
            vn_time = utc_time + timedelta(hours=7)
            
            # 3. Định dạng lại cho đẹp (Ngày/Tháng/Năm Giờ:Phút)
            formatted_time = vn_time.strftime("%d/%m/%Y %H:%M:%S")

            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size/1024/1024:.2f} MB",
                "created": formatted_time # Đã là giờ Việt Nam
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

        # 3. Request Transcription
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        response = model.generate_content(
            [video_file, "Listen to the video and provide a full transcript. Output only the text content."],
            request_options={"timeout": 600}
        )
        genai.delete_file(video_file.name)

        # 4. LƯU RA FILE .TXT
        transcript_text = response.text
        # Đổi đuôi file từ .webm/.mp4 sang .txt
        txt_filename = os.path.splitext(filename)[0] + ".txt"
        txt_path = UPLOAD_DIR / txt_filename
        
        # Ghi file vào ổ đĩa
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)

        # 5. Trả về đường dẫn tải file
        return {
            "ok": True, 
            "txt_filename": txt_filename,
            "txt_url": f"/uploads/{txt_filename}" 
        }

    except Exception as e:
        print(f"AI Error: {e}")
        raise HTTPException(status_code=500, detail=f"AI Error: {e}")


