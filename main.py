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

# --- CẤU HÌNH ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") 

if not GOOGLE_API_KEY:
    print("❌ Lỗi: Chưa cấu hình GOOGLE_API_KEY trong Railway Variables!")
else:
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

# --- HÀM CHẠY NGẦM (QUY TRÌNH 2 BƯỚC: STT -> TEXT -> GRADING) ---
def process_video_background(filename: str):
    print(f"🚀 [Step 1] Start Processing: {filename}")
    file_path = UPLOAD_DIR / filename
    
    # Lấy câu hỏi
    try:
        parts = filename.split("_Question_")
        q_num = int(parts[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "General Question")
    except:
        question_text = "General Question"

    try:
        # --- BƯỚC 1: SPEECH TO TEXT (STT) ---
        
        # 1.1 Upload Video
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # 1.2 Chờ Google xử lý (Bắt buộc)
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED": 
            print("❌ Google failed to read video.")
            return

        # 1.3 Gọi Gemini lấy Transcript (Chỉ lấy chữ)
        model = genai.GenerativeModel(model_name="gemini-2.5-flash")
        
        print(f"🎤 [Step 1] Transcribing...")
        stt_response = model.generate_content(
            [video_file, "Transcribe the audio in this video verbatim. Output ONLY the raw text."],
            request_options={"timeout": 600}
        )
        
        # Lấy kết quả Text
        transcript_text = stt_response.text.strip()
        print(f"📝 [Step 1] Transcript done (Len: {len(transcript_text)})")

        # [QUAN TRỌNG] Xóa file video trên cloud NGAY LẬP TỨC để nhẹ gánh
        genai.delete_file(video_file.name)


        # --- BƯỚC 2: CHẤM ĐIỂM TRÊN VĂN BẢN (TEXT-BASED GRADING) ---
        
        print(f"🧠 [Step 2] Grading text...")
        
        prompt_grading = f"""
        Act as a Professional Recruiter.
        
        
        Question: "{question_text}"
        Candidate's Answer (Text): "{transcript_text}"
        
        Task: Evaluate the answer on a scale of 1-10.
        
        Return ONLY a JSON object:
        {{
            "score": 0,
            "comment": "Short feedback (max 15 words)"
        }}
        """
        
        # Gửi Text đi chấm (Rất nhanh)
        grading_response = model.generate_content(
            prompt_grading,
            generation_config={"response_mime_type": "application/json"},
            request_options={"timeout": 180} # <-- THÊM DÒNG NÀY VÀO
        )

        # Xử lý JSON kết quả
        raw_json = grading_response.text.strip()
        if raw_json.startswith("```json"):
            raw_json = raw_json.replace("```json", "").replace("```", "")
            
        grade_data = json.loads(raw_json)

        # --- LƯU KẾT QUẢ CUỐI CÙNG ---
        result_data = {
            "filename": filename,
            "question": question_text,
            "transcript": transcript_text, # Text lấy từ Bước 1
            "score": grade_data.get("score", 0), # Điểm lấy từ Bước 2
            "comment": grade_data.get("comment", "No comment")
        }
        
        json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False)
            
        print(f"✅ [Finish] {filename} -> Score: {result_data['score']}")

    except Exception as e:
        print(f"❌ [Error] {filename}: {e}")
        # Nếu lỗi, cố gắng tạo file JSON báo lỗi để Frontend không bị treo
        error_data = {
            "filename": filename, 
            "question": question_text,
            "transcript": "Error processing video.", 
            "score": 0, 
            "comment": "AI Processing Failed."
        }
        try:
            json_path = UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(error_data, f)
        except: pass

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
        # Chạy ngầm quy trình 2 bước
        background_tasks.add_task(process_video_background, safe_filename)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True}

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
    
    # Tính trung bình
    avg = 0
    if results:
        avg = round(sum(r['score'] for r in results) / len(results), 1)

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

# --- API: TẠO BÁO CÁO TỔNG HỢP (ĐÃ CĂN CHỈNH LỀ) ---
@app.get("/api/report/{cname}")
async def generate_report(cname: str):
    
    if not UPLOAD_DIR.is_dir(): 
        raise HTTPException(status_code=500, detail="Server storage not available.")
    
    # 1. Tìm dữ liệu JSON
    results = []
    for f in UPLOAD_DIR.glob(f"{cname}_Question_*.json"):
        try:
            with open(f, "r", encoding="utf-8") as jf:
                results.append(json.load(jf))
        except: continue
    
    if len(results) < 5:
        raise HTTPException(status_code=400, detail=f"Chưa đủ {5} câu trả lời để tạo báo cáo.")

    # 2. Sắp xếp và Tính điểm
    results.sort(key=lambda x: x['filename']) 
    avg_score = round(sum(r['score'] for r in results) / len(results), 1)
    
    # 3. Tạo nội dung báo cáo (Text File)
    # Ghi chú: Căn lề sát trái để file xuất ra không bị thụt đầu dòng
    report_content = f"""
=============================================================
              INTERVIEW RESULTS SUMMARY (REPORT CARD)
=============================================================
CANDIDATE NAME   : {cname.replace('_', ' ')}
DATE GENERATED   : {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}
OVERALL AVG SCORE: {avg_score} / 10
=============================================================

DETAILS BY QUESTION:
"""
    
    for i, item in enumerate(results):
        report_content += f"""
-------------------------------------------------------------
QUESTION {i+1}: {item.get('question', 'Unknown Question')}
SCORE   : {item.get('score', 0)}/10
COMMENT : {item.get('comment', 'No comment provided by AI.')}
TRANSCRIPT:
{item.get('transcript', 'Unavailable.')}
"""

    report_content += "\n=============================================================\n"

    # 4. Lưu file Report
    report_filename = f"REPORT_{cname}.txt"
    report_path = UPLOAD_DIR / report_filename
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return {
        "ok": True, 
        "url": f"/uploads/{report_filename}"
    }
