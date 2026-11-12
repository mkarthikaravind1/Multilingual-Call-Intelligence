import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from './client'
import { ApiError } from './errors'

const fetchMock = vi.fn<typeof fetch>()

function reply(body: string, status = 200) {
  fetchMock.mockResolvedValueOnce(new Response(body || null, { status }))
}

function lastCall() {
  const [url, init] = fetchMock.mock.calls.at(-1)!
  return { url: String(url), init: init!, headers: new Headers(init!.headers) }
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  fetchMock.mockReset()
  vi.unstubAllGlobals()
})

describe('ApiClient.request', () => {
  it('joins the base url and path whatever the slashes', async () => {
    const client = new ApiClient('http://api.test/')
    reply('{}')
    reply('{}')

    await client.get('calls')
    expect(lastCall().url).toBe('http://api.test/calls')
    await client.get('/calls')
    expect(lastCall().url).toBe('http://api.test/calls')
  })

  it('sends JSON content type and the bearer token', async () => {
    const client = new ApiClient('http://api.test')
    client.setAccessToken('tok')
    reply('{"ok":true}')

    await expect(client.post('/x', { a: 1 })).resolves.toEqual({ ok: true })

    const { init, headers } = lastCall()
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"a":1}')
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.get('Authorization')).toBe('Bearer tok')
  })

  it('leaves the content type to the browser for FormData', async () => {
    const client = new ApiClient('http://api.test')
    reply('{}')

    await client.request('/upload', { method: 'POST', body: new FormData() })

    expect(lastCall().headers.has('Content-Type')).toBe(false)
  })

  it('returns undefined for an empty body and text for a non-JSON body', async () => {
    const client = new ApiClient('http://api.test')
    reply('', 204)
    reply('plain')

    await expect(client.get('/a')).resolves.toBeUndefined()
    await expect(client.get('/b')).resolves.toBe('plain')
  })

  it('throws an ApiError with the server message on failure', async () => {
    const client = new ApiClient('http://api.test')
    reply('{"detail":"Call not found"}', 404)

    const error = await client.get('/calls/1').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404, message: 'Call not found' })
  })

  it('wraps network failures in a friendly ApiError', async () => {
    const client = new ApiClient('http://api.test')
    fetchMock.mockRejectedValueOnce(new TypeError('offline'))

    await expect(client.get('/x')).rejects.toMatchObject({
      status: 500,
      message: 'Unable to reach the server. Please try again.',
    })
  })

  it('reports 401 and 403 to the handlers unless quiet', async () => {
    const client = new ApiClient('http://api.test')
    const onUnauthorized = vi.fn()
    const onForbidden = vi.fn()
    client.setErrorHandlers({ onUnauthorized, onForbidden })
    reply('{}', 401)
    reply('{}', 403)
    reply('{}', 401)

    await client.get('/a').catch(() => {})
    await client.get('/b').catch(() => {})
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(onForbidden).toHaveBeenCalledTimes(1)

    await client.request('/c', {}, true).catch(() => {})
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })
})

describe('ApiClient.download', () => {
  it('returns the blob with the token attached', async () => {
    const client = new ApiClient('http://api.test')
    client.setAccessToken('tok')
    reply('csv,data')

    const blob = await client.download('/export')

    expect(await blob.text()).toBe('csv,data')
    expect(lastCall().headers.get('Authorization')).toBe('Bearer tok')
  })

  it('throws and notifies on 401', async () => {
    const client = new ApiClient('http://api.test')
    const onUnauthorized = vi.fn()
    client.setErrorHandlers({ onUnauthorized })
    reply('', 401)

    await expect(client.download('/export')).rejects.toMatchObject({ status: 401 })
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })
})
