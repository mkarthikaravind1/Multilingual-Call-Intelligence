import { StatePanel } from '../../../components/StatePanel'
import { ComplaintStatusBadge, SentimentBadge } from '../../../components/ToneBadges'
import type { PostCallSummaryViewModel } from '../types/view-models'

export type PostCallSummaryState =
  | 'available'
  | 'active_call'
  | 'no_speech'
  | 'generating'
  | 'unavailable'

type PostCallSummaryPanelProps = {
  state: PostCallSummaryState
  summary: PostCallSummaryViewModel | null
}

function SummaryStatus({ state }: { state: Exclude<PostCallSummaryState, 'available'> }) {
  switch (state) {
    case 'active_call':
      return (
        <StatePanel
          compact
          title="Summary not generated yet"
          description="The post-call summary is generated automatically when this call is completed."
        />
      )
    case 'no_speech':
      return (
        <StatePanel
          compact
          title="No speech recorded"
          description="No utterances were recorded on this call, so there is nothing to summarise."
        />
      )
    case 'generating':
      return (
        <StatePanel
          compact
          variant="loading"
          title="Generating post-call summary…"
          description="The summary is created when a call completes. This usually takes a few seconds."
        />
      )
    case 'unavailable':
      return (
        <StatePanel
          compact
          title="No post-call summary stored"
          description="No summary is stored for this call. Calls completed before summaries were stored, or whose summary generation failed, have no summary."
        />
      )
  }
}

const STATE_BADGES: Record<PostCallSummaryState, { label: string; tone: string }> = {
  available: { label: 'Summary ready', tone: 'success' },
  generating: { label: 'Generating', tone: 'warning' },
  active_call: { label: 'Call in progress', tone: 'active' },
  no_speech: { label: 'No speech', tone: 'neutral' },
  unavailable: { label: 'Not available', tone: 'neutral' },
}

export function PostCallSummaryPanel({ state, summary }: PostCallSummaryPanelProps) {
  const effectiveState = state === 'available' && !summary ? 'unavailable' : state
  const stateBadge = STATE_BADGES[effectiveState]

  return (
    <section className="panel">
      <div className="section-heading">
        <h3 className="section-title">Post-call summary</h3>
        <span className={`badge badge--${stateBadge.tone}`}>{stateBadge.label}</span>
      </div>

      {effectiveState !== 'available' || !summary ? (
        <SummaryStatus state={effectiveState === 'available' ? 'unavailable' : effectiveState} />
      ) : (
        <>
          <p className="summary-text summary-text--lead">{summary.overallSummary}</p>

          <div className="fact-grid spaced-top">
            <div className="fact">
              <span>Sentiment</span>
              <div className="list-card__meta">
                <SentimentBadge label={summary.sentiment.label} />
                <small className="fact__note">
                  {Math.round(summary.sentiment.confidence * 100)}% confidence
                </small>
              </div>
            </div>
            <div className="fact">
              <span>Follow-up</span>
              <div className="list-card__meta">
                <span
                  className={`badge badge--${summary.followUpRequired ? 'warning' : 'success'}`}
                >
                  {summary.followUpRequired ? 'Required' : 'Not required'}
                </span>
              </div>
            </div>
            <div className="fact">
              <span>Languages</span>
              <div className="list-card__meta">
                {summary.languages.map((language) => (
                  <span key={language} className="badge">
                    {language.toUpperCase()}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="summary-grid">
            <div>
              <p className="panel__label">Customer summary</p>
              <p className="summary-callout">{summary.customerSummary}</p>
            </div>

            {summary.unresolvedIssues.length > 0 && (
              <div>
                <p className="panel__label">Unresolved issues</p>
                <ul className="bullet-list">
                  {summary.unresolvedIssues.map((issue) => (
                    <li key={issue}>{issue}</li>
                  ))}
                </ul>
              </div>
            )}

            {summary.actionsPromised.length > 0 && (
              <div>
                <p className="panel__label">Actions promised</p>
                <ul className="bullet-list">
                  {summary.actionsPromised.map((action) => (
                    <li key={action}>{action}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {summary.complaints.length > 0 && (
            <div className="spaced-top">
              <p className="panel__label">Complaints</p>
              <div className="card-stack">
                {summary.complaints.map((complaint) => (
                  <article key={complaint.category} className="list-card">
                    <div className="list-card__meta">
                      <strong className="list-card__title">{complaint.category}</strong>
                      <ComplaintStatusBadge status={complaint.status} />
                    </div>
                    <p>{complaint.description}</p>
                    <div className="list-card__facts">
                      <span>Evidence: “{complaint.evidence}”</span>
                      {complaint.confidence !== null && (
                        <span>Confidence: {Math.round(complaint.confidence * 100)}%</span>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
