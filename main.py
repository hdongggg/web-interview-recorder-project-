from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
import json
import subprocess  # Dùng để gọi FFmpeg
from datetime import datetime, timedelta, timezone
import google.generativeai as genai

app = FastAPI(title="AI Interviewer Flash 2.0")

# --- CẤU HÌNH API KEY ---
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" 
genai.configure(api_key=GOOGLE_API_KEY)

# Múi giờ VN
VN_TZ = timezone(timedelta(hours=7))

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

QUESTIONS_DB = {
    1: "Please briefly introduce yourself.",
    2: "What are your greatest strengths and weaknesses?",
    3: "Why do you want to apply for this position?",
    4: "Describe a challenge you faced at work and how you overcame it.",
    5: "What are your salary expectations?"
}

# --- HÀM TÁCH AUDIO TỪ VIDEO (Sử dụng FFmpeg) ---
def extract_audio(video_path: Path) -> Path:
    """Tách audio từ webm/mp4 ra file mp3 để xử lý nhẹ hơn"""
    audio_filename = video_path.stem + ".mp3"
    audio_path = video_path.parent / audio_filename
    
    # Lệnh FFmpeg: -i input -vn (bỏ hình) -acodec libmp3lame (nén mp3) -y (ghi đè)
    command = [
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame", "-q:a", "4",
        "-y", str(audio_path)
    ]
    
    # Chạy lệnh (ẩn log để đỡ rác console)
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return audio_path

# --- HÀM XỬ LÝ BACKGROUND (Video -> Audio -> Gemini) ---
def process_video_background(filename: str, q_num: int):
    print(f"🚀 [Step 1] Start Processing: {filename}")
    video_path = UPLOAD_DIR / filename
    json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
    question_text = QUESTIONS_DB.get(q_num, "General Question")

    audio_path = None
    uploaded_file = None

    try:
        # --- BƯỚC 2: TÁCH AUDIO ---
        print(f"🎵 [Step 2] Extracting Audio...")
        if not video_path.exists():
            raise FileNotFoundError("Video file not found")
            
        audio_path = extract_audio(video_path)
        print(f"✅ Audio extracted: {audio_path.name}")

        # --- BƯỚC 3: UPLOAD AUDIO LÊN GOOGLE ---
        # Audio upload nhanh hơn video gấp nhiều lần
        print(f"☁️ [Step 3] Uploading Audio to Google...")
        uploaded_file = genai.upload_file(path=audio_path, display_name=audio_path.name)
        
        # Đợi xử lý (Audio xử lý cực nhanh, thường < 2s)
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(1)
            uploaded_file = genai.get_file(uploaded_file.name)

        if uploaded_file.state.name == "FAILED":
            raise ValueError("Google failed to process audio file.")

        # --- BƯỚC 4: TRANSCRIBE & CHẤM ĐIỂM (Dùng Gemini 2.0 Flash) ---
        print(f"🧠 [Step 4] Calling Gemini 2.0 Flash...")
        
        # Sử dụng model mới nhất: gemini-2.0-flash-exp (nếu có) hoặc gemini-1.5-flash
        # Hiện tại bản ổn định nhất vẫn là 1.5-flash, nhưng nếu bạn muốn test 2.0 thì dùng tên dưới:
        model_name = "gemini-1.5-flash" # Hoặc "gemini-2.0-flash-exp"
        
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"response_mime_type": "application/json"}
        )

        prompt = f"""
        You are an expert HR Recruiter.
        The candidate is answering Question {q_num}: "{question_text}"
        
        Input: An audio recording of the answer.
        
        Task:
        1. LISTEN to the audio and TRANSCRIPT it verbatim (English).
        2. Based on the TRANSCRIPT, SCORE the answer (1-10).
        3. Provide a short COMMENT (max 30 words).
        
        Output JSON:
        {{
            "transcript": "...",
            "score": 0,
            "comment": "..."
        }}
        """

        response = model.generate_content([uploaded_file, prompt])
        
        # --- BƯỚC 5: LƯU KẾT QUẢ ---
        data = json.loads(response.text)
        
        result_data = {
            "filename": filename,
            "question_index": q_num,
            "question": question_text,
            "transcript": data.get("transcript", "No transcript"),
            "score": data.get("score", 0),
            "comment": data.get("comment", "No comment"),
            "timestamp": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Done] Score: {result_data['score']}")

    except Exception as e:
        print(f"❌ [Error] {e}")
        error_data = {"score": 0, "comment": "Error processing", "transcript": str(e)}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f)
            
    finally:
        # Dọn dẹp: Xóa file audio tạm và file trên cloud
        if audio_path and audio_path.exists():
            os.remove(audio_path)
        if uploaded_file:
            try: genai.delete_file(uploaded_file.name)
            except: pass

# --- API ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(): return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/examiner", response_class=HTMLResponse)
async def examiner(): return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_video(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    question_index: int = Form(...) # Nhận index từ frontend
):
    timestamp = datetime.now(VN_TZ).strftime("%Y%m%d_%H%M%S")
    clean_name = "".join(c for c in file.filename if c.isalnum() or c in "._-")
    safe_filename = f"{timestamp}_Q{question_index}_{clean_name}"
    
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Gửi vào background xử lý
        background_tasks.add_task(process_video_background, safe_filename, question_index)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

@app.get("/api/results/{cname}")
async def get_results(cname: str):
    if not UPLOAD_DIR.is_dir(): return {"completed": False}
    results = []
    # Tìm file JSON kết quả
    for f in UPLOAD_DIR.glob(f"*{cname}*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: pass
    
    results.sort(key=lambda x: x.get('question_index', 0))
    
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
        if f.is_file() and f.suffix.lower() in ['.webm', '.mp4']:
            json_path = f.with_suffix('.json')
            status = "pending"
            score = 0
            comment = "..."
            
            if json_path.exists():
                try:
                    with open(json_path, encoding='utf-8') as jf:
                        data = json.load(jf)
                        status = "done"
                        score = data.get('score', 0)
                        comment = data.get('comment', '')
                except: pass

            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "created": datetime.fromtimestamp(f.stat().st_mtime, tz=VN_TZ).strftime("%d/%m %H:%M"),
                "grading_status": status,
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
