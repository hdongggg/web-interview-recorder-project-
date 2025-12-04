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
GOOGLE_API_KEY = "" # <--- THAY KEY CỦA BẠN VÀO ĐÂY
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

# --- CONFIGURATION ---
# IMPORTANT: Replace the placeholder with your actual key or use Railway Variables
GOOGLE_API_KEY = "" 
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

# --- QUESTION DATABASE ---
QUESTIONS_DB = {
    1: "Please briefly introduce yourself.",
    2: "What are your greatest strengths and weaknesses?",
    3: "Why do you want to apply for this position?",
    4: "Describe a challenge you faced at work and how you overcame it.",
    5: "What are your salary expectations?"
}

# --- BACKGROUND TASK: AI GRADING ---
def process_video_background(filename: str):
    print(f"🔄 [Background] Grading: {filename}...")
    file_path = UPLOAD_DIR / filename
    
    # Extract Question Text
    try:
        parts = filename.split("_Question_")
        q_num = int(parts[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "General Interview Question")
    except Exception:
        question_text = "General Interview Question"

    try:
        # 1. Upload Video to Google Cloud
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # Wait for processing
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED": 
            print("❌ Google failed to read video.")
            return

        # 2. COMBINED STT & GRADING CALL
        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        
        prompt = f"""
        Act as a Professional Recruiter.
        The candidate is answering this question: "{question_text}"
        
        Evaluate this answer on a scale of 1-10.
        Return ONLY a JSON object like this:
        {{
            "transcript": "The full transcription text here...",
            "score": 8,
            "comment": "Short feedback (max 20-25 words)"
        }}
        """

        # Get combined response
        grade_res = model.generate_content(
            [video_file, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # 3. CRUCIAL FIX: DELETE FILE FROM CLOUD ONLY AFTER RESPONSE RECEIVED
        genai.delete_file(video_file.name)

        # 4. Robust JSON Parsing
        raw_text = grade_res.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "")
        
        try:
            grade_data = json.loads(raw_text)
        except json.JSONDecodeError:
            print(f"❌ [JSON FAIL] AI returned invalid JSON for {filename}.")
            grade_data = {"score": 0, "comment": "AI grading failed (JSON error)."}
            
        # 5. Save Results
        result_data = {
            "filename": filename,
            "question": question_text,
            "transcript": grade_data.get("transcript", "Transcription unavailable."),
            "score": grade_data.get("score", 0),
            "comment": grade_data.get("comment", "No comment available.")
        }
        
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Done] {filename}: Score {result_data['score']}/10")

    except Exception as e:
        print(f"❌ [FATAL ERROR] An unexpected error occurred while processing {filename}: {e}")

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
        
        # Trigger background grading immediately
        background_tasks.add_task(process_video_background, safe_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

# API KIỂM TRA KẾT QUẢ (Polling for Candidate)
@app.get("/api/results/{cname}")
async def get_results(cname: str):
    if not UPLOAD_DIR.is_dir(): return {"completed": False}
    
    results = []
    for f in UPLOAD_DIR.glob(f"{cname}_Question_*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: pass
    
    results.sort(key=lambda x: x['filename'])
    
    return {
        "completed": len(results) >= 5, 
        "count": len(results),
        "avg_score": round(sum(r['score'] for r in results)/len(results), 1) if results else 0,
        "details": results
    }

# API CHO EXAMINER (List videos and status)
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
                "created": (datetime.utcfromtimestamp(f.stat().st_mtime) + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"),
                "grading_status": grading_status,
                "score": score,
                "comment": comment
            })
    return videos

# API XÓA
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
