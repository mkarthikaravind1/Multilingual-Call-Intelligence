import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../api/errors'
import { StatePanel } from '../components/StatePanel'
import { toEscalationViewModel } from '../features/escalation/adapters/toEscalationViewModel'
import { EscalationCard } from '../features/escalation/components/EscalationCard'
import { escalationRestService } from '../features/escalation/services/escalationRestService'

import type { EscalationViewModel } from '../features/escalation/types/view-models'

// New escalations appear without a manual refresh.
const REFRESH_INTERVAL_MS = 10000

type QueueView = 'active' | 'resolved'

export function EscalationsPage() {
  const [view, setView] = useState<QueueView>('active')
  const [escalations, setEscalations] = useState<EscalationViewModel[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (state: QueueView) => {
    try {
      const data = await escalationRestService.listQueue(state)
      setEscalations(data.map(toEscalationViewModel))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load escalations.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) {
        void load(view)
      }
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [view, load])

  const switchView = (next: QueueView) => {
    if (next !== view) {
      setIsLoading(true)
      setEscalations([])
      setView(next)
    }
  }

  const handleUpdated = (updated: EscalationViewModel) => {
    setEscalations((current) =>
      view === 'active' && updated.status === 'resolved'
        ? current.filter((item) => item.callId !== updated.callId)
        : current.map((item) => (item.callId === updated.callId ? updated : item)),
    )
  }

  const counts = {
    critical: escalations.filter((e) => e.level === 'critical').length,
    open: escalations.filter((e) => e.status === 'open').length,
  }

  return (
    <section className="page-shell">
      <div className="page-shell__header page-shell__header--actions">
        <div className="button-row" role="tablist" aria-label="Escalation queue">
          <button
            type="button"
            role="tab"
            aria-selected={view === 'active'}
            className={view === 'active' ? 'button' : 'button button--secondary'}
            onClick={() => switchView('active')}
          >
            Active
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === 'resolved'}
            className={view === 'resolved' ? 'button' : 'button button--secondary'}
            onClick={() => switchView('resolved')}
          >
            Resolved
          </button>
        </div>
        {view === 'active' && !isLoading && !error && (
          <span className="customer-panel__muted">
            {escalations.length} active · {counts.critical} critical · {counts.open} not yet acknowledged
          </span>
        )}
      </div>

      {isLoading && <StatePanel variant="loading" title="Loading escalations…" />}

      {!isLoading && error && (
        <StatePanel variant="error" title="Could not load escalations" description={error} />
      )}

      {!isLoading && !error && escalations.length === 0 && (
        <StatePanel
          title={view === 'active' ? 'No active escalations' : 'No resolved escalations yet'}
          description={
            view === 'active'
              ? 'Calls appear here as soon as a customer asks for a manager, threatens legal action or a public complaint, wants to cancel, or stays clearly negative with open complaints.'
              : 'Escalations you resolve are kept here with the resolution note.'
          }
        />
      )}

      {!isLoading && !error && escalations.length > 0 && (
        <div className="card-stack">
          {escalations.map((escalation) => (
            <EscalationCard
              key={escalation.callId}
              escalation={escalation}
              canManage
              showCallLink
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}
    </section>
  )
}
