# AI Tools

Repo này đã được rút gọn để chỉ giữ lại một luồng chính:

- lấy transcript YouTube bằng `Playwright`
- thao tác trực tiếp trên giao diện YouTube
- không dùng `youtube-transcript-api`
- không giữ các tool `X`, `EthCC batch`, hay các script chuyển đổi/tổng hợp tài liệu khác

## Cấu trúc hiện tại

```text
.
├── tools/
│   └── youtube/
│       └── youtube_transcript_tool.py
├── tests/
│   └── test_youtube_transcript_tool.py
├── outputs/
│   └── youtube_transcripts/
├── profiles/
│   └── chrome profile/
├── README.md
├── ARCHITECTURE.md
└── requirements.txt
```

## Cài đặt

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## Cách dùng

Tool chính:

```powershell
python -m tools.youtube.youtube_transcript_tool `
  "https://www.youtube.com/watch?v=VIDEO_ID" `
  --profile-dir "profiles\\chrome profile"
```

Hoặc truyền trực tiếp `video id`:

```powershell
python -m tools.youtube.youtube_transcript_tool `
  "VIDEO_ID" `
  --profile-dir "profiles\\chrome profile"
```

### Output

```text
outputs/youtube_transcripts/<video_id>/
├── metadata.json
├── transcript.json
└── transcript.txt
```

- `metadata.json`: metadata gọn của lần scrape
- `transcript.json`: transcript đầy đủ kèm segments
- `transcript.txt`: transcript text dễ đọc/dễ xử lý tiếp

## Ghi chú vận hành

- Tool dùng `launch_persistent_context`, nên profile Chrome cần tồn tại thật.
- Nếu profile đang bị Chrome khác giữ lock, hãy đóng Chrome đang dùng profile đó trước khi chạy.
- Luồng hiện tại cố ý bám vào giao diện YouTube vì đây là nhánh ổn định hơn so với các transcript API hay bị chặn/rate-limit/CAPTCHA.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```
