interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  className?: string
  ariaLabel?: string
}

/**
 * Inline SVG sparkline. Pure presentational — no client interactivity, no deps.
 * Renders a smoothed line plus filled area under the curve.
 */
export function Sparkline({
  values,
  width = 320,
  height = 64,
  className,
  ariaLabel = 'Trend',
}: SparklineProps) {
  if (values.length === 0) {
    return (
      <div
        className={className}
        style={{ width, height }}
        role="img"
        aria-label="No data"
      />
    )
  }

  const pad = 4
  const innerW = width - pad * 2
  const innerH = height - pad * 2
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const range = Math.max(max - min, 1)

  const step = values.length > 1 ? innerW / (values.length - 1) : 0
  const points = values.map((v, i) => {
    const x = pad + step * i
    const y = pad + innerH - ((v - min) / range) * innerH
    return [x, y] as const
  })

  const line = points
    .map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`))
    .join(' ')
  const area = `${line} L${points[points.length - 1][0]},${pad + innerH} L${points[0][0]},${pad + innerH} Z`

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label={ariaLabel}
    >
      <path d={area} fill="currentColor" opacity={0.12} />
      <path
        d={line}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
