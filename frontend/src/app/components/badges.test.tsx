import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CallStatusBadge } from './CallStatusBadge'
import { ComplaintStatusBadge, SentimentBadge } from './ToneBadges'

describe('CallStatusBadge', () => {
  it('styles active and completed calls', () => {
    const { rerender } = render(<CallStatusBadge status="ACTIVE" />)
    expect(screen.getByText('Active')).toHaveClass('badge--active')

    rerender(<CallStatusBadge status="completed" />)
    expect(screen.getByText('Completed')).toHaveClass('badge--completed')
  })

  it('shows the phase instead of the status, warning when on hold', () => {
    render(<CallStatusBadge status="active" phase="on_hold" />)

    expect(screen.getByText('On hold')).toHaveClass('badge--warning')
  })

  it('falls back to neutral for unknown statuses', () => {
    render(<CallStatusBadge status="weird" />)

    expect(screen.getByText('Weird')).toHaveClass('badge--neutral')
  })
})

describe('ToneBadges', () => {
  it('colours a complaint status', () => {
    render(<ComplaintStatusBadge status="unresolved" />)

    expect(screen.getByText('Unresolved')).toHaveClass('badge--danger')
  })

  it('colours a sentiment label', () => {
    render(<SentimentBadge label="FRUSTRATED" />)

    expect(screen.getByText('Frustrated')).toHaveClass('badge--danger')
  })
})
