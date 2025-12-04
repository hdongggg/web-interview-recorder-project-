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

# --- CẤU HÌNH API KEY (QUAN TRỌNG) ---
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" # <--- DÁN KEY CỦA BẠN VÀO ĐÂY
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

# --- HÀM XỬ LÝ BACKGROUND TỐI ƯU (1 BƯỚC) ---
def process_video_background(filename: str):
    start_time = time.time() # Bắt đầu tính giờ
    print(f"🔄 [Background] Grading: {filename}...")
    file_path = UPLOAD_DIR / filename
    
    # 1. Lấy nội dung câu hỏi
    try:
        parts = filename.split("_Question_")
        q_num = int(parts[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "General Interview Question")
    except Exception:
        question_text = "General Interview Question"

    # Bắt lỗi Timeout và các lỗi khác
    try:
        # 1. Upload Video
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # 2. Wait for processing (Kiểm tra Timeout trong vòng lặp)
        while video_file.state.name == "PROCESSING":
            if time.time() - start_time > GRADING_TIMEOUT:
                # Nếu quá 30 giây -> Báo lỗi Timeout
                raise TimeoutError("Processing exceeded time limit.")
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED": 
            print("❌ Google failed to read video.")
            return

        # 3. Grading Call (Kiểm tra lần cuối trước khi gọi AI)
        if time.time() - start_time > GRADING_TIMEOUT:
            raise TimeoutError("Grading API call exceeded time limit.")

        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        
        prompt = f"""
        Act as a Professional Recruiter.
        The candidate is answering: "{question_text}"
        
        Task:
        1. Transcribe it.
        2. Score it (1-10), give comments.
        
        Return JSON structure:
        {{
            "transcript": "...",
            "score": 0,
            "comment": "Short feedback (max 20 words)"
        }}
        """
        
        response = model.generate_content(
            [video_file, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # 4. Dọn dẹp Cloud và Lưu kết quả
        genai.delete_file(video_file.name)

        # Xử lý JSON (đã bao gồm robust parsing)
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text.replace("```json", "").replace("```", "")
        
        grade_data = json.loads(raw_text)

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
            
        print(f"✅ [Done] {filename}: Score {result_data['score']}/10. Time: {time.time() - start_time:.2f}s")

    except TimeoutError:
        print(f"⏰ [TIMEOUT] Processing {filename} exceeded {GRADING_TIMEOUT}s. Saving default score.")
        
        # Cố gắng xóa file trên Google Cloud
        try:
            if 'video_file' in locals():
                genai.delete_file(video_file.name)
        except Exception:
            pass
            
        # Lưu kết quả mặc định (Timeout)
        result_data = {"filename": filename, "transcript": "TIMEOUT: AI processing took too long.", "score": 0, "comment": "System timeout: Processing exceeded 30 seconds."}
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
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
        # Kích hoạt background task
        background_tasks.add_task(process_video_background, safe_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

@app.get("/api/results/{cname}")
async def get_results(cname: str):
    if not UPLOAD_DIR.is_dir(): return {"completed": False}
    
    results = []
    # Quét tất cả file json của user này
    for f in UPLOAD_DIR.glob(f"{cname}_Question_*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: pass
    
    results.sort(key=lambda x: x['filename'])
    
    # Tính điểm trung bình
    avg = 0
    if results:
        avg = round(sum(r['score'] for r in results) / len(results), 1)

    return {
        "completed": len(results) >= 5, # Kiểm tra đủ 5 câu
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
