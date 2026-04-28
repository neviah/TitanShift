---
name: last30days
description: "Research what people actually say about any topic in the last 30 days. Pulls posts and engagement from Reddit, X, YouTube, TikTok, Hacker News, Polymarket, GitHub, and the web. Use when the user wants live social intelligence, competitive research, or current-events context before a coding or planning task."
version: "3.0.1"
domain: research
mode: prompt
tags: [research, social, reddit, youtube, trends, news, competitive-intelligence]
source: "https://github.com/mvanhorn/last30days-skill"
license: MIT
required_tools: []
dependencies: [last30days-skill]
---

# last30days — Live Social Research

Research any topic across Reddit, X, YouTube, TikTok, Hacker News, Polymarket,
and the web. Returns what people are actually saying, not what search engines rank.

## When to Use

- User asks "what's the community saying about X?"
- Before a competitive analysis, market sizing, or tech stack decision
- When current-events context would improve a coding or planning response
- User invokes `/last30days <topic>` explicitly

## Setup Requirements

This skill requires the `last30days-skill` Python engine to be available. Install it once:

```bash
pip install last30days-skill
# or clone: git clone https://github.com/mvanhorn/last30days-skill
```

Configure API keys in `harness.config.json` under `skills.last30days`:

| Key | Required | Purpose |
|-----|----------|---------|
| `SCRAPECREATORS_API_KEY` | Yes (10K free) | TikTok, Instagram, Reddit backup |
| `XAI_API_KEY` | Optional | X/Twitter search via xAI |
| `OPENROUTER_API_KEY` | Optional | Web search via OpenRouter |
| `BRAVE_API_KEY` | Optional | Brave Search grounding |

## How to Invoke

```bash
python3 scripts/last30days.py "<topic>" \
  --emit=compact \
  --save-dir=~/Documents/Last30Days \
  --save-suffix=v3
```

With planning (Claude Code-class output):
```bash
python3 scripts/last30days.py "<topic>" \
  --emit=compact \
  --plan '<QUERY_PLAN_JSON>' \
  --x-handle=<resolved_handle> \
  --subreddits=<sub1,sub2,sub3>
```

## Output

The engine outputs a structured research brief with:
- Per-cluster story summaries (Reddit, X, YouTube, TikTok, HN, Polymarket)
- Engagement signals (upvotes, likes, views)
- Prediction market odds (when relevant)
- `✅ All agents reported back!` emoji-tree footer with source stats

Emit the result as a `document.markdown` artifact so it appears in the TitanShift UI.

## Query Types

| Type | Example | Output shape |
|------|---------|--------------|
| GENERAL | `/last30days claude code` | Bold-lead narrative + KEY PATTERNS list |
| RECOMMENDATIONS | `/last30days best python web framework` | Signal-ranked picks |
| COMPARISON | `/last30days pytorch vs jax` | Per-entity sections + comparison table |
| NEWS | `/last30days openai news` | Recent events synthesis |

## Key Research Laws (always follow)

1. **No trailing Sources block** — the engine footer's `🌐 Web:` line is the citation
2. **Run the Python engine first** — do not synthesize from WebSearch alone
3. **No em-dashes** — use ` - ` (hyphen with spaces) in synthesis output
4. **Pass through the engine footer verbatim** — do not recompute stats
5. **Pre-flight required** — resolve X handles, subreddits, and GitHub repos before running
