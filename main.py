from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from datetime import datetime

app = FastAPI()

# 1. Cấu hình đường dẫn Volume (Nơi chứa video thực tế)
UPLOAD_DIR = Path("/mnt/videos") 
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 2. Mount thư mục static (chứa file html/css/js giao diện)
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# 3. Mount thư mục uploads để xem được video
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- API LẤY DANH SÁCH VIDEO CHO GIÁM KHẢO ---
@app.get("/api/videos")
async def get_all_videos():
    if not UPLOAD_DIR.is_dir():
        return []
    
    videos = []
    # Lấy tất cả file trong volume, sắp xếp theo thời gian mới nhất
    files = sorted(UPLOAD_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    
    for f in files:
        if f.is_file():
            # Tạo thông tin trả về
            videos.append({
                "name": f.name,                  # Tên file (VD: NguyenVanA_Q1.webm)
                "url": f"/uploads/{f.name}",     # Link để xem
                "size": f"{f.stat().st_size / 1024 / 1024:.2f} MB", # Kích thước
                "created": datetime.fromtimestamp(f.stat().st_mtime).strftime("%d/%m/%Y %H:%M")
            })
    return videos

# --- TRANG GIAO DIỆN GIÁM KHẢO ---
@app.get("/examiner", response_class=HTMLResponse)
async def examiner_page():
    # Đọc file html dành riêng cho giám khảo
    try:
        return (BASE_DIR / "static" / "examiner.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>Chưa tạo file examiner.html trong thư mục static</h1>"
