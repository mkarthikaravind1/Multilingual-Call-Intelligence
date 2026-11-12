import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/errors'
import { DashboardPage } from './DashboardPage'

const mocks = vi.hoisted(() => ({
  role: 'SUPERVISOR',
  getCallStats: vi.fn(),
  browser: vi.fn(),
}))
vi.mock('../auth/useAuth', () => ({ useAuth: () => ({ session: { role: mocks.role } }) }))
vi.mock('../features/live-call/services/callRestService', () => ({
  callRestService: { getCallStats: mocks.getCallStats },
}))
vi.mock('../features/live-call/components/CallBrowser', () => ({
  CallBrowser: (props: { finishedCallsOnly: boolean; emptyState: React.ReactNode }) => {
    mocks.browser(props.finishedCallsOnly)
    return <div data-testid="browser">{props.emptyState}</div>
  },
}))

beforeEach(() => {
  mocks.role = 'SUPERVISOR'
  mocks.getCallStats.mockReset().mockResolvedValue({ total: 12, active: 3, completed: 9 })
  mocks.browser.mockReset()
})

describe('DashboardPage', () => {
  it('shows the call counts', async () => {
    render(<DashboardPage />)

    expect(await screen.findByText('12')).toBeInTheDocument()
    expect(screen.getByText('Active calls:').nextSibling).toHaveTextContent('3')
    expect(screen.getByText('Completed calls:').nextSibling).toHaveTextContent('9')
  })

  it('shows a spinner until the counts arrive', () => {
    mocks.getCallStats.mockReturnValue(new Promise(() => {}))
    render(<DashboardPage />)

    expect(screen.getAllByLabelText('Loading')).toHaveLength(3)
  })

  it('shows the error and dashes when the counts cannot be loaded', async () => {
    mocks.getCallStats.mockRejectedValue(new ApiError(500, 'Stats are down'))
    render(<DashboardPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the call counts')
    expect(screen.getByText('Stats are down')).toBeInTheDocument()
    expect(screen.getByText('Total calls:').nextSibling).toHaveTextContent('—')
  })

  it('lets staff see calls in progress and tells them how to start one', () => {
    render(<DashboardPage />)

    expect(mocks.browser).toHaveBeenCalledWith(false)
    expect(screen.getByText(/Start a call from Live Call/)).toBeInTheDocument()
  })

  it('limits an admin to finished calls', () => {
    mocks.role = 'ADMIN'
    render(<DashboardPage />)

    expect(mocks.browser).toHaveBeenCalledWith(true)
    expect(screen.getByText(/once executives take them/)).toBeInTheDocument()
  })
})
