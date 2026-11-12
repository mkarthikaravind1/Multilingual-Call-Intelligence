import { beforeEach, describe, expect, it, vi } from 'vitest'

import { escalationRestService } from './escalationRestService'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../../api/client', () => ({ apiClient: api }))

beforeEach(() => {
  api.get.mockReset().mockResolvedValue([])
  api.post.mockReset().mockResolvedValue({})
})

describe('escalationRestService', () => {
  it('lists the queue for a state, defaulting to active', async () => {
    await escalationRestService.listQueue()

    expect(api.get).toHaveBeenCalledWith('/api/v1/escalations?state=active')
  })

  it('sends only the date bounds that are set', async () => {
    await escalationRestService.listQueue('open', { detectedFrom: 100, acknowledgedTo: 0 })

    const url = new URL(api.get.mock.calls[0][0], 'http://x')
    expect(url.searchParams.get('state')).toBe('open')
    expect(url.searchParams.get('detected_from')).toBe('100')
    // Zero is a real value, not "unset".
    expect(url.searchParams.get('acknowledged_to')).toBe('0')
    expect(url.searchParams.has('detected_to')).toBe(false)
  })

  it('encodes the call id when acknowledging', async () => {
    await escalationRestService.acknowledge('CALL 1/2')

    expect(api.post).toHaveBeenCalledWith('/api/v1/escalations/CALL%201%2F2/acknowledge', {})
  })

  it('trims the resolution note and sends null when blank', async () => {
    await escalationRestService.resolve('c1', '  fixed  ')
    await escalationRestService.resolve('c1', '   ')

    expect(api.post).toHaveBeenNthCalledWith(1, '/api/v1/escalations/c1/resolve', { note: 'fixed' })
    expect(api.post).toHaveBeenNthCalledWith(2, '/api/v1/escalations/c1/resolve', { note: null })
  })
})
