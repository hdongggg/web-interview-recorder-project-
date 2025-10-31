# Sequence Flow

1️⃣ FE: Nhập Token & Name  
2️⃣ FE → BE: POST /verify-token  
3️⃣ FE → BE: POST /session/start → server tạo folder  
4️⃣ Lặp từng câu hỏi: record → upload → server lưu Qn.webm  
5️⃣ FE → BE: POST /session/finish → kết thúc phiên

Error handling (Week 4): retry exponential backoff.
