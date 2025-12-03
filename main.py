from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import uuid
from datetime import datetime

app = FastAPI(title="Video Recorder Server")

# --- 1. CẤU HÌNH CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. CẤU HÌNH THƯ MỤC LƯU TRỮ (VOLUME) ---
# Đây là đường dẫn Volume trên Railway
UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- 3. MOUNT CÁC THƯ MỤC TĨNH ---
BASE_DIR = Path(__file__).parent

# Mount thư mục static chứa html/css/js
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Mount thư mục uploads để xem lại video qua URL
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# --- 4. CÁC ENDPOINT TRANG WEB ---

@app.get("/", response_class=HTMLResponse)
async def home():
    """Trang chủ (Giao diện quay video)"""
    try:
        return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Lỗi: Không tìm thấy file index.html trong thư mục static.</h1>"

@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    """Trang giám khảo (Giao diện xem và xóa video)"""
    try:
        return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Lỗi: Chưa tạo file examiner.html trong thư mục static.</h1>"


# --- 5. CÁC API XỬ LÝ DỮ LIỆU ---

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """API: Nhận video từ Client và lưu vào Volume"""
    # Validate định dạng file
    if file.content_type not in {"video/webm", "video/mp4", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Định dạng file không được hỗ trợ.")

    # Tạo tên file (Timestamp + UUID) để tránh trùng
    ext = ".webm" if "webm" in file.content_type else ".mp4"
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename

    try:
        # Lưu file vào ổ đĩa Volume
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu file: {e}")

    return {"ok": True, "filename": filename, "url": f"/uploads/{filename}"}


@app.get("/api/videos")
async def get_all_videos():
    """API: Lấy danh sách tất cả video trong Volume"""
    if not UPLOAD_DIR.is_dir():
        return []
    
    videos = []
    # Lấy tất cả file, sắp xếp mới nhất lên đầu
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file():
            videos.append({
                "name": f.name,
                "url": f"/uploads/{f.name}",
                "size": f"{f.stat().st_size / 1024 / 1024:.2f} MB",
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            })
    return videos


@app.delete("/api/video/{filename}")
async def delete_video(filename: str):
    """API: Xóa video khỏi Volume"""
    file_path = UPLOAD_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file: {filename}")

    try:
        file_path.unlink() # Xóa vĩnh viễn
        return {"ok": True, "message": f"Đã xóa file {filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {e}")
