import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/errors'
import type { EscalationDto } from '../features/escalation/types/dto'
import { EscalationsPage } from './EscalationsPage'

const service = vi.hoisted(() => ({
  listQueue: vi.fn(),
  getStats: vi.fn(),
  acknowledge: vi.fn(),
  resolve: vi.fn(),
}))
vi.mock('../features/escalation/services/escalationRestService', () => ({
  escalationRestService: service,
}))

function escalation(callId: string, extra: object = {}): EscalationDto {
  return {
    call_id: callId,
    level: 'high',
    status: 'open',
    signals: [],
    first_detected_at: 1_700_000_000,
    updated_at: 1_700_000_100,
    acknowledged_by: null,
    acknowledged_at: null,
    resolved_by: null,
    resolved_at: null,
    resolution_note: null,
    ...extra,
  } as unknown as EscalationDto
}

function renderPage() {
  return render(
    <MemoryRouter>
      <EscalationsPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  service.listQueue.mockReset().mockResolvedValue([])
  service.getStats.mockReset().mockResolvedValue({ active: 2, critical: 1, unacknowledged: 2 })
})

describe('EscalationsPage', () => {
  it('shows the counts and the empty message when there are no escalations', async () => {
    renderPage()

    expect(await screen.findByText('No escalations yet')).toBeInTheDocument()
    expect(screen.getByText('Active:').nextSibling).toHaveTextContent('2')
    expect(screen.getByText('Critical:').nextSibling).toHaveTextContent('1')
    expect(service.listQueue).toHaveBeenCalledWith('all', expect.any(Object))
  })

  it('lists the escalated calls', async () => {
    service.listQueue.mockResolvedValue([escalation('CALL-1'), escalation('CALL-2')])
    renderPage()

    expect(await screen.findAllByText('High escalation')).toHaveLength(2)
    expect(screen.queryByText('No escalations yet')).toBeNull()
  })

  it('reloads the queue when another view is chosen', async () => {
    renderPage()
    await screen.findByText('No escalations yet')

    await userEvent.click(screen.getByRole('radio', { name: 'Open' }))

    expect(await screen.findByText('No open escalations')).toBeInTheDocument()
    expect(service.listQueue).toHaveBeenLastCalledWith('open', expect.any(Object))
  })

  it('sends the chosen dates as a half-open range and can clear them', async () => {
    renderPage()
    await screen.findByText('No escalations yet')
    const clear = screen.getByRole('button', { name: 'Clear dates' })
    expect(clear).toBeDisabled()

    const [from] = screen.getAllByLabelText('From')
    await userEvent.type(from, '2026-10-02')

    await waitFor(() => expect(clear).toBeEnabled())
    expect(await screen.findByText('No escalations in these dates')).toBeInTheDocument()
    const filters = service.listQueue.mock.calls.at(-1)![1]
    expect(filters.detectedFrom).toBe(new Date(2026, 9, 2).getTime() / 1000)
    expect(filters.detectedTo).toBeUndefined()

    await userEvent.click(clear)

    expect(await screen.findByText('No escalations yet')).toBeInTheDocument()
  })

  it('shows the error and dashes for the counts when loading fails', async () => {
    service.listQueue.mockRejectedValue(new ApiError(500, 'Server is down'))
    service.getStats.mockRejectedValue(new ApiError(500, 'Server is down'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load escalations')
    expect(screen.getByText('Server is down')).toBeInTheDocument()
    expect(screen.getByText('Active:').nextSibling).toHaveTextContent('—')
  })
})
