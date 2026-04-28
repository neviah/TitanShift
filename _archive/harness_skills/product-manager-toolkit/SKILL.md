---
name: product-manager-toolkit
description: "Comprehensive product management toolkit covering RICE feature prioritization, customer discovery, PRD development, go-to-market strategy, and agile workflows. Use when the user needs help prioritizing features, writing product specs, synthesizing user research, planning a product roadmap, or documenting acceptance criteria."
version: "1.1.0"
domain: product
mode: prompt
tags: [product, prd, roadmap, prioritization, discovery, spec-writing, agile]
source: "https://github.com/alirezarezvani/claude-skills/tree/main/product-team/product-manager-toolkit"
license: MIT
---

# Product Manager Toolkit

Essential frameworks and workflows for feature prioritization, customer discovery,
PRD development, and product strategy.

## When to Use

- Writing a product requirements document (PRD) or feature spec
- Prioritizing a backlog of features against capacity
- Synthesizing user interviews into actionable insights
- Building a quarterly product roadmap
- Defining success metrics and acceptance criteria for a feature

## Feature Prioritization — RICE Framework

**RICE Score = (Reach × Impact × Confidence) / Effort**

| Factor | How to Estimate |
|--------|----------------|
| Reach | Users affected per quarter (e.g., 5,000) |
| Impact | massive=3, high=2, medium=1, low=0.5, minimal=0.25 |
| Confidence | high=1.0, medium=0.8, low=0.5 |
| Effort | XS=0.5, S=1, M=2, L=4, XL=8 (person-months) |

Prioritization workflow: `Gather → Score → Analyze → Plan → Validate → Execute`

Portfolio balance checks before finalizing:
- [ ] Compare top priorities against strategic goals
- [ ] Run 2× sensitivity analysis on effort estimates
- [ ] Identify dependencies between features
- [ ] Reserve 20% capacity for tech debt and maintenance

## PRD Templates

| Template | Use Case | Timeline |
|----------|----------|----------|
| Standard PRD | Complex, cross-team features | 6–8 weeks |
| One-Page PRD | Simple, single-team features | 2–4 weeks |
| Feature Brief | Exploration / spike | 1 week |
| Agile Epic | Sprint-based delivery | Ongoing |

**Every PRD must include:**
1. Problem statement (lead with the problem, not the solution)
2. Success metrics defined *before* building
3. Explicit out-of-scope items
4. Technical constraints and feasibility notes
5. Acceptance criteria (testable, binary pass/fail)

## Customer Discovery Process

`Plan → Recruit → Interview → Analyze → Synthesize → Validate`

Interview best practices:
- 5–8 interviews per user segment
- Focus on *past behavior*, not future intentions
- Ask "why" five times to reach root cause
- Avoid leading questions ("Wouldn't you love...")
- Patterns require 3+ mentions across independent interviews

After analysis, map insights to the Opportunity Solution Tree before committing to a solution.

## Roadmap Planning

Quarterly capacity allocation:
- 60–70% — top-RICE strategic features
- 20% — tech debt, maintenance, reliability
- 10–20% — discovery spikes and experiments

Before finalizing: validate effort with engineering, check for hidden dependencies,
confirm strategic alignment.

## Common Pitfalls

| Pitfall | Prevention |
|---------|------------|
| Solution-first thinking | Start every PRD with a problem statement |
| Analysis paralysis | Time-box research phases; ship to learn |
| Feature factory (no metrics) | Define success metrics before building |
| Stakeholder surprise | Weekly async updates, monthly demos |
| Metric theater | Tie metrics to user value, not vanity numbers |

## Acceptance Criteria Format (BDD)

```
Given [context/precondition]
When [user action or system event]
Then [expected observable outcome]
```

Example:
```
Given an operator has admin scope
When they POST /api/keys with a valid body
Then the response is 201 with the raw key in the body (visible once only)
And subsequent GET /api/keys/[id] shows the masked prefix, not the raw value
```
