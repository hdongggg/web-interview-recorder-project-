from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import os
import time
from datetime import datetime
import google.generativeai as genai

app = FastAPI(title="Interview System")

# --- CẤU HÌNH GOOGLE GEMINI (MIỄN PHÍ) ---
# Lấy key tại: https://aistudio.google.com/app/apikey
GOOGLE_API_KEY = "AIzaSyD7d78Goxctsn7OohpVKp-ggUT3jgC9tZs" # <--- DÁN KEY CỦA BẠN VÀO ĐÂY
genai.configure(api_key=GOOGLE_API_KEY)

# Cấu hình CORS và Thư mục
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

# --- CÁC TRANG WEB ---
@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Lỗi: Thiếu index.html"

@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    try:
        return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Lỗi: Thiếu examiner.html"

# --- API UPLOAD VIDEO ---
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    filename = file.filename
    # Làm sạch tên file, KHÔNG thêm timestamp để ghi đè file cũ nếu quay lại
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lưu file: {e}")

    return {"ok": True, "filename": safe_filename, "url": f"/uploads/{safe_filename}?v={datetime.now().timestamp()}"}

# --- API LẤY DANH SÁCH ---
@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir(): return []
    videos = []
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files:
        if f.is_file():
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size/1024/1024:.2f} MB",
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            })
    return videos

# --- API XÓA 1 VIDEO ---
@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists(): raise HTTPException(status_code=404, detail="Not Found")
    file_path.unlink()
    return {"ok": True}

# --- API XÓA TẤT CẢ (DỌN DẸP) ---
@app.delete("/api/nuke-all-videos")
async def delete_all_videos():
    if not UPLOAD_DIR.is_dir(): return {"ok": False}
    for f in UPLOAD_DIR.iterdir():
        if f.is_file():
            try: os.remove(f)
            except: pass
    return {"ok": True}

# --- API DỊCH VIDEO SANG TEXT (GEMINI) ---
@app.post("/api/transcribe/{filename}")
async def transcribe_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File không tồn tại")
    
    try:
        # 1. Upload lên Google
        video_file = genai.upload_file(path=file_path, display_name=filename)
        
        # 2. Đợi xử lý (Google cần vài giây để load video)
        while video_file.state.name == "PROCESSING":
            time.sleep(1)
            video_file = genai.get_file(video_file.name)
            
        if video_file.state.name == "FAILED":
            raise ValueError("Google từ chối xử lý video này.")

        # 3. Yêu cầu dịch
        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(
            [video_file, "Nghe video và chép lại toàn bộ lời nói (transcript) bằng tiếng Việt. Chỉ viết nội dung, không thêm lời bình luận."],
            request_options={"timeout": 600}
        )

        # 4. Xóa file trên Google (để không tốn dung lượng cloud của họ)
        genai.delete_file(video_file.name)

        return {"ok": True, "text": response.text}

    except Exception as e:
        print(f"Lỗi AI: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi AI: {e}")
