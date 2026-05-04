# YouTube Transcript Architecture

Tài liệu này mô tả kiến trúc đã được rút gọn của project.

## Mục tiêu

Giữ lại duy nhất một luồng ổn định để lấy transcript YouTube:

- mở YouTube bằng `Playwright`
- dùng `Chrome profile` thật
- bấm `Show transcript`
- scrape transcript segments từ DOM
- ghi output thành file JSON/TXT

Các nhánh sau đã được loại bỏ khỏi project:

- `youtube-transcript-api`
- các fallback transcript API khác
- tool `X`
- batch scripts `EthCC`
- scripts xử lý tài liệu phụ

## Thành phần còn lại

### 1. Main CLI

File:

```text
tools/youtube/youtube_transcript_tool.py
```

Vai trò:

- nhận `YouTube URL` hoặc `video id`
- chuẩn hóa về watch URL
- mở video bằng Playwright
- xử lý consent popup nếu có
- tìm và mở transcript panel
- scrape từng transcript segment
- lưu output vào `outputs/youtube_transcripts/<video_id>/`

## Luồng chạy

```text
Input URL / video id
        |
        v
extract_video_id()
normalize_video_url()
        |
        v
Playwright + persistent Chrome profile
        |
        v
Open YouTube page
        |
        v
Open transcript panel
        |
        v
Scrape transcript segments from DOM
        |
        v
Write:
- metadata.json
- transcript.json
- transcript.txt
```

## Output contract

```text
outputs/youtube_transcripts/<video_id>/
├── metadata.json
├── transcript.json
└── transcript.txt
```

### `metadata.json`

Chứa metadata gọn:

- `video_id`
- `url`
- `title`
- `open_method`
- `segment_count`

### `transcript.json`

Chứa payload đầy đủ:

- metadata scrape
- title
- transcript segments

### `transcript.txt`

Transcript text line-by-line để đọc hoặc xử lý tiếp.

## Thiết kế chính

### Vì sao dùng Playwright thay cho transcript API

- ít phụ thuộc vào các endpoint không ổn định
- tránh luồng bị chặn bởi `rate limit`, `RequestBlocked`, `CAPTCHA`, hoặc API drift
- bám trực tiếp vào UI mà user thật cũng nhìn thấy

### Vì sao dùng persistent Chrome profile

- giúp giữ session thật
- tăng khả năng thấy transcript button trong các layout/case YouTube khác nhau
- tránh phải xử lý login/cookie theo cách riêng

### Vì sao giữ output đơn giản

Project hiện chỉ cần một primitive rõ ràng:

- lấy transcript
- lưu transcript

Các lớp batching, summarization orchestration, và workflow theo conference đã được tách ra khỏi repo này để giảm noise khi review.
