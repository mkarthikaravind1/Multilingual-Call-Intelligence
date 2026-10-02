// The Live Call page shows either a call started from it ("Live Call") or
// one opened from a call list ("Call details", via ?call_id= alone). Calls
// started on the page carry this flag in the URL.
export const LIVE_SESSION_PARAM = 'live'

export function isCallDetailsView(params: URLSearchParams): boolean {
  return Boolean(params.get('call_id')?.trim()) && params.get(LIVE_SESSION_PARAM) !== '1'
}
