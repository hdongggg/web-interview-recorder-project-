from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
import json
import re
from datetime import datetime, timedelta, timezone
import google.generativeai as genai

app = FastAPI(title="AI Interviewer Pro")

# --- 1. CẤU HÌNH API KEY ---
# (Lưu ý: Đảm bảo Key này còn hạn mức sử dụng)
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" 
genai.configure(api_key=GOOGLE_API_KEY)

# In phiên bản thư viện ra Log để kiểm tra (Xem trong Railway Logs)
print(f"📚 Google GenAI Library Version: {genai.__version__}")

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

# --- 2. HÀM XỬ LÝ BACKGROUND (CƠ CHẾ AUTO-FIX) ---
def process_video_background(filename: str, q_num: int):
    print(f"🚀 [Start AI] Analyzing {filename} (Question {q_num})")
    file_path = UPLOAD_DIR / filename
    question_text = QUESTIONS_DB.get(q_num, "General Interview Question")

    try:
        # A. Upload video
        print("⏳ Uploading to Google...")
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # B. Đợi xử lý
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED":
            raise ValueError("Google Video Processing Failed.")

        # C. CƠ CHẾ THỬ NHIỀU MODEL (Để tránh lỗi 404)
        # Hệ thống sẽ thử lần lượt các tên model này
        backup_models = ["gemini-1.5-flash", "gemini-1.5-flash-001", "gemini-1.5-flash-latest", "gemini-pro"]
        
        response = None
        used_model = ""
        last_error = None

        prompt = f"""
        You are an expert HR Recruiter.
        The candidate is answering Question {q_num}: "{question_text}"
        
        Task:
        1. Transcribe the answer verbatim (English).
        2. Score the answer (1-10).
        3. Give a short comment (max 30 words).
        
        Output strictly in JSON format:
        {{ "transcript": "...", "score": 0, "comment": "..." }}
        """

        for model_name in backup_models:
            try:
                print(f"🔄 Trying model: {model_name}...")
                model = genai.GenerativeModel(model_name=model_name)
                response = model.generate_content(
                    [video_file, prompt],
                    generation_config={"response_mime_type": "application/json"}
                )
                used_model = model_name
                print(f"✅ Success with model: {model_name}")
                break # Nếu thành công thì thoát vòng lặp ngay
            except Exception as e:
                print(f"⚠️ Failed with {model_name}: {e}")
                last_error = e
        
        # Nếu thử hết model mà vẫn không có response
        if not response:
            try: genai.delete_file(video_file.name)
            except: pass
            raise last_error

        # D. Xử lý kết quả
        try: genai.delete_file(video_file.name)
        except: pass

        data = json.loads(response.text)

        result_data = {
            "filename": filename,
            "question_index": q_num,
            "question": question_text,
            "transcript": data.get("transcript", "No transcript."),
            "score": data.get("score", 0),
            "comment": data.get("comment", "No comment."),
            "ai_model_used": used_model, # Ghi lại model nào đã chạy được
            "timestamp": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        }
        
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        print(f"🎉 Grading Complete! Score: {result_data['score']}")

    except Exception as e:
        print(f"❌ [CRITICAL ERROR] {filename}: {e}")
        error_data = {
            "filename": filename,
            "question_index": q_num,
            "question": question_text,
            "score": 0, 
            "comment": "AI Connection Error. Please Check Logs.",
            "transcript": f"Error details: {str(e)}"
        }
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f)

# --- 3. API ROUTES (Giữ nguyên) ---

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
        background_tasks.add_task(process_video_background, safe_filename, question_index)
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
            status, score, comment = "pending", 0, "Waiting..."
            if json_path.exists():
                try:
                    with open(json_path, encoding='utf-8') as jf:
                        data = json.load(jf)
                        status, score, comment = "done", data.get('score', 0), data.get('comment', '')
                except: pass
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "created": datetime.fromtimestamp(f.stat().st_mtime, tz=VN_TZ).strftime("%d/%m %H:%M"),
                "grading_status": status, "score": score, "comment": comment
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
