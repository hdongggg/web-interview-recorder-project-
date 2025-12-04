from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
import json
import subprocess  # Thư viện để gọi lệnh FFmpeg
import re
from datetime import datetime, timedelta, timezone
import google.generativeai as genai

app = FastAPI(title="AI Interviewer - Audio Split")

# --- CẤU HÌNH ---
# Nên đặt API Key trong Variable của Railway để bảo mật, nhưng để cứng vầy test cho nhanh
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" 
genai.configure(api_key=GOOGLE_API_KEY)

VN_TZ = timezone(timedelta(hours=7))

UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Thư mục tạm để chứa file mp3 sau khi tách
AUDIO_DIR = Path("/mnt/audios")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- HÀM TÁCH AUDIO (FFMPEG) ---
def extract_audio(video_path: Path) -> Path:
    """Chuyển đổi Video (.webm) -> Audio (.mp3) để xử lý nhanh hơn"""
    filename = video_path.stem
    audio_path = AUDIO_DIR / f"{filename}.mp3"
    
    # Lệnh chạy FFmpeg: Lấy input -> Bỏ hình (-vn) -> Codec mp3 -> Output
    command = [
        "ffmpeg", "-y", "-i", str(video_path), 
        "-vn", "-acodec", "libmp3lame", "-q:a", "4", 
        str(audio_path)
    ]
    
    try:
        # Gọi lệnh hệ thống
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return audio_path
    except Exception as e:
        print(f"⚠️ FFmpeg Error: {e}. Fallback to video file.")
        return video_path # Nếu lỗi thì trả về video gốc để dùng tạm

# --- PIPELINE XỬ LÝ BACKGROUND ---
def process_interview_pipeline(filename: str, q_num: int):
    print(f"🚀 [Start Pipeline] {filename} (Question {q_num})")
    
    video_path = UPLOAD_DIR / filename
    json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
    question_text = QUESTIONS_DB.get(q_num, "General Question")

    try:
        # BƯỚC 1: TÁCH ÂM THANH
        print("🔊 Extracting Audio...")
        media_path = extract_audio(video_path)
        
        # BƯỚC 2: TRANSCRIBE (Speech-to-Text)
        print(f"☁️ Uploading {media_path.name} to Gemini...")
        # Upload file audio (nhẹ hơn video rất nhiều)
        uploaded_file = genai.upload_file(path=media_path)
        
        # Đợi xử lý
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)
            
        if uploaded_file.state.name == "FAILED":
            raise ValueError("File processing failed on Google Cloud.")

        # Gọi Model để lấy Text (Dùng Flash cho nhanh)
        print("📝 Transcribing...")
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        transcribe_res = model.generate_content(
            [uploaded_file, "Listen carefully and transcribe this audio to English text verbatim. No intro/outro."],
        )
        transcript_text = transcribe_res.text.strip()
        print(f"✅ Transcript extracted: {len(transcript_text)} chars")
        
        # Dọn dẹp file trên Cloud
        genai.delete_file(uploaded_file.name)
        # Xóa file mp3 tạm trên server
        if media_path != video_path:
            media_path.unlink(missing_ok=True)

        # BƯỚC 3: CHẤM ĐIỂM (GRADING) - Dựa trên Text
        print("🧠 Grading...")
        grading_prompt = f"""
        You are a Recruiter.
        Question: "{question_text}"
        Candidate Answer: "{transcript_text}"
        
        Task:
        1. Score (1-10).
        2. Short comment (max 30 words).
        
        Output JSON: {{ "score": 0, "comment": "..." }}
        """
        
        grading_res = model.generate_content(
            grading_prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        data = json.loads(grading_res.text)

        # BƯỚC 4: LƯU KẾT QUẢ
        result_data = {
            "filename": filename,
            "question_index": q_num,
            "question": question_text,
            "transcript": transcript_text,
            "score": data.get("score", 0),
            "comment": data.get("comment", "No comment."),
            "timestamp": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        }
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        print(f"🎉 Done! Score: {result_data['score']}")

    except Exception as e:
        print(f"❌ Pipeline Error: {e}")
        error_data = {
            "filename": filename,
            "question_index": q_num,
            "question": question_text,
            "score": 0,
            "comment": "System Error.",
            "transcript": f"Error log: {str(e)}"
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f)

# --- API ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(): return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/examiner", response_class=HTMLResponse)
async def examiner(): return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_video(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    question_index: int = Form(...) 
):
    timestamp = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
    clean_name = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    safe_filename = f"{timestamp}_Q{question_index}_{clean_name}"
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        # Gọi Pipeline mới
        background_tasks.add_task(process_interview_pipeline, safe_filename, question_index)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

@app.get("/api/results/{cname}")
async def get_results(cname: str):
    if not UPLOAD_DIR.is_dir(): return {"completed": False}
    results = []
    for f in UPLOAD_DIR.glob(f"*{cname}*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: pass
    results.sort(key=lambda x: x.get('question_index', 0))
    avg = 0
    if results: avg = round(sum(r.get('score', 0) for r in results) / len(results), 1)
    return {"completed": len(results) >= 5, "count": len(results), "avg_score": avg, "details": results}

@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        if f.is_file() and f.suffix.lower() in ['.webm', '.mp4']:
            json_path = f.with_suffix('.json')
            status, score, comment, trans = "pending", 0, "Processing...", ""
            if json_path.exists():
                try:
                    with open(json_path, encoding='utf-8') as jf:
                        data = json.load(jf)
                        status = "done"
                        score = data.get('score', 0)
                        comment = data.get('comment', '')
                        trans = data.get('transcript', '')[:50] + "..."
                except: pass
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "created": datetime.fromtimestamp(f.stat().st_mtime, tz=VN_TZ).strftime("%d/%m %H:%M"),
                "grading_status": status, "score": score, "comment": comment, "transcript": trans
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
