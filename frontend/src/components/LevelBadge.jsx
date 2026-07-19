import React from 'react'

// Governance level of a prompt (PLAN.MD phase A). `compact` is for cards,
// where "Community · maintained by <owner>" would crowd the layout.
export default function LevelBadge({ level, owner, compact = false }) {
  if (level === 'community') {
    const full = owner ? `Community · maintained by ${owner}` : 'Community'
    return (
      <span
        className="badge badge-community"
        title="Owner-maintained shared prompt. The owner publishes edits; Bank Approvers are not required."
      >
        {compact ? 'Community' : full}
      </span>
    )
  }
  return (
    <span
      className="badge badge-bank"
      title="Controlled prompt. Every change requires Bank Approver sign-off."
    >
      Bank approved
    </span>
  )
}
