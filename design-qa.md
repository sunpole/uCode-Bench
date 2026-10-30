# uCode 0.3.0 — fidelity evidence

Target: the user's latest approved screenshot and the immutable HTML snapshot in `docs/design/approved-2026-10-30/` (SHA256 recorded in its manifest).

The intermediate native Tk recreation was rejected as the final renderer because native controls differ from the approved design. The default launcher now uses the original HTML renderer with a local Python API. Every one of the 18 original CSS blocks is preserved verbatim, and their presence is checked automatically. The supplied barcode samples and the original typeface/color/spacing rules are reused. Real selected QR previews come from the production ReportLab matrix.

Typography, tokens, spacing, copy and images: source CSS/markup preservation is verified; demonstration copy/data/actions are replaced with actual local state. On shorter viewports only central height and preview scale adapt. A functional browser check at 1280 × 720 found the original fixed-height footer outside the viewport (bottom 857.67 px). Responsive central-height adjustment fixed this: root height 704 px, footer bottom 701 px. Console errors were empty after the real three-page workflow.

No screenshots or formal pixel comparison were made. Repository AGENTS.md explicitly assigns visual acceptance to the user and forbids screenshots/manual walkthrough for acceptance. Functional DOM/API verification is separate from that acceptance. This file does not certify a pixel-perfect match across Windows DPI settings.

Functional checks: create real three-line TXT → selected QR preview → one physical CPU → measured disk preflight → one real three-page PDF, UNVERIFIED as requested → measured timing/CPU/RAM → result actions. Local backend tests additionally cover strict QA, delayed stop authorization, console/config preservation, source cache, background round trip and endpoint origin protection. No large test series were started automatically.

final result: blocked

Blocker is formal visual acceptance by the user, not the engine/API functional checks. The user-owned visual acceptance rule takes precedence over the skill's screenshot workflow. Remaining visual/DPI differences, if reported, should be corrected against the same immutable source without another redesign.
