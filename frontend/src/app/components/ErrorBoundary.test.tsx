import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'

let shouldThrow = true

function Bomb() {
  if (shouldThrow) {
    throw new Error('boom')
  }
  return <p>All good</p>
}

beforeEach(() => {
  shouldThrow = true
  // React and the boundary both log the caught error.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ErrorBoundary', () => {
  it('renders its children when nothing fails', () => {
    shouldThrow = false
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    )

    expect(screen.getByText('All good')).toBeInTheDocument()
  })

  it('shows a fallback naming what failed', () => {
    render(
      <ErrorBoundary what="The live call">
        <Bomb />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('The live call could not be displayed')
  })

  it('recovers on "Try again" once the cause is gone', async () => {
    render(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    )
    shouldThrow = false

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(screen.getByText('All good')).toBeInTheDocument()
  })
})
