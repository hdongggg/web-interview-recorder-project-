
# Web Interview Recorder (Per-Question Upload)

## 1️⃣ Project Overview
Ứng dụng web cho phép người dùng ghi hình trả lời phỏng vấn từng câu hỏi, sau đó upload ngay video của từng câu lên server.  
Dự án mô phỏng mô hình **client–server** trong mạng máy tính (Computer Networks) thông qua giao tiếp **HTTP/HTTPS**.

---

## 2️⃣ Objectives
- Sử dụng `MediaDevices.getUserMedia()` để truy cập camera và microphone.  
- Ghi hình mỗi câu hỏi riêng lẻ (≤ 5 câu hỏi).  
- Upload video từng câu hỏi (per-question upload) tới server qua API.  
- Lưu trữ dữ liệu server theo thư mục thời gian:  
  `DD_MM_YYYY_HH_mm_ten_user/` (múi giờ: Asia/Bangkok).  
- Quản lý session qua các endpoint:  
  `/verify-token`, `/session/start`, `/upload-one`, `/session/finish`.  

---

## 3️⃣ Architecture Overview
Hệ thống hoạt động theo mô hình **Client–Server**:

[Browser Frontend]
↓ POST /api/verify-token
[Backend Server – Token Validation]

↓ POST /api/session/start
[Server tạo thư mục lưu trữ]

↓ POST /api/upload-one
[Server nhận video từng câu hỏi]

↓ POST /api/session/finish
[Server cập nhật metadata và kết thúc session]

## 4 Workflow
1. Người dùng nhập Token + Name  
2. Server xác minh Token  
3. Bắt đầu session  
4. Ghi video từng câu hỏi → Upload từng câu  
5. Kết thúc session → Server lưu metadata  
