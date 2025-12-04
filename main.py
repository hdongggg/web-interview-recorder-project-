from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
import json
from datetime import datetime, timedelta
import google.generativeai as genai

app = FastAPI(title="AI Interviewer")

# --- CẤU HÌNH API KEY ---
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" # <--- THAY KEY CỦA BẠN VÀO ĐÂY
genai.configure(api_key=GOOGLE_API_KEY)

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

# --- BACKGROUND TASK (CHẤM ĐIỂM) ---
def process_video_background(filename: str):
    print(f"🔄 [Background] Grading: {filename}...")
    file_path = UPLOAD_DIR / filename
    
    try:
        q_num = int(filename.split("_Question_")[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "General Question")
    except:
        question_text = "General Question"

    try:
        # 1. Upload & Wait
        video_file = genai.upload_file(path=file_path, display_name=filename)
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED": return

        # 2. Transcribe
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        stt_res = model.generate_content([video_file, "Output ONLY the raw transcript text."])
        transcript = stt_res.text.strip()
        genai.delete_file(video_file.name)

        # 3. Grading (ĐÃ SỬA LỖI CÚ PHÁP)
        # Dùng f""" cho nhiều dòng và {{ }} cho JSON
        prompt = f"""
        Act as a Professional Recruiter.
        Question: "{question_text}"
        Candidate Answer: "{transcript}"
        
        Evaluate this answer on a scale of 1-10.
        Return ONLY a JSON object like this:
        {{
            "score": 8,
            "comment": "Good answer but needs more details."
        }}
        """
        
        grade_res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        grade_data = json.loads(grade_res.text)

        # 4. Save JSON
        result_data = {
            "filename": filename,
            "transcript": transcript,
            "score": grade_data.get("score", 0),
            "comment": grade_data.get("comment", "")
        }
        
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False)
            
        print(f"✅ [Done] {filename}: Score {result_data['score']}")

    except Exception as e:
        print(f"❌ Error: {e}")

# --- API ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def home(): return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")

@app.get("/examiner", response_class=HTMLResponse)
async def examiner(): return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")

@app.post("/api/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    filename = file.filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        # Chạy ngầm chấm điểm
        background_tasks.add_task(process_video_background, safe_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

# API CHO EXAMINER (Trả về trạng thái chấm điểm)
@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file() and f.name.endswith(('.webm', '.mp4')):
            json_path = f.with_suffix('.json')
            
            # Mặc định là chưa chấm xong
            grading_status = "pending" 
            score = None
            comment = ""
            
            # Nếu có file JSON nghĩa là đã chấm xong
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
