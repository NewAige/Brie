---
title: Meeting Minutes Summarizer
category: internal-ops
tags: [internal, productivity, meetings]
status: approved
level: bank
author: mchen
target_model: internal-chatbot-v1
intended_use: Turn raw meeting notes into structured minutes with actions and owners
review_notes: Compliance reviewed 2026-03; internal use only, no customer data
---

Turn the raw meeting notes below into structured minutes.

Output format:
1. **Summary** — three sentences maximum.
2. **Decisions** — bullet list of decisions actually made (not discussed).
3. **Actions** — table with columns: action, owner, due date. Use "TBC" where
   the notes don't say.
4. **Open questions** — anything raised but not resolved.

Rules:
- Do not invent decisions, owners or dates that are not in the notes.
- Keep names exactly as written in the notes.
- Remind the user at the end: "Check actions and owners before circulating."

Meeting notes:
[PASTE THE RAW NOTES HERE]
