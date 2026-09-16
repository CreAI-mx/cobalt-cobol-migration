# Brand Guidelines v1.0 — Cobalt

## Quick Reference
- **Primary Color:** #0071e3 (Cobalt Blue)
- **Secondary Color:** #111111 / #f5f5f7 (monochrome ink/paper)
- **Primary Font:** -apple-system (system UI stack)
- **Voice:** precise, honest, unhyped

## 1. Color Palette

### Primary Colors
| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Cobalt Blue | #0071e3 | rgb(0,113,227) | CTAs, links, active/COBOL-flagged tree items, run status |
| Cobalt Blue (dark) | #2997ff | rgb(41,151,255) | Same role, dark-mode variant |

### Neutral Palette
| Name | Hex | RGB | Usage |
|------|-----|-----|-------|
| Paper (bg light) | #ffffff | rgb(255,255,255) | Page background, light mode |
| Ink (fg light) | #111111 | rgb(17,17,17) | Body text, light mode |
| Void (bg dark) | #000000 | rgb(0,0,0) | Page background, dark mode |
| Chalk (fg dark) | #f5f5f7 | rgb(245,245,247) | Body text, dark mode |
| Dim | #6e6e73 / #8e8e93 | — | Secondary text, captions (light/dark) |
| Border | #e5e5e5 / #2c2c2e | — | Dividers, no boxed cards (light/dark) |

### Semantic (status) Colors
| Name | Hex | Usage |
|------|-----|-------|
| OK | #1d7a3c | Phase passed, COBOL discovery success |
| Blocked | #d70015 | Phase blocked (e.g. `BLOCKED_MISSING_COMPILERS`) |
| Warning | #b25000 | Phase skipped/stubbed |

### Accessibility
- Text/Background Contrast: ≥4.5:1 (WCAG AA), verified for both light and dark tokens above.
- CTA (Cobalt Blue on white/black) meets AA at body size.
- Single accent color only — status is never conveyed by color alone (paired with the text label OK/BLOCKED/SKIPPED).

## 2. Typography

### Font Stack
```css
--font-heading: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: ui-monospace, Menlo, monospace;
```
Deliberate choice: system font stack, not a webfont. Matches the project's "lo más fácil" constraint — zero external font fetch, zero added network dependency, renders instantly.

### Type Scale
| Element | Weight | Size | Line Height |
|---------|--------|------|-------------|
| H1 | 600 | 1.5rem (24px) | 1.25 |
| Section label (H2) | 600, uppercase, +0.06em tracking | 0.75rem (12px) | 1.3 |
| Body | 400 | 0.9–0.95rem (14–15px) | 1.5 |
| Caption/dim | 400 | 0.8–0.85rem (13px) | 1.4 |
| Code/mono | 400 | 0.8rem (13px) | 1.4 |

## 3. Logo Usage

No graphic mark yet — the product identity is the wordmark "Cobalt" set in the header, weight 600, no icon. Do not introduce a symbol/icon logo until the product has a public-facing surface beyond this internal demo; a logo commissioned for a 3-file internal tool is scope creep.

### Wordmark rule
- Always "Cobalt", never stylized as "COBALT" or "cobalt.".
- No color other than Ink/Chalk (never rendered in Cobalt Blue itself — the accent stays reserved for interactive elements, not the name).

## 4. Voice & Tone

### Brand Personality
**Precise**: states exact numbers, file counts, statuses — never "many files" when the count is known.
**Honest**: a blocked or stubbed phase says so explicitly (`BLOCKED_MISSING_COMPILERS`), never a fake pass.
**Unhyped**: no marketing adjectives ("powerful", "seamless", "cutting-edge") anywhere in UI copy or docs.

### Voice Chart
| Trait | We Are | We Are Not |
|-------|--------|------------|
| Precise | "3 COBOL files inventoried" | "Several files found" |
| Honest | "BLOCKED_MISSING_COMPILERS — cobc/dotnet not found" | "Almost there!" |
| Unhyped | "Run pipeline" | "Unleash the power of AI migration!" |

### Tone by Context
| Context | Tone | Example |
|---------|------|---------|
| Status/progress | Flat, factual | "Phase 3 — cobol-dependency-mapping — OK — CALL graph: [DataProgram, OperationsProgram]" |
| Errors | Direct, names the cause | "Only .zip is supported... convert to .zip first." |
| Empty states | Minimal, no filler | Sections stay hidden until there's content — no "Nothing here yet!" placeholder copy |

### Prohibited Terms
- "seamless" (nothing about compiler integration is seamless — say what actually happens)
- "powerful AI" (vague; name the specific capability instead)
- "revolutionize" / "transform your business" (this is a migration tool, not a pitch deck)

## 5. Imagery Guidelines

No photography or illustration — this is a developer tool, not a marketing surface. Icons only:
- Style: outline/stroke, 1.5px stroke weight, 24×24 viewBox
- Source: hand-drawn minimal SVG (folder/file/COBOL-file/upload/run), no icon library dependency added for 4 icons
- Corner radius: consistent with UI radius scale (8–12px for containers, sharp for icon strokes)
