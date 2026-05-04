---
name: defi-transcript-analyzer
description: >
  Use this skill whenever the user provides a YouTube transcript, subtitle file (.srt, .vtt, .txt),
  or raw text dump from a video/talk/podcast and wants it summarized, analyzed, or distilled into
  structured research notes. Trigger on phrases like "tóm tắt transcript", "phân tích video này",
  "extract info from this talk", "note lại nội dung video", "summarize this presentation",
  or any request involving transcript/subtitle content from conferences (EthCC, Devcon, ETHDenver,
  DeFi-related talks), protocol deep-dives, founder interviews, or technical presentations.
  Also trigger when the user pastes a large block of conversational text that looks like a transcript
  (timestamped lines, speaker labels, subtitle formatting). This skill is designed for DeFi/crypto
  research contexts but works for any technical transcript.
---

# DeFi Transcript Analyzer

## Purpose

Extract maximum research value from video transcripts and subtitles. Conference talks, protocol
presentations, founder interviews, and technical deep-dives contain dense alpha that is hard to
skim. This skill turns raw transcripts into structured, actionable research notes.

## Step 1: Identify the transcript format and clean it

Transcripts arrive in many forms. Detect the format and normalize before analysis.

**Common formats:**
- `.srt` / `.vtt` — timestamped subtitle files. Strip timing metadata and sequence numbers,
  merge lines into coherent paragraphs.
- Raw paste — a wall of text the user copied from YouTube's auto-generated captions.
  These often lack punctuation and have word-boundary errors. Mentally correct as you parse.
- Speaker-labeled transcript — lines prefixed with speaker names (e.g., from podcasts or panels).
  Preserve speaker attribution, it matters for sourcing claims.
- Auto-generated captions — watch for hallucinated words, misheard technical terms
  (e.g., "uniswap" → "you knees wap", "rollup" → "roll up", "EIP" → "EAP").

**Cleaning rules:**
1. Remove all timestamp lines (`00:01:23,456 --> 00:01:25,789` etc.)
2. Remove sequence numbers from `.srt` files
3. Merge fragmented subtitle lines into full sentences
4. Fix obvious auto-caption errors for crypto/DeFi terminology. Common misheards:
   - Protocol names: Aave, Uniswap, Lido, Curve, Compound, MakerDAO, Kyber, etc.
   - Technical terms: rollup, zkSNARK, zkSTARK, EVM, EIP, MEV, PBS, sequencer,
     attestation, finality, slashing, staking, bridging, oracle
   - Standards: ERC-20, ERC-721, ERC-1155, ERC-4337, EIP-4844, EIP-7702
5. If speaker labels exist, standardize them (`Speaker 1:` → use actual names if identifiable)

## Step 2: Produce the structured summary

Generate the output in the following structure. Always write in the **same language the user
used in their request** (Vietnamese if they asked in Vietnamese, English if in English).
If the user doesn't specify, default to Vietnamese with technical terms kept in English.

---

### Output Template

```
# [Tiêu đề / Title]
> Video/Talk: [tên video nếu biết]
> Speaker(s): [tên speaker nếu xác định được]
> Event: [conference/podcast name nếu biết]
> Duration: [ước lượng từ timestamps nếu có]

## TL;DR
[2-3 câu tóm tắt core message của toàn bộ video. Phải trả lời được:
"Video này nói về cái gì và tại sao nó quan trọng?"]

## Key Points
[Liệt kê 5-10 điểm chính, mỗi điểm là 1-3 câu.
Ưu tiên thông tin MỚI, thông tin có thể ACTION được, và insight chưa phổ biến.
KHÔNG liệt kê những thứ ai cũng biết rồi.]

## Technical Details
[Phần này dành cho chi tiết kỹ thuật sâu. Bao gồm:]

### Architecture / Mechanism Design
[Mô tả kiến trúc hệ thống, cơ chế hoạt động, flow chính.
Nếu có thể, vẽ diagram dạng text/ASCII hoặc liệt kê flow theo bước.]

### Parameters & Numbers
[Mọi con số cụ thể được đề cập: TVL, APY, block time, gas cost,
fee tiers, thresholds, limits, etc. Đây là loại info dễ bị mất nhất
khi chỉ xem summary — luôn capture lại.]

### Equations / Formulas
[Nếu video đề cập công thức toán học, invariant, bonding curve,
hay bất kỳ biểu thức nào — ghi lại chính xác.
Dùng LaTeX notation nếu phức tạp.]

## Competitive / Ecosystem Context
[Video này liên quan đến protocol/project nào khác?
So sánh với competitors được đề cập.
Nằm ở đâu trong ecosystem map?]

## Actionable Insights for Research
[Phần quan trọng nhất cho researcher. Trả lời:]
- Có integration opportunity nào cho KyberSwap/Kyber Network không?
- Có mechanism design nào đáng học hỏi/adapt không?
- Có risk/vulnerability nào được tiết lộ không?
- Có alpha chưa được thị trường price in không?
- Cần follow-up research thêm về topic nào?

## Quotes & Key Statements
[Trích dẫn nguyên văn những câu nói quan trọng từ speaker.
Chỉ giữ lại quotes có giá trị — tuyên bố chiến lược, tiết lộ roadmap,
quan điểm controversial, hoặc technical claims quan trọng.
Format: "[quote]" — Speaker Name, [timestamp nếu có]]

## References & Links
[Mọi project, paper, EIP, tool, website được nhắc đến trong video.
Liệt kê để dễ tra cứu sau.]

## Tags
[Gắn tags để dễ tìm kiếm sau. Ví dụ:]
#DeFi #AMM #MEV #ZK #L2 #Bridge #Lending #Privacy #Governance
```

---

## Step 3: Contextual enrichment

After producing the base summary, enhance it with contextual knowledge:

1. **Cross-reference protocols mentioned** — If the speaker mentions a protocol, briefly note
   its current status (active, deprecated, hacked, forked) if you know.
2. **Flag outdated information** — Conference talks age fast. If the transcript is from months
   ago, note which claims may no longer be accurate (e.g., TVL figures, team changes, roadmap
   items that may have shipped or been abandoned).
3. **Connect to broader narratives** — Link the talk's themes to ongoing meta-narratives
   in the space (e.g., modular vs monolithic, intent-based architectures, restaking wars,
   L2 fragmentation, privacy regulation).

## Step 4: Adapt depth to content type

Not all transcripts deserve the same treatment. Adjust your depth:

**Deep technical talk** (protocol mechanism design, math-heavy, architecture deep-dive):
→ Full template. Maximize Technical Details section. Include diagrams if possible.
  Capture every parameter and formula.

**Panel discussion / debate**:
→ Focus on Key Points and Quotes. Attribute claims to specific speakers.
  Highlight disagreements — these are often the most valuable signal.

**Founder/CEO interview**:
→ Focus on TL;DR, Actionable Insights, and Quotes.
  Extract roadmap commitments, strategic pivots, partnership hints.
  These talks contain forward-looking alpha.

**Tutorial / workshop**:
→ Focus on Technical Details as a step-by-step guide.
  The value is in the HOW, not the WHAT.

**Market/macro commentary**:
→ Focus on Parameters & Numbers, and Actionable Insights.
  Capture specific predictions, timeframes, and reasoning.

## Edge cases and common pitfalls

- **Multi-topic talks**: Some conference talks cover 3-4 unrelated topics. Split the summary
  into clearly labeled sections per topic rather than forcing a single narrative.
- **Q&A sections**: The Q&A at the end of talks often contains the best alpha — speakers
  are more candid and specific. Do NOT skip or downplay Q&A content.
- **Humor and sarcasm**: Auto-captions can't convey tone. If a statement seems absurd,
  consider whether it might be sarcastic or a joke before treating it as a factual claim.
- **Multilingual content**: Some talks switch languages mid-stream (e.g., English presentation
  with Vietnamese Q&A). Handle each language segment appropriately.
- **Incomplete transcripts**: If the transcript is clearly cut off or has gaps, note this
  explicitly so the reader knows the summary is partial.

## Output format

- Default: Markdown (`.md` file), suitable for Obsidian, Notion, or any knowledge base.
- If the user requests a different format (PDF, docx), convert accordingly.
- Filename convention: `YYYY-MM-DD_[event]_[speaker]_[short-topic].md`
  - Example: `2026-04-15_EthCC9_vitalik_lean-ethereum.md`

## Quality checklist

Before delivering, verify:
- [ ] TL;DR actually captures the core message (not just a topic label)
- [ ] Numbers and parameters are captured (not rounded away or omitted)
- [ ] Speaker attribution is correct (especially in panels)
- [ ] Technical terms are spelled correctly
- [ ] Actionable Insights section contains at least one concrete follow-up
- [ ] No entire sections of the transcript were silently skipped
- [ ] Tags are relevant and will aid future search