import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { RecordTime } from '../../../components/RecordTime'
import { StatePanel } from '../../../components/StatePanel'
import { humanizeLabel } from '../../../format/text'
import { learningRestService } from '../services/learningRestService'
import type { CorrectionsDto, LearningEvidenceDto } from '../types/dto'

// "Customer Name(Vehicle Number)", or as much of it as is known.
function caller(item: LearningEvidenceDto): string {
  if (!item.customer_name) return 'Open the call'
  return item.vehicle_registration
    ? `${item.customer_name}(${item.vehicle_registration})`
    : item.customer_name
}

// Where a person corrected the AI or rated what it suggested. The AI's own
// outputs (one record each, several per call) are counted, never listed:
// nobody reads them, and they are what made this page a wall of text.
export function CorrectionsPanel() {
  const [data, setData] = useState<CorrectionsDto | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    learningRestService
      .listCorrections()
      .then((loaded) => {
        if (!cancelled) setData(loaded)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Unable to load the corrections.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Corrections made by people</h3>
          <p className="customer-panel__muted">
            Each time someone corrects the AI on a finished call, or rates a question it suggested,
            it is kept here. When the same correction keeps coming up it becomes a suggested
            improvement.
          </p>
        </div>
        {data && (
          <span className="customer-panel__muted">
            {data.corrections.length} of {data.evidence_total} records
          </span>
        )}
      </div>

      {error && (
        <StatePanel compact variant="error" title="Could not load the corrections" description={error} />
      )}
      {!data && !error && <StatePanel compact variant="loading" title="Loading corrections…" />}

      {data && data.corrections.length === 0 && (
        <StatePanel
          compact
          title="No corrections yet"
          description="Correct the AI under “Review AI output” on a finished call's page and it appears here."
        />
      )}

      {data && data.corrections.length > 0 && (
        <div className="card-stack">
          {data.corrections.map((item) => (
            <article
              key={item.evidence_id}
              className={`list-card evidence-card evidence-tone--${item.component}`}
            >
              <div className="evidence-card__top">
                <div className="list-card__meta">
                  <span className="badge evidence-card__component">
                    {humanizeLabel(item.component)}
                  </span>
                  <span className="badge">{humanizeLabel(item.evidence_type)}</span>
                </div>
                <div className="list-card__facts evidence-card__source">
                  <span>
                    Call:{' '}
                    <Link
                      className="text-link"
                      to={`/post-call-analysis?call_id=${encodeURIComponent(item.call_id)}`}
                      title={`Call ${item.call_id}`}
                    >
                      {caller(item)}
                    </Link>
                  </span>
                  <span>
                    <RecordTime seconds={item.created_at} />
                  </span>
                </div>
              </div>

              {item.actual_value && item.human_correction ? (
                <p className="correction-change">
                  <span>
                    The AI said <strong>{item.actual_value}</strong>
                  </span>
                  <span aria-hidden="true">→</span>
                  <span>
                    corrected to <strong>{item.human_correction}</strong>
                  </span>
                </p>
              ) : (
                <p>{item.description}</p>
              )}
            </article>
          ))}
        </div>
      )}

      {data && data.evidence_total > data.corrections.length && (
        <p className="customer-panel__muted">
          The other {data.evidence_total - data.corrections.length} records are the AI's own
          outputs (each complaint it named, tone it rated and question it suggested). They are
          kept to measure whether an improvement works and are not listed.
        </p>
      )}
    </section>
  )
}
