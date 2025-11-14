from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import uuid
from datetime import datetime

app = FastAPI(title="Video Recorder Server")

# Cấu hình CORS để Front-end có thể gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cho phép mọi domain, chỉnh lại khi triển khai thật
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"

# Đảm bảo thư mục uploads tồn tại
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 1. Phục vụ file Front-end (static)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# 2. Phục vụ video đã upload (uploads)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# Trang chủ: Trả về index.html từ thư mục static
@app.get("/", response_class=HTMLResponse)
def home():
    try:
        html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    except FileNotFoundError:
        return HTMLResponse("<h1>Lỗi: Không tìm thấy file index.html trong thư mục static.</h1>", status_code=404)


# API upload video (Tên trường: 'file' phải khớp với formData.append('file', ...) ở Front-end)
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    # Kiểm tra loại file cơ bản
    if file.content_type not in {"video/webm", "video/mp4", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Định dạng file không được hỗ trợ.")

    # Tạo tên file an toàn và duy nhất
    ext = ".webm"
    if "mp4" in file.content_type:
        ext = ".mp4"

    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename

    # Lưu file
    try:
        with dest.open("wb") as buffer:
            # Sử dụng shutil.copyfileobj để lưu file stream an toàn
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu file: {e}")

    # Trả về kết quả thành công
    return {"ok": True, "filename": filename, "url": f"/uploads/{filename}"}