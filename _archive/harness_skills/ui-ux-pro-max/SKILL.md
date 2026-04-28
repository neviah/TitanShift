---
name: ui-ux-pro-max
description: "UI/UX design intelligence for web and mobile. Includes 50+ styles, 161 color palettes, 57 font pairings, 161 product types, 99 UX guidelines, and 25 chart types across 10 stacks (React, Next.js, Vue, Svelte, SwiftUI, React Native, Flutter, Tailwind, shadcn/ui, and HTML/CSS). Use for building, designing, reviewing, or improving any UI/UX."
version: 1.0.0
domain: frontend
mode: prompt
tags: [ui, ux, design, mobile, web, accessibility, responsive]
license: "MIT. See https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"
source: "https://github.com/nextlevelbuilder/ui-ux-pro-max-skill"
---

# UI/UX Pro Max: Design Intelligence

Comprehensive design guide for web and mobile applications. Contains 50+ styles, 161 color palettes, 57 font pairings, 161 product types with reasoning rules, 99 UX guidelines, and 25 chart types across 10 technology stacks.

## When to Use

Use this skill when the task involves **UI structure, visual design decisions, interaction patterns, or user experience quality control**.

**Must Use:**
- Designing new pages (Landing Page, Dashboard, Admin, SaaS, Mobile App)
- Creating or refactoring UI components (buttons, modals, forms, tables, charts)
- Choosing color schemes, typography systems, spacing standards, or layout systems
- Reviewing UI code for user experience, accessibility, or visual consistency
- Implementing navigation structures, animations, or responsive behavior
- Making product-level design decisions (style, information hierarchy, brand expression)

**Recommended:**
- UI looks "not professional enough" but the reason is unclear
- Receiving feedback on usability or experience
- Pre-launch UI quality optimization
- Aligning cross-platform design (Web / iOS / Android)

**Skip:**
- Pure backend logic development
- Only involving API or database design
- Infrastructure or DevOps work
- Non-visual scripts or automation tasks

## Priority Rule Categories

Follow priority 1→10 when deciding which rule category to focus on first:

| Priority | Category | Impact | Key Checks | Anti-Patterns |
|----------|----------|--------|------------|---------------|
| 1 | Accessibility | CRITICAL | Contrast 4.5:1, Alt text, Keyboard nav, Aria-labels | Removing focus rings, Icon-only buttons without labels |
| 2 | Touch & Interaction | CRITICAL | Min size 44×44px, 8px+ spacing, Loading feedback | Reliance on hover only, Instant state changes (0ms) |
| 3 | Performance | HIGH | WebP/AVIF, Lazy loading, Reserve space (CLS < 0.1) | Layout thrashing, Cumulative Layout Shift |
| 4 | Style Selection | HIGH | Match product type, Consistency, SVG icons (no emoji) | Mixing flat & skeuomorphic, Emoji as icons |
| 5 | Layout & Responsive | HIGH | Mobile-first breakpoints, No horizontal scroll | Fixed px container widths, Disable zoom |
| 6 | Typography & Color | MEDIUM | Base 16px, Line-height 1.5, Semantic color tokens | Text < 12px body, Gray-on-gray, Raw hex in components |
| 7 | Animation | MEDIUM | Duration 150–300ms, Motion conveys meaning | Decorative-only animation, Animating width/height |
| 8 | Forms & Feedback | MEDIUM | Visible labels, Error near field, Progressive disclosure | Placeholder-only label, Errors only at top |
| 9 | Navigation Patterns | HIGH | Predictable back, Bottom nav ≤5, Deep linking | Overloaded nav, Broken back behavior |
| 10 | Charts & Data | LOW | Legends, Tooltips, Accessible colors | Relying on color alone to convey meaning |

## Quick Reference Checklist

### 1. Accessibility (CRITICAL)
- `color-contrast` — Minimum 4.5:1 ratio for normal text (large text 3:1)
- `focus-states` — Visible focus rings on interactive elements (2–4px)
- `alt-text` — Descriptive alt text for meaningful images
- `aria-labels` — aria-label for icon-only buttons
- `keyboard-nav` — Tab order matches visual order; full keyboard support
- `form-labels` — Use label with for attribute
- `skip-links` — Skip to main content for keyboard users
- `heading-hierarchy` — Sequential h1→h6, no level skip
- `color-not-only` — Don't convey info by color alone (add icon/text)
- `reduced-motion` — Respect prefers-reduced-motion

### 2. Touch & Interaction (CRITICAL)
- `touch-target-size` — Min 44×44pt (Apple) / 48×48dp (Material)
- `touch-spacing` — Minimum 8px gap between touch targets
- `hover-vs-tap` — Use click/tap for primary interactions; don't rely on hover alone
- `loading-buttons` — Disable button during async operations; show spinner
- `cursor-pointer` — Add cursor-pointer to clickable elements (Web)
- `tap-delay` — Use touch-action: manipulation to reduce 300ms delay

### 3. Performance (HIGH)
- `image-optimization` — Use WebP/AVIF, responsive images (srcset/sizes), lazy load
- `image-dimension` — Declare width/height or use aspect-ratio to prevent CLS
- `font-loading` — Use font-display: swap/optional to avoid FOIT
- `bundle-splitting` — Split code by route/feature to reduce initial TTI
- `virtualize-lists` — Virtualize lists with 50+ items

### 5. Layout & Responsive (HIGH)
- `viewport-meta` — width=device-width initial-scale=1 (never disable zoom)
- `mobile-first` — Design mobile-first, then scale up
- `breakpoint-consistency` — Use systematic breakpoints (375 / 768 / 1024 / 1440)
- `readable-font-size` — Minimum 16px body text on mobile (avoids iOS auto-zoom)
- `horizontal-scroll` — No horizontal scroll on mobile

### 6. Typography & Color (MEDIUM)
- `line-height` — Use 1.5-1.75 for body text
- `line-length` — Limit to 65-75 characters per line
- `font-pairing` — Match heading/body font personalities
- `color-semantic` — Define semantic color tokens (primary, secondary, error, surface)
- `color-dark-mode` — Dark mode uses desaturated / lighter tonal variants, not inverted

### 7. Animation (MEDIUM)
- `duration-timing` — Use 150–300ms for micro-interactions; complex transitions ≤400ms
- `transform-performance` — Use transform/opacity only; avoid animating width/height/top/left
- `easing` — Use ease-out for entering, ease-in for exiting
- `motion-meaning` — Every animation must express cause-effect, not just be decorative
- `exit-faster-than-enter` — Exit animations ~60–70% of enter duration

### 8. Forms & Feedback (MEDIUM)
- `input-labels` — Visible label per input (not placeholder-only)
- `error-placement` — Show error below the related field
- `inline-validation` — Validate on blur (not keystroke)
- `progressive-disclosure` — Reveal complex options progressively
- `undo-support` — Allow undo for destructive or bulk actions

### 9. Navigation Patterns (HIGH)
- `bottom-nav-limit` — Bottom navigation max 5 items; use labels with icons
- `back-behavior` — Back navigation must be predictable and consistent
- `deep-linking` — All key screens must be reachable via deep link / URL
- `modal-escape` — Modals must offer a clear close/dismiss affordance
- `adaptive-navigation` — Large screens (≥1024px) prefer sidebar; small screens use bottom/top nav

### 10. Charts & Data (LOW)
- `chart-type` — Match chart type to data type (trend → line, comparison → bar, proportion → pie/donut)
- `color-guidance` — Use accessible color palettes; avoid red/green only pairs
- `legend-visible` — Always show legend near the chart
- `tooltip-on-interact` — Provide tooltips/data labels on hover (Web) or tap (mobile)
- `no-pie-overuse` — Avoid pie/donut for >5 categories; switch to bar chart

## How to Use This Skill

| Scenario | Start From |
|----------|------------|
| New project / page | Analyze requirements → choose style/colors/typography |
| New component | Domain search: style, ux |
| Choose style / color / font | Generate design system recommendation |
| Review existing UI | Quick Reference checklist above |
| Fix a UI bug | Quick Reference → relevant section |
| Improve / optimize | Domain search: ux |
| Add charts / data viz | Charts & Data section |

## Design System Workflow

When starting a new project:

1. **Analyze the product type** — Is it SaaS, healthcare, e-commerce, portfolio, etc.? The industry determines appropriate styles and color palettes.
2. **Commit to a style** — Choose ONE style direction (glassmorphism, minimalism, brutalism, neumorphism, etc.) and apply consistently.
3. **Select a palette** — Industry-appropriate colors, not generic. Use semantic tokens.
4. **Pair typography** — Match font personality to brand voice. Avoid overused defaults.
5. **Document the design system** — Write design decisions to `design-system/MASTER.md` for consistency across sessions.

## Pre-Delivery Checklist

Before delivering UI code:

**Visual Quality:**
- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons come from a consistent icon family and style
- [ ] Pressed-state visuals do not shift layout bounds

**Interaction:**
- [ ] All tappable elements provide clear pressed feedback
- [ ] Touch targets meet minimum size (≥44×44pt iOS, ≥48×48dp Android)
- [ ] Micro-interaction timing stays in the 150-300ms range

**Accessibility:**
- [ ] All meaningful images/icons have accessibility labels
- [ ] Form fields have labels, hints, and clear error messages
- [ ] Color is not the only indicator
- [ ] Reduced motion and dynamic text size are supported

**Layout:**
- [ ] Safe areas are respected for headers, tab bars, and bottom CTA bars
- [ ] Verified on small phone (375px), large phone, tablet
- [ ] 4/8pt spacing rhythm maintained throughout
- [ ] Long-form text measure remains readable on larger devices
