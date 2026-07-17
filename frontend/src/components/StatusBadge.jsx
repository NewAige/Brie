import React from 'react'

const LABELS = {
  approved: 'Approved',
  draft: 'Draft',
  'in-review': 'In review',
  deprecated: 'Deprecated',
}

export default function StatusBadge({ status }) {
  const key = LABELS[status] ? status : 'draft'
  return <span className={`badge badge-${key}`}>{LABELS[key]}</span>
}
