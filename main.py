from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
import json
import subprocess
from datetime import datetime, timedelta

# --- THƯ VIỆN GOOGLE ---
import google.generativeai as genai
from google.cloud import speech
from google.oauth2 import service_account

app = FastAPI(title="AI Interviewer - Hybrid Architecture")

# --- 1. CẤU HÌNH API & CREDENTIALS ---

# A. Cấu hình Gemini (Để chấm điểm)
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" 
genai.configure(api_key=GOOGLE_API_KEY)

# B. Cấu hình Google Cloud Speech (Để gỡ băng) - Lấy từ biến môi trường Railway
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
speech_credentials = None

if creds_json:
    try:
        creds_dict = json.loads(creds_json)
        speech_credentials = service_account.Credentials.from_service_account_info(creds_dict)
        print("✅ Google Cloud Credentials loaded successfully.")
    except Exception as e:
        print(f"⚠️ Error loading credentials: {e}")
else:
    print("⚠️ WARNING: Missing GOOGLE_CREDENTIALS_JSON env var for Speech-to-Text!")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DIRECTORIES ---
UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = Path("/mnt/audios") # Thư mục tạm cho audio
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

QUESTIONS_DB = {
    1: "Please briefly introduce yourself.",
    2: "What are your greatest strengths and weaknesses?",
    3: "Why do you want to apply for this position?",
    4: "Describe a challenge you faced at work and how you overcame it.",
    5: "What are your salary expectations?"
}

# --- HÀM TÁCH AUDIO (FFMPEG) ---
def extract_audio(video_path: Path) -> Path:
    """Tách audio từ video file"""
    filename = video_path.stem
    audio_path = AUDIO_DIR / f"{filename}.mp3"
    
    # Lệnh ffmpeg chuyển webm -> mp3 (16k mono để tối ưu cho Speech API)
    command = [
        "ffmpeg", "-y", "-i", str(video_path), 
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", 
        str(audio_path)
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return audio_path
    except Exception as e:
        print(f"⚠️ FFmpeg Error: {e}")
        return None

# --- PIPELINE XỬ LÝ CHÍNH ---
def process_video_background(filename: str):
    print(f"🚀 [Start Pipeline] Processing {filename}")
    
    video_path = UPLOAD_DIR / filename
    json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
    
    # 1. Xác định câu hỏi
    try:
        parts = filename.split("_Question_")
        q_num = int(parts[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "General Question")
    except:
        q_num = 0
        question_text = "General Question"

    try:
        # BƯỚC 1: EXTRACT AUDIO
        audio_path = extract_audio(video_path)
        if not audio_path:
            raise Exception("Failed to extract audio from video.")

        # BƯỚC 2: SPEECH TO TEXT (Google Cloud)
        transcript_text = ""
        if speech_credentials:
            client = speech.SpeechClient(credentials=speech_credentials)
            with open(audio_path, "rb") as f:
                content = f.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.MP3,
                sample_rate_hertz=16000,
                language_code="en-US",
                enable_automatic_punctuation=True
            )
            
            print("☁️ Calling Google Speech API...")
            response = client.recognize(config=config, audio=audio)
            
            for result in response.results:
                transcript_text += result.alternatives[0].transcript + " "
        else:
            transcript_text = "(System Error: Missing Google Cloud Credentials)"

        # Dọn dẹp file audio tạm
        if audio_path.exists():
            audio_path.unlink()

        print(f"📝 Transcript: {transcript_text[:50]}...")

        # BƯỚC 3: GRADING (Gemini)
        model = genai.GenerativeModel("gemini-2.0-flash")
        
        prompt = f"""
        Act as a Recruiter.
        Question: "{question_text}"
        Candidate Answer: "{transcript_text}"
        
        Task:
        1. Score (1-10).
        2. Short comment (max 20 words).
        
        Output JSON: {{ "score": 0, "comment": "..." }}
        """
        
        print("🧠 Grading with Gemini...")
        grading_res = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        data = json.loads(grading_res.text)

        # LƯU KẾT QUẢ
        result_data = {
            "filename": filename,
            "question": question_text,
            "transcript": transcript_text.strip(),
            "score": data.get("score", 0),
            "comment": data.get("comment", "No comment")
        }
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False)
            
        print(f"✅ [Done] Score: {result_data['score']}")

    except Exception as e:
        print(f"❌ [Error] {filename}: {e}")
        # Lưu file lỗi để Frontend hiển thị
        error_data = {
            "filename": filename,
            "question": question_text,
            "transcript": f"Error: {str(e)}",
            "score": 0,
            "comment": "System Error. Please check server logs."
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f)

# --- API ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(): return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/examiner", response_class=HTMLResponse)
async def examiner(): return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    filename = file.filename
    # Làm sạch tên file để tránh lỗi path
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_filename

    # LOGIC GHI ĐÈ: Xóa file JSON cũ nếu tồn tại (để Frontend biết đang chấm lại)
    json_path = UPLOAD_DIR / (os.path.splitext(safe_filename)[0] + ".json")
    if json_path.exists():
        json_path.unlink()

    try:
        # Lưu file video (Tự động ghi đè nếu trùng tên)
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Gọi Pipeline xử lý
        background_tasks.add_task(process_video_background, safe_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

@app.get("/api/results/{cname}")
async def get_results(cname: str):
    if not UPLOAD_DIR.is_dir(): return {"completed": False}
    
    results = []
    # Tìm file JSON theo tên người dùng
    for f in UPLOAD_DIR.glob(f"{cname}_Question_*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: pass
    
    results.sort(key=lambda x: x.get('filename', ''))
    
    avg = 0
    if results:
        avg = round(sum(r.get('score', 0) for r in results) / len(results), 1)

    return {
        "completed": len(results) >= 5, 
        "count": len(results),
        "avg_score": avg,
        "details": results
    }

@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file() and f.name.endswith(('.webm', '.mp4')):
            json_path = f.with_suffix('.json')
            grading_status = "pending"
            score = None
            comment = ""
            
            if json_path.exists():
                try:
                    with open(json_path) as jf:
                        data = json.load(jf)
                        grading_status = "done"
                        score = data.get('score', 0)
                        comment = data.get('comment', '')
                except: pass

            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size/1024/1024:.2f} MB",
                "created": (datetime.utcfromtimestamp(f.stat().st_mtime) + timedelta(hours=7)).strftime("%d/%m %H:%M"),
                "grading_status": grading_status,
                "score": score,
                "comment": comment
            })
    return videos

@app.delete("/api/nuke-all-videos")
async def nuke():
    for f in UPLOAD_DIR.iterdir(): 
        try: os.remove(f) 
        except: pass
    return {"ok": True}

@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    (UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")).unlink(missing_ok=True)
    return {"ok": True}
