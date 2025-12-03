from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
from datetime import datetime
import os

app = FastAPI(title="Interview Recorder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cấu hình Volume
UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/", response_class=HTMLResponse)
async def home():
    try:
        return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Lỗi: Thiếu file index.html</h1>"

@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    try:
        return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Lỗi: Thiếu file examiner.html</h1>"

# --- API UPLOAD ĐÃ SỬA ĐỔI ---
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    # 1. Lấy tên file từ Frontend (VD: NguyenVanA_Question_1.webm)
    filename = file.filename
    
    # [QUAN TRỌNG] ĐÃ BỎ TIMESTAMP Ở ĐÂY. 
    # File mới sẽ GHI ĐÈ (OVERWRITE) file cũ có cùng tên.
    
    # Chỉ làm sạch tên file để an toàn
    safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    
    dest = UPLOAD_DIR / safe_filename

    try:
        # Ghi file mới (ghi đè lên file cũ nếu tồn tại)
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lưu file: {e}")

    # Trả về đường dẫn. Thêm timestamp vào URL để trình duyệt tải file mới nhất
    return {
        "ok": True, 
        "filename": safe_filename, 
        "url": f"/uploads/{safe_filename}?v={datetime.now().timestamp()}"
    }

# --- CÁC API KHÁC (GET LIST, DELETE) GIỮ NGUYÊN ---
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

@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists(): raise HTTPException(status_code=404, detail="Not Found")
    file_path.unlink()
    return {"ok": True}
