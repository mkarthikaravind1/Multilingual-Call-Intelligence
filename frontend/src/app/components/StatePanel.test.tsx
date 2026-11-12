import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { StatePanel } from './StatePanel'

describe('StatePanel', () => {
  it('announces errors as alerts', () => {
    render(<StatePanel variant="error" title="Broke" description="Try later" />)

    expect(screen.getByRole('alert')).toHaveTextContent('Broke')
    expect(screen.getByText('Try later')).toBeInTheDocument()
  })

  it('announces loading as a status', () => {
    render(<StatePanel variant="loading" title="Loading calls" />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading calls')
  })

  it('is a plain panel when empty, with an optional action', () => {
    render(<StatePanel title="No calls" action={<button type="button">Refresh</button>} compact />)

    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
    expect(document.querySelector('.state-panel--compact')).not.toBeNull()
  })
})
