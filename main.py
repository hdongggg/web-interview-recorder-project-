from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
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
GOOGLE_API_KEY = "AIzaSy......" # <--- THAY API KEY CỦA BẠN VÀO ĐÂY
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

# --- DANH SÁCH CÂU HỎI (ĐỂ AI BIẾT MÀ CHẤM) ---
QUESTIONS_DB = {
    1: "Please briefly introduce yourself.",
    2: "What are your greatest strengths and weaknesses?",
    3: "Why do you want to apply for this position?",
    4: "Describe a challenge you faced at work and how you overcame it?",
    5: "What are your salary expectations?"
}

# --- CÁC HÀM XỬ LÝ NGẦM (BACKGROUND) ---

def process_video_background(filename: str):
    """
    Hàm này chạy ngầm: 
    1. Upload lên Google -> STT (Transcribe)
    2. Gửi Text cho AI -> Chấm điểm (Grading)
    3. Lưu kết quả vào file .json
    """
    file_path = UPLOAD_DIR / filename
    
    # Giả sử tên file là: NguyenVanA_Question_1.webm -> Lấy số 1
    try:
        q_num = int(filename.split("_Question_")[1].split(".")[0])
        question_text = QUESTIONS_DB.get(q_num, "Unknown Question")
    except:
        q_num = 0
        question_text = "Unknown Question"

    print(f"🔄 [Background] Đang xử lý: {filename} (Câu {q_num})...")

    try:
        # BƯỚC 1: STT (Speech to Text)
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED":
            print(f"❌ [Background] Lỗi xử lý video: {filename}")
            return

        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        
        # Lấy transcript
        stt_response = model.generate_content(
            [video_file, "Listen to this interview answer. Output ONLY the raw transcript text."],
            request_options={"timeout": 600}
        )
        transcript = stt_response.text.strip()
        genai.delete_file(video_file.name) # Xóa trên cloud
        
        # BƯỚC 2: CHẤM ĐIỂM (GRADING)
        # Prompt chấm điểm
        prompt = f"""
        You are an expert HR Interviewer.
        Question: "{question_text}"
        Candidate's Answer (Transcript): "{transcript}"
        
        Task: Evaluate the answer on a scale of 1-10 based on clarity, relevance, and professionalism.
        Output ONLY a JSON object like this:
        {{
            "score": 8,
            "comment": "Good introduction but a bit too short."
        }}
        """
        
        grading_response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        grading_result = json.loads(grading_response.text)

        # BƯỚC 3: LƯU KẾT QUẢ RA FILE JSON
        # File kết quả sẽ có tên: NguyenVanA_Question_1.json
        result_data = {
            "filename": filename,
            "question": question_text,
            "transcript": transcript,
            "score": grading_result.get("score", 0),
            "comment": grading_result.get("comment", "No comment"),
            "status": "done"
        }
        
        json_filename = os.path.splitext(filename)[0] + ".json"
        with open(UPLOAD_DIR / json_filename, "w", encoding="utf-8") as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Background] Hoàn tất chấm điểm: {filename} -> {grading_result['score']}/10")

    except Exception as e:
        print(f"❌ [Background] Lỗi ngoại lệ: {e}")

# --- API ---

@app.get("/", response_class=HTMLResponse)
async def home():
    try: return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except: return "Error"

@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    try: return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except: return "Error"

# API UPLOAD (CÓ BACKGROUND TASKS)
@app.post("/api/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    filename = file.filename
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # [QUAN TRỌNG] Kích hoạt xử lý ngầm ngay lập tức
        background_tasks.add_task(process_video_background, safe_filename)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save error: {e}")

    return {"ok": True, "filename": safe_filename}

# API KIỂM TRA ĐIỂM (CHO MÀN HÌNH WAITING)
@app.get("/api/results/{candidate_name}")
async def get_results(candidate_name: str):
    """
    Frontend sẽ gọi API này liên tục để xem đã chấm xong chưa.
    Nó tìm các file .json tương ứng với tên ứng viên.
    """
    if not UPLOAD_DIR.is_dir(): return {"completed": False, "results": []}
    
    results = []
    # Tìm các file json bắt đầu bằng tên ứng viên
    for f in UPLOAD_DIR.glob(f"{candidate_name}_Question_*.json"):
        try:
            with open(f, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
                results.append(data)
        except: pass
    
    # Sắp xếp theo câu hỏi (Question_1, Question_2...)
    results.sort(key=lambda x: x['filename'])

    # Kiểm tra xem đủ 5 câu chưa (hoặc số lượng câu hỏi bạn định nghĩa)
    is_completed = len(results) >= 5 
    
    # Tính điểm trung bình
    avg_score = 0
    if results:
        avg_score = sum(r['score'] for r in results) / len(results)

    return {
        "completed": is_completed,
        "count": len(results),
        "avg_score": round(avg_score, 1),
        "details": results
    }

# API CHO GIÁM KHẢO (ĐÃ NÂNG CẤP ĐỂ HIỆN ĐIỂM LUÔN)
@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file() and f.name.endswith(('.webm', '.mp4')):
            # Thử tìm file json kết quả tương ứng
            json_name = os.path.splitext(f.name)[0] + ".json"
            json_path = UPLOAD_DIR / json_name
            
            score_info = "Waiting..."
            transcript_preview = ""
            
            if json_path.exists():
                try:
                    with open(json_path, "r", encoding="utf-8") as jf:
                        data = json.load(jf)
                        score_info = f"Score: {data['score']}/10"
                        transcript_preview = data['transcript'][:100] + "..."
                except: pass

            utc_time = datetime.utcfromtimestamp(f.stat().st_mtime)
            vn_time = utc_time + timedelta(hours=7)
            
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size/1024/1024:.2f} MB",
                "created": vn_time.strftime("%Y-%m-%d %H:%M"),
                "score_info": score_info, # Thêm thông tin điểm
                "transcript_preview": transcript_preview
            })
    return videos

# DELETE API (GIỮ NGUYÊN)
@app.delete("/api/nuke-all-videos")
async def delete_all_videos():
    if not UPLOAD_DIR.is_dir(): return {"ok": False}
    for f in UPLOAD_DIR.iterdir():
        try: 
            if f.is_file(): os.remove(f)
        except: pass
    return {"ok": True}
@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    (UPLOAD_DIR / filename).unlink(missing_ok=True)
    # Xóa luôn file json đi kèm nếu có
    (UPLOAD_DIR / (os.path.splitext(filename)[0] + ".json")).unlink(missing_ok=True)
    return {"ok": True}
