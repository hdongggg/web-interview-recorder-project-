from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import shutil
import uuid
from datetime import datetime

app = FastAPI(title="Video Recorder Server")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dùng Volume Railway
UPLOAD_DIR = Path("/mnt/videos")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Static frontend
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# Serve uploaded videos từ volume
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.get("/", response_class=HTMLResponse)
def home():
    try:
        html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    except FileNotFoundError:
        return HTMLResponse("<h1>Lỗi: Không tìm thấy file index.html trong thư mục static.</h1>", status_code=404)


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    if file.content_type not in {"video/webm", "video/mp4", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Định dạng file không được hỗ trợ.")

    ext = ".webm" if "webm" in file.content_type else ".mp4"
    filename = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / filename

    try:
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi khi lưu file: {e}")

    return {"ok": True, "filename": filename, "url": f"/uploads/{filename}"}
