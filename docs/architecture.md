# Architecture

## Components
- **Frontend**: HTML + JS (`getUserMedia`, `MediaRecorder`, `fetch` multipart).  
- **Backend**: Express server với các API `/verify-token`, `/session/start`, `/upload-one`, `/session/finish`.

## Data Flow
User → Browser (FE) → API (BE) → Disk + Meta update → Response OK.

## Storage Layout
`uploads/DD_MM_YYYY_HH_mm_<user>/Q{n}.webm + meta.json`

## Security
Bearer Token qua header `Authorization`.  
Yêu cầu HTTPS (nếu public) để truy cập camera/mic.
