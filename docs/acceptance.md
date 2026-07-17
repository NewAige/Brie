# v1 acceptance checklist — how to verify each criterion

Run through this on a seeded stack (`python3 scripts/seed.py`, or the
production install).

1. **Sign-in never sees a password.** Sign in as `uma.user`. The password
   form is served by Gitea (`localhost:3000` in dev), not by the app; the app
   only receives the OAuth code on `/auth/callback`. Check the backend logs:
   no password appears anywhere.
2. **Browse & search.** Category chips return only that folder's prompts.
   Searching `deferral` finds "Payment Deferral Explainer" (title), `faq`
   finds by tag, and a phrase that appears only in a body (e.g. `8th-grade`)
   finds "Delinquency Outreach Letter" (body search).
3. **Copy = body only.** Open a prompt, click *Copy prompt*, paste into a
   plain-text editor. The paste must start with the prompt text — no `---`,
   no `title:` line.
4. **User cannot merge.** As `uma.user`, open a suggestion (edit → note →
   *Send for review*). On the Suggestions page there is no *Approve & publish*
   button; calling `POST /api/pulls/{id}/merge` directly returns 403 (Gitea
   refuses — branch protection).
5. **Approver can merge; author preserved.** As `adam.approver`, *Approve &
   publish* the suggestion. The change appears in the library, and the commit
   in Gitea shows `uma.user` as the author.
6. **History.** The prompt's History page lists author, date and a readable
   diff for each change, including the one just merged.
7. **No tokens in the browser.** DevTools → Application: `localStorage` and
   `sessionStorage` are empty; the only cookie is `pl_session`, marked
   HttpOnly (and Secure in production). Nothing token-like is readable from
   the JS console.
8. **Fully functional with egress blocked.** Block the VM's outbound internet
   and the browser's non-internal traffic; everything still works.
9. **Zero non-internal requests.** DevTools → Network over a full session:
   every request goes to the app host or the Gitea host only.
10. **Clean-VM bring-up.** On a fresh VM: clone, seed (or follow
    docs/deployment.md), `docker compose up` — working stack.
