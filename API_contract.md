# API Contract – Web Interview Recorder

---

## 1. POST /api/verify-token
**Purpose:** Kiểm tra token hợp lệ.  
**Request Body:**
```json
{ "token": "ABC123" }


{ "ok": true }



## 2. POST /api/session/start
**Purpose:** Bắt đầu buổi phỏng vấn, tạo thư mục lưu trữ cho người dùng.  
**Request Body:**
```json
{ "token": "ABC123", "userName": "NguyenVanA" }

**Response:**
```json
{ "ok": true, "folder": "30_10_2025_14_25_NguyenVanA" }


## 3. POST /api/upload-one
**Purpose:** Upload video cho từng câu hỏi.  
**Request (multipart/form-data):**
| Field | Type | Description |
|-------|------|-------------|
| token | string | Mã xác thực |
| folder | string | Tên thư mục người dùng |
| questionIndex | number | Số thứ tự câu hỏi |
| video | file (.webm) | Video câu hỏi |

**Response:**
```json
{ "ok": true, "savedAs": "Q1.webm" }

## 4. POST /api/session/finish
**Request Body:**
```json
{ "token": "ABC123", "folder": "30_10_2025_14_25_NguyenVanA", "questionsCount": 3 }

**Response:**
```json
{ "ok": true }
