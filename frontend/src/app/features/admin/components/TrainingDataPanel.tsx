import { useEffect, useState } from 'react'

import { apiClient } from '../../../api/client'
import { ApiError } from '../../../api/errors'
import { StatePanel } from '../../../components/StatePanel'
import { humanizeLabel } from '../../../format/text'

interface TrainingDataDto {
  // AI outputs a person has judged.
  examples: number
  // Of those, with a correct answer and a transcript: usable to fine-tune.
  with_messages: number
  by_task: Record<string, number>
}

const basePath = '/api/v1/learning/training-data'

function saveFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

// Every AI output a person has judged, as a file a model could one day be
// fine-tuned on. Administrators only: the file holds call transcripts.
export function TrainingDataPanel() {
  const [summary, setSummary] = useState<TrainingDataDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isDownloading, setIsDownloading] = useState(false)

  useEffect(() => {
    let cancelled = false
    apiClient
      .get<TrainingDataDto>(basePath)
      .then((loaded) => {
        if (!cancelled) setSummary(loaded)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Unable to load the training data.')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const download = async () => {
    setIsDownloading(true)
    setError(null)
    try {
      saveFile(await apiClient.download(`${basePath}/export`), 'training-data.jsonl')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The download failed.')
    } finally {
      setIsDownloading(false)
    }
  }

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Training data</h3>
          <p className="customer-panel__muted">
            Nothing here retrains the AI: the models belong to their providers. This is every AI
            output someone has corrected or judged, with the call it came from, in a file a model
            could be fine-tuned on later. It holds what customers said, and each download is
            recorded.
          </p>
        </div>
        <button
          type="button"
          className="button button--secondary"
          disabled={isDownloading || !summary || summary.examples === 0}
          onClick={() => void download()}
        >
          {isDownloading ? 'Preparing…' : 'Download (JSON Lines)'}
        </button>
      </div>

      {error && <p className="inline-notice">{error}</p>}
      {!summary && !error && <StatePanel compact variant="loading" title="Loading…" />}
      {summary && summary.examples === 0 && (
        <StatePanel
          compact
          title="Nothing has been judged yet"
          description="Corrections and question ratings given on finished calls collect here."
        />
      )}
      {summary && summary.examples > 0 && (
        <div className="list-card__facts">
          <span>
            Judged outputs: <strong>{summary.examples}</strong>
          </span>
          <span>
            Usable to fine-tune: <strong>{summary.with_messages}</strong>
          </span>
          {Object.entries(summary.by_task).map(([task, count]) => (
            <span key={task}>
              {humanizeLabel(task)}: <strong>{count}</strong>
            </span>
          ))}
        </div>
      )}
    </section>
  )
}
