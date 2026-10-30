# Approved: stable v0.3.4

User request (2026-10-30): transfer verified uCode 0.3.4 to GitHub main, mark it stable and publish a GitHub Release before resuming backlog development.

Release preconditions:
- All source changes merged via PR #27 (portable packaging) and PR #26 (uCode 0.3.4 to main).
- User reported the Windows desktop launches correctly and uCode 0.3.4 CLI smoke produced a two-page QR/PDF.
- Test evidence of feature SHA `7b1d5fae151b7edbe1f916c093d11813516479cd`:
  - Windows/Linux CI: https://github.com/sunpole/uCode-Bench/actions/runs/41074759503 (SUCCESS)
  - Windows/Linux/macOS packaged CI: https://github.com/sunpole/uCode-Bench/actions/runs/41074759451 (SUCCESS).
- After merging to main, source diff from feature SHA consists only of release documentation/workflow. Runtime files must be checked for equality again by stable publisher.
- Version: `v0.3.4`. Existing tags and releases must remain immutable. Publish only when SHA256 validation of all three build artifacts succeeds.
- Explicitly out of scope: numeric variable-length batch QR. It is archived, deferred without planned version or developer work.

This file is a one-time approval marker consumed by the guarded GitHub Actions stable publisher. It is not a claim that the release has already succeeded. Review Actions run and GitHub Releases before marking the delivery complete.
