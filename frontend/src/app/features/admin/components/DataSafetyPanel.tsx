import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../../../api/errors'
import { RecordTime } from '../../../components/RecordTime'
import { StatePanel } from '../../../components/StatePanel'
import { adminRestService } from '../services/adminRestService'
import type { DataSafetyDto } from '../types/dto'

const REFRESH_INTERVAL_MS = 30000

function size(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function every(seconds: number): string {
  const hours = seconds / 3600
  return hours >= 48 ? `every ${Math.round(hours / 24)} days` : `every ${Math.round(hours)} hours`
}

type Action = 'copy' | 'check' | 'backup'

// Copies of recordings and transcripts off the server, the check that
// stored recordings are intact, and database backups (administrators).
export function DataSafetyPanel() {
  const [status, setStatus] = useState<DataSafetyDto | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<Action | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setStatus(await adminRestService.getDataSafety())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Unable to load data safety.')
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const refresh = () => {
      if (!cancelled) void load()
    }
    refresh()
    const intervalId = window.setInterval(refresh, REFRESH_INTERVAL_MS)
    return () => {
      cancelled = true
      window.clearInterval(intervalId)
    }
  }, [load])

  const run = async (action: Action) => {
    setBusy(action)
    setNotice(null)
    try {
      if (action === 'copy') {
        const result = await adminRestService.copyOffsiteNow()
        setNotice(
          result.skipped_reason ??
            `Copied ${result.recordings_copied} recordings and ${result.transcripts_copied} transcripts` +
              (result.failed ? `; ${result.failed} failed: ${result.last_error ?? ''}` : '.'),
        )
      } else if (action === 'check') {
        const result = await adminRestService.checkRecordingsNow()
        setNotice(
          result.skipped_reason ??
            `Checked ${result.checked} recordings: ${result.ok} intact, ${result.repaired} repaired, ${result.lost} lost.`,
        )
      } else {
        const backup = await adminRestService.backUpNow()
        setNotice(
          backup.status === 'done'
            ? `Backup stored (${size(backup.size_bytes)}).`
            : `The backup failed: ${backup.error ?? 'see the server log'}`,
        )
      }
      await load()
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : 'That did not work.')
    } finally {
      setBusy(null)
    }
  }

  const lastBackup = status?.backups.find((backup) => backup.status === 'done')

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h3 className="section-title">Data safety</h3>
          <p className="customer-panel__muted">
            Copies of recordings and transcripts kept off this server, the check that stored
            recordings are intact, and database backups.
          </p>
        </div>
      </div>

      {notice && <p className="inline-notice">{notice}</p>}
      {error && (
        <StatePanel compact variant="error" title="Could not load data safety" description={error} />
      )}
      {!error && !status && <StatePanel compact variant="loading" title="Loading…" />}

      {status && (
        <div className="card-stack">
          <article className="list-card">
            <div className="section-heading complaint-card__heading">
              <strong className="list-card__title">Copies off the server</strong>
              <span className={`badge ${status.archive_enabled ? 'badge--success' : 'badge--warning'}`}>
                {status.archive_enabled ? 'On' : 'Off'}
              </span>
            </div>
            {status.archive_enabled ? (
              <>
                <div className="list-card__facts">
                  <span className="data-safety__where">Going to: <strong>{status.storage}</strong></span>
                  <span>
                    Transcripts copied: <strong>{status.transcripts_archived}</strong>
                    {status.transcripts_pending > 0 && ` (${status.transcripts_pending} waiting)`}
                  </span>
                  {status.recordings_enabled && (
                    <span>
                      Recordings copied: <strong>{status.recordings_archived}</strong> of{' '}
                      <strong>{status.recordings_kept}</strong>
                    </span>
                  )}
                  {status.last_archive_run && (
                    <span>Last copied: <RecordTime seconds={status.last_archive_run.ran_at} /></span>
                  )}
                </div>
                {status.last_archive_run && status.last_archive_run.failed > 0 && (
                  <p className="summary-delivery__message">
                    {status.last_archive_run.failed} copies failed at the last try (they are tried
                    again): {status.last_archive_run.last_error}
                  </p>
                )}
                <div className="button-row">
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={busy !== null}
                    onClick={() => void run('copy')}
                  >
                    {busy === 'copy' ? 'Copying…' : 'Copy now'}
                  </button>
                </div>
              </>
            ) : (
              <p>
                Nothing is copied off this server. Set <code>ARCHIVE_STORAGE_PROVIDER</code> and{' '}
                <code>ARCHIVE_ENCRYPTION_KEY</code> to turn it on.
              </p>
            )}
          </article>

          <article className="list-card">
            <div className="section-heading complaint-card__heading">
              <strong className="list-card__title">Stored recordings</strong>
              {status.recordings_enabled ? (
                <span className={`badge ${status.recordings_lost > 0 ? 'badge--danger' : 'badge--success'}`}>
                  {status.recordings_lost > 0 ? `${status.recordings_lost} lost` : 'Intact'}
                </span>
              ) : (
                <span className="badge badge--warning">Off</span>
              )}
            </div>
            {status.recordings_enabled ? (
              <>
                <div className="list-card__facts">
                  <span>Kept now: <strong>{status.recordings_kept}</strong></span>
                  <span>Checked: <strong>{status.recordings_checked}</strong></span>
                  {status.last_integrity_run && (
                    <span>
                      Last check: <RecordTime seconds={status.last_integrity_run.ran_at} /> (
                      {status.last_integrity_run.checked} checked,{' '}
                      {status.last_integrity_run.repaired} repaired)
                    </span>
                  )}
                </div>
                {status.lost.length > 0 && (
                  <p className="summary-delivery__message">
                    Missing or changed, with no good copy to restore:{' '}
                    {status.lost.map((lost, index) => (
                      <span key={lost.call_id}>
                        {index > 0 && ', '}
                        <Link
                          className="text-link"
                          to={`/post-call-analysis?call_id=${encodeURIComponent(lost.call_id)}`}
                        >
                          {lost.call_id}
                        </Link>
                      </span>
                    ))}
                  </p>
                )}
                <div className="button-row">
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={busy !== null}
                    onClick={() => void run('check')}
                  >
                    {busy === 'check' ? 'Checking…' : 'Check now'}
                  </button>
                </div>
              </>
            ) : (
              <p>This server keeps no call recordings.</p>
            )}
          </article>

          <article className="list-card">
            <div className="section-heading complaint-card__heading">
              <strong className="list-card__title">Database backups</strong>
              <span className={`badge ${status.backups_enabled ? 'badge--success' : 'badge--warning'}`}>
                {status.backups_enabled ? 'On' : 'Off'}
              </span>
            </div>
            {status.backups_enabled ? (
              <>
                <div className="list-card__facts">
                  {status.backup_interval_seconds !== null && (
                    <span>Made: <strong>{every(status.backup_interval_seconds)}</strong></span>
                  )}
                  {status.backup_retention_days !== null && (
                    <span>Kept: <strong>{Math.round(status.backup_retention_days)} days</strong></span>
                  )}
                  <span>
                    Last good backup:{' '}
                    {lastBackup ? (
                      <>
                        <RecordTime seconds={lastBackup.started_at} /> ({size(lastBackup.size_bytes)})
                      </>
                    ) : (
                      <strong>none yet</strong>
                    )}
                  </span>
                </div>
                {status.backups[0]?.status === 'failed' && (
                  <p className="summary-delivery__message">
                    The last backup failed: {status.backups[0].error}
                  </p>
                )}
                <div className="button-row">
                  <button
                    type="button"
                    className="button button--secondary"
                    disabled={busy !== null}
                    onClick={() => void run('backup')}
                  >
                    {busy === 'backup' ? 'Backing up…' : 'Back up now'}
                  </button>
                </div>
              </>
            ) : (
              <p>
                The database is not backed up by the application. Set <code>BACKUP_ENABLED</code>{' '}
                (it needs the copies above turned on).
              </p>
            )}
          </article>
        </div>
      )}
    </section>
  )
}
