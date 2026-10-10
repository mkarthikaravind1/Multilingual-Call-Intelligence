import { useState, type MouseEvent } from 'react'

import { dayFormat, formatBucket } from '../format/bucket'
import type { ReportBucket } from '../services/reportRestService'

export type TrendLine = {
  category: string
  counts: number[]
  // A CSS colour; the same category keeps it whatever else is shown.
  color: string
}

type TrendChartProps = {
  bucket: ReportBucket
  // When each day or week starts (epoch seconds).
  bucketStarts: number[]
  lines: TrendLine[]
}

const WIDTH = 760
const HEIGHT = 280
const MARGIN = { top: 12, right: 16, bottom: 30, left: 40 }
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom
const MAX_X_LABELS = 7

// A round number at or above the largest count, and the step between gridlines.
function yScale(max: number): { top: number; step: number } {
  const step = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000].find(
    (candidate) => candidate * 4 >= max,
  ) ?? Math.ceil(max / 4)
  return { top: step * 4, step }
}

export function TrendChart({ bucket, bucketStarts, lines }: TrendChartProps) {
  const [hovered, setHovered] = useState<number | null>(null)

  const count = bucketStarts.length
  const max = Math.max(1, ...lines.flatMap((line) => line.counts))
  const { top, step } = yScale(max)
  // A single period sits in the middle of the plot.
  const x = (index: number) =>
    MARGIN.left + (count === 1 ? PLOT_WIDTH / 2 : (index / (count - 1)) * PLOT_WIDTH)
  const y = (value: number) => MARGIN.top + PLOT_HEIGHT - (value / top) * PLOT_HEIGHT

  const labelEvery = Math.max(1, Math.ceil(count / MAX_X_LABELS))

  const onMove = (event: MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const position = ((event.clientX - box.left) / box.width) * WIDTH
    const index = Math.round(((position - MARGIN.left) / PLOT_WIDTH) * (count - 1))
    setHovered(Math.min(count - 1, Math.max(0, count === 1 ? 0 : index)))
  }

  return (
    <div className="trend-chart">
      <ul className="chart-legend" aria-label="Categories">
        {lines.map((line) => (
          <li key={line.category}>
            <span className="chart-legend__swatch" style={{ background: line.color }} />
            {line.category}
          </li>
        ))}
      </ul>

      <div className="trend-chart__plot">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Complaints per ${bucket} for each category. The table below has the same numbers.`}
          onMouseMove={onMove}
          onMouseLeave={() => setHovered(null)}
        >
          {[0, 1, 2, 3, 4].map((line) => (
            <g key={line}>
              <line
                className={line === 0 ? 'chart-axis' : 'chart-grid'}
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(line * step)}
                y2={y(line * step)}
              />
              <text className="chart-tick" x={MARGIN.left - 8} y={y(line * step) + 4} textAnchor="end">
                {line * step}
              </text>
            </g>
          ))}

          {bucketStarts.map((start, index) =>
            index % labelEvery === 0 ? (
              <text
                key={start}
                className="chart-tick"
                x={x(index)}
                y={HEIGHT - 8}
                textAnchor="middle"
              >
                {dayFormat.format(new Date(start * 1000))}
              </text>
            ) : null,
          )}

          {hovered !== null && (
            <line
              className="chart-crosshair"
              x1={x(hovered)}
              x2={x(hovered)}
              y1={MARGIN.top}
              y2={MARGIN.top + PLOT_HEIGHT}
            />
          )}

          {lines.map((line) => (
            <g key={line.category}>
              <polyline
                className="trend-chart__line"
                stroke={line.color}
                points={line.counts.map((value, index) => `${x(index)},${y(value)}`).join(' ')}
              />
              {/* A lone period has no line to draw: show its point. */}
              {(count === 1 || hovered !== null) && (
                <circle
                  className="trend-chart__point"
                  cx={x(hovered ?? 0)}
                  cy={y(line.counts[hovered ?? 0])}
                  r={4}
                  fill={line.color}
                />
              )}
            </g>
          ))}
        </svg>

        {hovered !== null && (
          <div
            className={`chart-tooltip${x(hovered) > WIDTH / 2 ? ' chart-tooltip--left' : ''}`}
            style={{ left: `${(x(hovered) / WIDTH) * 100}%` }}
            role="status"
          >
            <strong>{formatBucket(bucketStarts[hovered], bucket)}</strong>
            {lines.map((line) => (
              <span key={line.category} className="chart-tooltip__row">
                <span className="chart-legend__swatch" style={{ background: line.color }} />
                <span>{line.category}</span>
                <b>{line.counts[hovered]}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
