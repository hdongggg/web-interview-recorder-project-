from fastapi import FastAPI, File, UploadFile, HTTPException, Form, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
import shutil
import os
import json
import re
from datetime import datetime
import pytz # Xử lý múi giờ Asia/Bangkok

# --- GOOGLE CLOUD IMPORTS (Chỉ chạy nếu có Key) ---
try:
    from google.cloud import speech
    from google.cloud import storage
    HAS_GOOGLE_CLOUD = True
except ImportError:
    HAS_GOOGLE_CLOUD = False
    print("⚠️ Chưa cài thư viện Google Cloud. Tính năng STT sẽ bị tắt.")

app = FastAPI(title="Web Interview Recorder")

# --- CẤU HÌNH ---
# Token bí mật để đơn giản hóa xác thực
SECRET_TOKEN = "SUPER_SECRET_PROJECT_TOKEN_123" 
TIMEZONE = pytz.timezone('Asia/Bangkok') # [cite: 60]
UPLOAD_DIR = Path("/mnt/videos") # Đường dẫn Volume trên Railway
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Tên Bucket GCS (Điền tên bucket của bạn vào đây nếu dùng STT)
GCS_BUCKET_NAME = "ten-bucket-cua-ban" 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(_file_).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- MODELS ---
class SessionStart(BaseModel):
    token: str
    userName: str

class SessionFinish(BaseModel):
    token: str
    folder: str
    questionsCount: int

# --- HELPER FUNCTIONS ---
def sanitize_filename(name: str) -> str:
    """Tạo tên an toàn cho thư mục"""
    name = re.sub(r'[^\w\s-]', '', name).strip()
    return re.sub(r'[-\s]+', '_', name)

def get_timestamp():
    return datetime.now(TIMEZONE).isoformat()

# --- GOOGLE CLOUD STT FUNCTION (BONUS) ---
def process_stt_background(filepath: Path, filename: str, folder_path: Path, question_idx: int):
    """Xử lý STT dưới nền để không chặn UI"""
    if not HAS_GOOGLE_CLOUD:
        return

    try:
        # 1. Init Clients
        storage_client = storage.Client()
        speech_client = speech.SpeechClient()
        
        # 2. Upload lên GCS
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(f"temp/{filename}")
        blob.upload_from_filename(filepath)
        gcs_uri = f"gs://{GCS_BUCKET_NAME}/temp/{filename}"

        # 3. Call Speech API (Long Running)
        audio = speech.RecognitionAudio(uri=gcs_uri)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
            sample_rate_hertz=48000, # Tùy chỉnh theo mic
            language_code="vi-VN",
            enable_automatic_punctuation=True,
        )
        
        operation = speech_client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=600)

        # 4. Get Transcript
        transcript = ""
        for result in response.results:
            transcript += result.alternatives[0].transcript + " "

        # 5. Save Transcript
        transcript_file = folder_path / "transcript.txt"
        with transcript_file.open("a", encoding="utf-8") as f:
            f.write(f"\n--- Question {question_idx} ---\n{transcript}\n")

        # 6. Clean up GCS
        blob.delete()
        print(f"✅ STT Success for {filename}")

    except Exception as e:
        print(f"❌ STT Error for {filename}: {e}")

# --- ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Lỗi: Không tìm thấy file index.html</h1>"

@app.post("/api/verify-token")
async def verify_token_endpoint(data: dict):
    if data.get("token") != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")
    return {"ok": True}

@app.post("/api/session/start")
async def session_start(data: SessionStart):
    # Validate Token [cite: 105]
    if data.token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid Token")

    # Tạo tên thư mục: DD_MM_YYYY_HH_mm_ten_user 
    now = datetime.now(TIMEZONE)
    folder_name = f"{now.strftime('%d_%m_%Y_%H_%M')}_{sanitize_filename(data.userName)}"
    session_path = UPLOAD_DIR / folder_name
    
    try:
        session_path.mkdir(parents=True, exist_ok=False)
        # Tạo metadata ban đầu [cite: 108]
        meta = {
            "userName": data.userName,
            "startTime": get_timestamp(),
            "timeZone": "Asia/Bangkok",
            "questions": []
        }
        with (session_path / "meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4)
    except FileExistsError:
        # Nếu trùng tên (do test quá nhanh), thêm giây vào
        folder_name += f"_{now.second}"
        session_path = UPLOAD_DIR / folder_name
        session_path.mkdir(parents=True, exist_ok=True)
    
    return {"ok": True, "folder": folder_name}

@app.post("/api/upload-one")
async def upload_one(
    background_tasks: BackgroundTasks,
    token: str = Form(...),
    folder: str = Form(...),
    questionIndex: int = Form(...),
    video: UploadFile = File(...)
):
    # Validate [cite: 77]
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid Token")
    
    session_path = UPLOAD_DIR / folder
    if not session_path.exists():
        raise HTTPException(status_code=404, detail="Session folder not found")

    # Save Video: Q{index}.webm [cite: 92]
    filename = f"Q{questionIndex}.webm"
    file_path = session_path / filename
    
    try:
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
            
        # Update Metadata
        meta_path = session_path / "meta.json"
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)
            
            meta["questions"].append({
                "index": questionIndex,
                "file": filename,
                "uploadedAt": get_timestamp()
            })
            
            with meta_path.open("w", encoding="utf-8") as f:
                json.dump(meta, f, indent=4)
        
        # Trigger STT Background Task (Bonus) [cite: 61]
        # Chỉ chạy nếu đã config Google Cloud credential trên server
        if HAS_GOOGLE_CLOUD:
            background_tasks.add_task(process_stt_background, file_path, filename, session_path, questionIndex)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "savedAs": filename}

@app.post("/api/session/finish")
async def session_finish(data: SessionFinish):
    if data.token != SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid Token")
        
    session_path = UPLOAD_DIR / data.folder
    meta_path = session_path / "meta.json"
    
    if meta_path.exists():
        with meta_path.open("r+", encoding="utf-8") as f:
            meta = json.load(f)
            meta["endTime"] = get_timestamp()
            meta["totalQuestions"] = data.questionsCount
            meta["status"] = "FINISHED"
            f.seek(0)
            json.dump(meta, f, indent=4)
            
    return {"ok": True}
