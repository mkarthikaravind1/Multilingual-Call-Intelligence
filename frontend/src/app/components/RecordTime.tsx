import { formatRecordTimestamp } from '../format/time'

// A record's date and time ("Oct 1, 2026, 8:11 PM"), in bold so it stands out
// from the label before it.
export function RecordTime({ seconds }: { seconds: number }) {
  return <strong className="record-time">{formatRecordTimestamp(seconds)}</strong>
}
