# API Contract (Draft)

## POST /api/verify-token
Req: `{ "token": "string" }`  
Res: `{ "ok": true, "user": "duyanh" }`  
Error: 401

## POST /api/session/start
Req: `{ "user":"duyanh" }`  
Res: `{ "ok": true, "sessionId": "DD_MM_YYYY_HH_mm_duyanh" }`  
Error: 401, 500

## POST /api/upload-one
Form-Data: `video` (file/webm), fields: `sessionId`, `questionNo`  
Res: `{ "ok": true, "savedAs":"Q1.webm", "size":123456 }`  
Error: 413, 500

## POST /api/session/finish
Req: `{ "sessionId":"..." }`  
Res: `{ "ok": true }`
