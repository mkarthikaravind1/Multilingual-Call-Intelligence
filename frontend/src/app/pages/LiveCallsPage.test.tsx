import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/errors'
import type { LiveCallDto, LiveCallsDto } from '../features/live-call/types/dto'
import { LiveCallsPage } from './LiveCallsPage'

const service = vi.hoisted(() => ({
  getLiveCalls: vi.fn(),
  getCallDirectory: vi.fn(),
}))
vi.mock('../features/live-call/services/callRestService', () => ({ callRestService: service }))

function call(id: string, extra: object = {}): LiveCallDto {
  return {
    call_id: id,
    start_time: 1000,
    direction: 'inbound',
    location_name: 'Chennai',
    executive_name: 'Ravi',
    caller_number: null,
    customer_name: 'Asha',
    utterance_count: 4,
    sentiment: null,
    complaints: [],
    escalation_level: null,
    escalation_status: null,
    alerts: [],
    ...extra,
  } as LiveCallDto
}

function page(items: LiveCallDto[], extra: Partial<LiveCallsDto> = {}): LiveCallsDto {
  return {
    items,
    limit: 50,
    offset: 0,
    matching: items.length,
    total: items.length,
    with_alerts: 0,
    negative_tone: 0,
    escalated: 0,
    now: 1065,
    ...extra,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LiveCallsPage />
    </MemoryRouter>,
  )
}


beforeEach(() => {
  service.getLiveCalls.mockReset().mockResolvedValue(page([]))
  service.getCallDirectory.mockReset().mockResolvedValue({
    locations: [{ id: 'loc-1', name: 'Chennai' }],
    executives: [{ id: 'ex-1', name: 'Ravi', is_active: true }],
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('LiveCallsPage', () => {
  it('shows a loading panel, then the empty state', async () => {
    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent('Loading ongoing calls')

    expect(await screen.findByText('No calls in progress')).toBeInTheDocument()
  })

  it('shows the totals and a card per call with its time on the call', async () => {
    service.getLiveCalls.mockResolvedValue(
      page([call('CALL-1', { sentiment: 'FRUSTRATED', complaints: [{ category: 'Cost', status: 'detected' }] })], {
        total: 7,
        with_alerts: 2,
        negative_tone: 3,
        escalated: 1,
      }),
    )
    renderPage()

    const card = (await screen.findByRole('article')) as HTMLElement
    expect(within(card).getByText('1:05')).toBeInTheDocument()
    expect(within(card).getByText('Frustrated')).toBeInTheDocument()
    expect(within(card).getByText('Cost')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Open the call' })).toHaveAttribute(
      'href',
      '/live-call?call_id=CALL-1',
    )
    expect(screen.getByText('Active calls').nextSibling).toHaveTextContent('7')
    expect(screen.getByText('With an alert').nextSibling).toHaveTextContent('2')
  })

  it('falls back to the caller number and to placeholders for unknown details', async () => {
    service.getLiveCalls.mockResolvedValue(
      page([call('CALL-2', { customer_name: null, caller_number: '+9199', executive_name: null, location_name: null, direction: null })]),
    )
    renderPage()

    expect(await screen.findByText('Executive not recorded')).toBeInTheDocument()
    expect(screen.getByText('+9199')).toBeInTheDocument()
    expect(screen.getByText('Location not recorded')).toBeInTheDocument()
    expect(screen.getByText('Not analysed yet')).toBeInTheDocument()
  })

  it('lists a standing alert on the call', async () => {
    service.getLiveCalls.mockResolvedValue(
      page([call('CALL-3', { alerts: [{ alert_type: 'poor_audio', subject: 'audio', message: 'Line is noisy' }] })]),
    )
    renderPage()

    expect(await screen.findByText('Line is noisy')).toBeInTheDocument()
    expect(screen.getByText('Poor audio')).toBeInTheDocument()
  })

  it('asks the server for the filtered calls and can clear the filters', async () => {
    renderPage()
    await screen.findByText('No calls in progress')
    const clear = screen.getByRole('button', { name: 'Clear filters' })
    expect(clear).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Only calls with an alert' }))
    await userEvent.selectOptions(screen.getByLabelText('Tone'), 'FRUSTRATED')

    expect(await screen.findByText('No ongoing calls match these filters')).toBeInTheDocument()
    expect(service.getLiveCalls).toHaveBeenLastCalledWith(50, 0, {
      alertsOnly: true,
      sentiment: 'FRUSTRATED',
    })

    await userEvent.click(clear)

    expect(await screen.findByText('No calls in progress')).toBeInTheDocument()
    expect(service.getLiveCalls).toHaveBeenLastCalledWith(50, 0, {})
  })

  it('offers the directory locations and executives as filters', async () => {
    renderPage()
    await screen.findByText('No calls in progress')

    await userEvent.selectOptions(screen.getByLabelText('Location'), 'loc-1')

    await waitFor(() =>
      expect(service.getLiveCalls).toHaveBeenLastCalledWith(50, 0, { locationId: 'loc-1' }),
    )
    expect(screen.getByRole('option', { name: 'Ravi' })).toBeInTheDocument()
  })

  it('pages through the matching calls', async () => {
    const first = Array.from({ length: 50 }, (_, i) => call(`CALL-${i}`))
    service.getLiveCalls.mockResolvedValue(page(first, { matching: 60 }))
    renderPage()

    await screen.findByText(/Showing/)
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: 'Next' }))

    await waitFor(() => expect(service.getLiveCalls).toHaveBeenLastCalledWith(50, 50, {}))
  })

  it('refreshes by itself every five seconds', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    renderPage()
    await waitFor(() => expect(service.getLiveCalls).toHaveBeenCalledTimes(1))

    await act(async () => {
      vi.advanceTimersByTime(5000)
    })

    expect(service.getLiveCalls).toHaveBeenCalledTimes(2)
  })

  it('keeps the last list and says it is stale when a refresh fails', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    service.getLiveCalls.mockResolvedValueOnce(page([call('CALL-1')]))
    renderPage()
    await screen.findByRole('article')

    service.getLiveCalls.mockRejectedValueOnce(new ApiError(503, 'Server busy'))
    await act(async () => {
      vi.advanceTimersByTime(5000)
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('Not refreshing: Server busy')
    expect(screen.getByRole('article')).toBeInTheDocument()
  })

  it('shows the error alone when the first load fails', async () => {
    service.getLiveCalls.mockRejectedValue(new Error('x'))
    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to load the ongoing calls.')
    expect(screen.queryByText('Active calls')).toBeNull()
  })
})
