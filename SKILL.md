---
name: defi-transcript-analyzer
description: >
  Use this skill whenever the user provides a YouTube transcript, subtitle file
  (.srt, .vtt, .txt), or raw transcript-like text from a video, talk, podcast,
  panel, interview, or technical presentation and wants it summarized, analyzed,
  or distilled into structured research notes. Trigger on requests such as
  "summarize this transcript", "analyze this video", "extract insights from this
  talk", "turn these subtitles into research notes", or any request involving
  conference talks from EthCC, Devcon, ETHDenver, DeFi events, protocol deep
  dives, founder interviews, market discussions, governance calls, or technical
  workshops. Also trigger when the user pastes a large block of timestamped,
  speaker-labeled, subtitle-formatted, or auto-caption text that looks like a
  transcript. The skill is optimized for DeFi and crypto research, but it can be
  used for any technical transcript.
---

# DeFi Transcript Analyzer

## Purpose

Extract high-signal research value from video transcripts and subtitles.
Conference talks, protocol presentations, founder interviews, panels, and
technical deep dives often contain dense information that is difficult to skim.
Use this skill to turn raw transcripts into structured, actionable research
notes.

## Step 1: Identify and Clean the Transcript

Detect the transcript format before analyzing it.

Common formats:

- `.srt` or `.vtt`: Timestamped subtitle files. Strip timing metadata and
  sequence numbers, then merge fragmented lines into coherent paragraphs.
- Raw YouTube paste: A wall of auto-generated caption text. Expect weak
  punctuation, broken sentence boundaries, and misheard technical terms.
- Speaker-labeled transcript: Lines prefixed with speaker names. Preserve
  speaker attribution because it matters for sourcing claims, debates, and
  roadmap commitments.
- Auto-generated captions: Watch for hallucinated or misheard crypto terms, such
  as `Uniswap` rendered as unrelated words, `rollup` split into `roll up`, or
  `EIP` heard as another acronym.

Cleaning rules:

1. Remove timestamp lines such as `00:01:23,456 --> 00:01:25,789`.
2. Remove `.srt` sequence numbers.
3. Merge fragmented subtitle lines into complete sentences where possible.
4. Fix obvious auto-caption errors for crypto and DeFi terminology.
5. Preserve speaker labels when present; replace generic labels with actual names
   if they are clearly identifiable.
6. Do not invent missing details. Mark unclear or corrupted transcript segments
   as uncertain.

Common terms to normalize:

- Protocols: Aave, Uniswap, Lido, Curve, Compound, MakerDAO, Kyber, EigenLayer,
  Chainlink, L2Beat, Flashbots, Safe, Farcaster.
- Technical terms: rollup, zkSNARK, zkSTARK, EVM, EIP, MEV, PBS, sequencer,
  attestation, finality, slashing, staking, bridging, oracle, account
  abstraction, intents, solver, liquidity, AMM, vault, restaking.
- Standards and EIPs: ERC-20, ERC-721, ERC-1155, ERC-4337, EIP-4844, EIP-7702.

## Step 2: Produce the Structured Summary

Write the final output in English unless the user explicitly requests another
language. Keep protocol names and technical terms in their canonical English
forms.

Use this Markdown template by default:

```markdown
# [Title]
> Video/Talk: [Video or talk title, if known]
> Speaker(s): [Speaker names, if identifiable]
> Event: [Conference, podcast, panel, or source, if known]
> Duration: [Estimate from timestamps, if available]

## TL;DR
[2-3 sentences explaining what the transcript is about and why it matters.]

## Key Points
- [5-10 high-signal points. Each point should be 1-3 concise sentences.]
- [Prioritize new information, actionable insight, non-obvious context, and
  concrete claims.]
- [Avoid generic background that any informed crypto reader already knows.]

## Technical Details

### Architecture / Mechanism Design
[Describe system architecture, mechanism design, contract flow, protocol flow,
security model, or operational process. Use a numbered flow or ASCII diagram if
it improves clarity.]

### Parameters & Numbers
[Capture every concrete number mentioned: TVL, APY, block time, gas cost, fee
tiers, thresholds, limits, risk parameters, market size, dates, timelines, or
performance metrics. Do not round away useful detail.]

### Equations / Formulas
[Record mathematical formulas, invariants, bonding curves, scoring functions,
risk formulas, or economic relationships. Use LaTeX notation when helpful.]

## Competitive / Ecosystem Context
[Identify related protocols, competitors, standards, narratives, and ecosystem
positions. Explain what the talk compares itself against, or what the closest
comparison is if the speaker does not make one directly.]

## Actionable Insights for Research
- [Integration opportunity for KyberSwap, Kyber Network, DeFi protocols, wallets,
  infra providers, or researchers.]
- [Mechanism design worth studying or adapting.]
- [Risk, vulnerability, operational weakness, or governance issue surfaced by the
  transcript.]
- [Potential market alpha or roadmap signal that may not be widely priced in.]
- [Concrete follow-up research questions.]

## Quotes & Key Statements
- "[Short quote]" - [Speaker], [timestamp if available]

## References & Links
- [Projects, papers, EIPs, tools, standards, or websites mentioned.]

## Tags
#DeFi #AMM #MEV #ZK #L2 #Bridge #Lending #Privacy #Governance
```

Quote rules:

- Include only high-value quotes: strategy claims, roadmap commitments,
  controversial positions, security disclosures, mechanism explanations, or
  unusually clear framing.
- Keep quotes short. Prefer paraphrase for long passages.
- Include timestamp and speaker when available.

## Step 3: Add Contextual Enrichment

After the base summary, enrich it with careful context:

1. Cross-reference protocols mentioned. If you know a protocol's current status,
   note it briefly: active, deprecated, hacked, forked, merged, migrated, or
   newly launched.
2. Flag potentially outdated claims. Conference talks age quickly; note when TVL,
   roadmap, team, regulatory, or market claims may have changed since recording.
3. Connect the talk to broader narratives such as modular vs monolithic chains,
   intent-based architecture, restaking, L2 fragmentation, privacy regulation,
   tokenized RWAs, stablecoin distribution, or institutional DeFi.
4. Separate transcript evidence from inference. Use phrasing like "The speaker
   claims..." for transcript-backed points and "A likely implication is..." for
   your own synthesis.

## Step 4: Adapt Depth to Content Type

Adjust the summary based on the transcript type.

Deep technical talk:

- Maximize the Technical Details section.
- Capture architecture, formulas, parameters, diagrams, attack surfaces, and
  assumptions.
- Do not collapse mechanism design into a vague product summary.

Panel discussion or debate:

- Attribute claims to specific speakers.
- Highlight disagreements, tradeoffs, and consensus points.
- Treat Q&A and rebuttals as high-value signal.

Founder or CEO interview:

- Focus on TL;DR, roadmap signals, strategic positioning, partnerships, business
  model, and actionable research insights.
- Extract forward-looking commitments and strategic pivots.

Tutorial or workshop:

- Turn the transcript into a practical step-by-step guide.
- Preserve commands, dependencies, contract addresses, code concepts, and setup
  assumptions.

Market or macro commentary:

- Capture specific predictions, timeframes, causal reasoning, market structure,
  positioning, liquidity constraints, and risk assumptions.

## Edge Cases and Pitfalls

- Multi-topic talks: Split the summary into clearly labeled subsections rather
  than forcing one narrative.
- Q&A sections: Do not skip them. They often contain the most candid details.
- Humor and sarcasm: If a statement sounds absurd, consider tone before treating
  it as factual.
- Multilingual transcripts: Summarize the content in English unless the user
  explicitly asks otherwise. Preserve original technical terms and translate only
  when meaning is clear.
- Incomplete transcripts: State that the summary is partial and identify missing
  or cut-off sections if visible.
- Noisy captions: Correct obvious crypto terminology, but do not over-correct
  ambiguous names, numbers, or claims.
- Sponsor or marketing talks: Extract concrete product mechanics, customers,
  metrics, or claims; avoid repeating promotional language.

## Output Format

- Default output: Markdown suitable for Notion, Obsidian, GitHub, or a research
  knowledge base.
- If writing files, use this naming convention:
  `YYYY-MM-DD_event_speaker_short-topic.md`.
- If the user asks for another format such as PDF, DOCX, or a Notion page, keep
  the same analytical structure while adapting the container format.

## Quality Checklist

Before delivering, verify that:

- The TL;DR captures the core message, not just the topic label.
- Key numbers, parameters, dates, formulas, and EIPs are preserved.
- Speaker attribution is correct, especially in panels.
- Technical terms are spelled correctly.
- Actionable Insights includes concrete follow-up research.
- Q&A sections and late-transcript details were not silently skipped.
- Claims from the transcript are separated from your own inference.
- Tags are relevant and useful for future retrieval.
