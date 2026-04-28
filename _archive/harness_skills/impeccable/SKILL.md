---
name: impeccable
description: "Create distinctive, production-grade frontend interfaces with high design quality. Generates creative, polished code that avoids generic AI aesthetics. Use when the user asks to build web components, pages, artifacts, posters, or applications, or when any design skill requires project context. Call with 'craft' for shape-then-build, 'teach' for design context setup, or 'extract' to pull reusable components and tokens into the design system."
version: 1.0.0
domain: frontend
mode: prompt
tags: [frontend, ui, design, aesthetics, components, css]
license: "Apache 2.0. Based on Anthropic's frontend-design skill."
source: "https://github.com/pbakaus/impeccable"
---

# Impeccable: Distinctive Frontend Design

This skill guides creation of distinctive, production-grade frontend interfaces that avoid generic "AI slop" aesthetics. Implement real working code with exceptional attention to aesthetic details and creative choices.

## When to Use

Use this skill when:
- Designing new pages (Landing Page, Dashboard, Admin, SaaS)
- Creating or refactoring UI components (buttons, modals, forms, tables, charts)
- Choosing color schemes, typography systems, spacing standards, or layout systems
- Building web components, pages, artifacts, posters, or applications
- The user asks to build anything that will be rendered visually in a browser

DO NOT use this skill for:
- Pure backend logic development
- Only involving API or database design
- Performance optimization unrelated to the interface
- Non-visual scripts or automation tasks

## Context Gathering

Design skills produce generic output without project context. Before doing design work, you MUST confirm design context.

**Required context** (every design skill needs at minimum):
- **Target audience**: Who uses this product and in what context?
- **Use cases**: What jobs are they trying to get done?
- **Brand personality/tone**: How should the interface feel?

**Gathering order:**
1. **Check current instructions (instant)**: If your loaded instructions already contain a **Design Context** section, proceed immediately.
2. **Check .impeccable.md (fast)**: If not in instructions, read `.impeccable.md` from the project root. If it exists and contains the required context, proceed.
3. **Ask the user (REQUIRED)**: If neither source has context, ask the user for the required context above before doing anything else.

## Design Direction

Commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick an extreme: brutally minimal, maximalist chaos, retro-futuristic, organic/natural, luxury/refined, playful/toy-like, editorial/magazine, brutalist/raw, art deco/geometric, soft/pastel, industrial/utilitarian, etc.
- **Constraints**: Technical requirements (framework, performance, accessibility).
- **Differentiation**: What makes this UNFORGETTABLE? What's the one thing someone will remember?

**CRITICAL**: Choose a clear conceptual direction and execute it with precision. Bold maximalism and refined minimalism both work. The key is intentionality, not intensity.

Then implement working code that is:
- Production-grade and functional
- Visually striking and memorable
- Cohesive with a clear aesthetic point-of-view
- Meticulously refined in every detail

## Frontend Aesthetics Guidelines

### Typography

Choose fonts that are beautiful, unique, and interesting. Pair a distinctive display font with a refined body font.

- Use a modular type scale with fluid sizing (`clamp`) for headings on marketing/content pages. Use fixed `rem` scales for app UIs and dashboards.
- Use fewer sizes with more contrast. A 5-step scale with at least a 1.25 ratio between steps creates clearer hierarchy.
- Line-height scales inversely with line length. Cap line length at ~65-75ch.

**Font selection procedure:**
1. Write down 3 concrete words for the brand voice. NOT "modern" or "elegant" — those are dead categories.
2. List the 3 fonts you would normally reach for. They are most likely from the reflex list. **Reject them.** Browse Google Fonts, Pangram Pangram, Future Fonts, ABC Dinamo, Klim Type Foundry instead.
3. The right font for an "elegant" brief is NOT necessarily a serif. The right font for a "technical" brief is NOT necessarily a sans-serif.

**Typography rules:**
- DO use a modular type scale with fluid sizing on headings
- DO vary font weights and sizes to create clear visual hierarchy
- DO NOT use Inter, Roboto, Arial, Open Sans, or system defaults
- DO NOT use monospace typography as lazy shorthand for "technical/developer" vibes

### Color & Theme

Commit to a cohesive palette. Dominant colors with sharp accents outperform timid, evenly-distributed palettes.

- Use OKLCH, not HSL. OKLCH is perceptually uniform: equal steps in lightness look equal.
- Tint your neutrals toward your brand hue. Even a chroma of 0.005-0.01 is perceptible.
- The 60-30-10 rule is about visual weight: 60% neutral / surface, 30% secondary text and borders, 10% accent.
- Theme (light vs dark) should be DERIVED from audience and viewing context, not picked from a default.

**Color rules:**
- DO use modern CSS color functions (oklch, color-mix, light-dark)
- DO NOT use pure black (#000) or pure white (#fff). Always tint.
- DO NOT use the AI color palette: cyan-on-dark, purple-to-blue gradients, neon accents on dark backgrounds.
- DO NOT use gradient text (background-clip: text + gradient).

### Layout & Space

Create visual rhythm through varied spacing, not the same padding everywhere.

- Use a 4pt spacing scale with semantic token names (`--space-sm`, `--space-md`). Scale: 4, 8, 12, 16, 24, 32, 48, 64, 96.
- Use `gap` instead of margins for sibling spacing.
- Vary spacing for hierarchy. A heading with extra space above it reads as more important.
- Container queries for components, viewport queries for page layout.

**Spatial rules:**
- DO create visual rhythm through varied spacing
- DO use asymmetry and unexpected compositions; break the grid intentionally for emphasis
- DO NOT wrap everything in cards. Not everything needs a container.
- DO NOT nest cards inside cards.
- DO NOT use identical card grids (same-sized cards with icon + heading + text, repeated endlessly).

### Visual Details — Absolute Bans

These CSS patterns are NEVER acceptable. They are the most recognizable AI design tells:

**BAN 1: Side-stripe borders on cards/list items/callouts/alerts**
- PATTERN: `border-left:` or `border-right:` with width greater than 1px
- FORBIDDEN: `border-left: 3px solid red`, `border-left: 4px solid var(--color-warning)`, etc.
- REWRITE: use full borders, background tints, leading numbers/icons, or no visual indicator at all.

**BAN 2: Gradient text**
- PATTERN: `background-clip: text` combined with a gradient background
- REWRITE: use a single solid color for text. If you want emphasis, use weight or size.

Additional bans:
- DO NOT use glassmorphism everywhere (blur effects, glass cards, glow borders used decoratively)
- DO NOT use rounded rectangles with generic drop shadows
- DO NOT use modals unless there's truly no better alternative

### Motion

Focus on high-impact moments: one well-orchestrated page load with staggered reveals creates more delight than scattered micro-interactions.

- DO: Use motion to convey state changes: entrances, exits, feedback
- DO: Use exponential easing (ease-out-quart/quint/expo) for natural deceleration
- DO NOT: Animate layout properties (width, height, padding, margin). Use transform and opacity only.
- DO NOT: Use bounce or elastic easing.

## The AI Slop Test

**Critical quality check**: If you showed this interface to someone and said "AI made this," would they believe you immediately? If yes, that's the problem.

A distinctive interface should make someone ask "how was this made?" not "which AI made this?"

## Implementation Principles

Match implementation complexity to the aesthetic vision. Maximalist designs need elaborate code with extensive animations and effects. Minimalist or refined designs need restraint, precision, and careful attention to spacing, typography, and subtle details.

Interpret creatively and make unexpected choices that feel genuinely designed for the context. No design should be the same. Vary between light and dark themes, different fonts, different aesthetics. NEVER converge on common choices across generations.

## Teach Mode

If invoked with the argument "teach" (e.g., `/impeccable teach`), skip all design work and instead set up design context:

1. **Explore the codebase** — README, package.json, existing components, brand assets, CSS variables.
2. **Ask focused questions** — Target audience, brand personality (3 words), reference sites, anti-references, light/dark preference, accessibility requirements.
3. **Write Design Context** — Synthesize findings into a `## Design Context` section in `.impeccable.md` at the project root.

## Craft Mode

If invoked with the argument "craft" (e.g., `/impeccable craft [feature description]`), use a shape-first approach:
1. Propose a visual direction (mood board in words: 3 aesthetic adjectives, a key visual metaphor, a color temperature)
2. Get user sign-off on direction before writing any code
3. Then implement fully

## Extract Mode

If invoked with the argument "extract" (e.g., `/impeccable extract [target]`), pull reusable components and design tokens from the existing codebase into a structured design system file.
