import { useState, useEffect } from 'react'
import { Tooltip, ResponsiveContainer } from 'recharts'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function scoreToColor(score) {
  if (score == null) return '#1f2937'
  const clamped = Math.max(0, Math.min(1, score))
  // red (fail) -> yellow (mid) -> green (pass)
  const r = Math.round(clamped < 0.5 ? 220 : 220 - (clamped - 0.5) * 2 * 180)
  const g = Math.round(clamped < 0.5 ? clamped * 2 * 180 : 180)
  const b = Math.round(40)
  return `rgb(${r}, ${g}, ${b})`
}

function HeatmapTooltip({ payload }) {
  if (!payload || payload.length === 0) return null
  const data = payload[0]?.payload
  if (!data) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 shadow-xl text-sm min-w-max">
      <p className="font-semibold text-white mb-1">{data.model} / {data.task}</p>
      <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 text-gray-300 whitespace-nowrap">
        <span>Score:</span>
        <span className="text-right font-mono">{data.score?.toFixed(3) ?? 'N/A'}</span>
        <span>Confidence:</span>
        <span className="text-right font-mono">{data.confidence?.toFixed(3) ?? 'N/A'}</span>
        <span>Cal R:</span>
        <span className="text-right font-mono">{data.calibration_r?.toFixed(3) ?? 'N/A'}</span>
        <span>Latency:</span>
        <span className="text-right font-mono">{data.latency != null ? `${data.latency.toFixed(0)}ms` : 'N/A'}</span>
      </div>
    </div>
  )
}

export default function CapabilityMatrix() {
  const [matrix, setMatrix] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [hoveredCell, setHoveredCell] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/capability-matrix`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => {
        // API returns a flat array: [{task, model, mean_score, ...}]
        // Transform into {tasks, models, cells} for the heatmap.
        if (!Array.isArray(data) || data.length === 0) {
          setError('Empty response from API')
          setLoading(false)
          return
        }
        const tasks = [...new Set(data.map(d => d.task))]
        const models = [...new Set(data.map(d => d.model))]
        const cells = data.map(d => ({
          task: d.task,
          model: d.model,
          score: d.mean_score,
          confidence: d.mean_confidence,
          calibration_r: d.calibration_r,
          latency: d.mean_latency_ms,
          passes_threshold: d.passes_threshold,
          tier: d.tier,
        }))
        setMatrix({ tasks, models, cells })
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />
  if (!matrix || !matrix.tasks || !matrix.models || !matrix.cells) {
    return <ErrorState message="Invalid data format from API" />
  }

  const { tasks, models, cells } = matrix

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Capability Matrix</h2>
        <p className="text-gray-400 mt-1">Model performance across task families. Green = high score, red = low score.</p>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-sm font-medium text-gray-400 p-2 min-w-[140px]">Task</th>
              {models.map(model => (
                <th key={model} className="text-center text-sm font-medium text-gray-400 p-2 min-w-[100px]">
                  <span className="block truncate max-w-[120px]" title={model}>{model}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map((task, rowIdx) => (
              <tr key={task}>
                <td className="text-sm text-gray-300 p-2 font-medium">{task}</td>
                {models.map(model => {
                  const cell = cells.find(c => c.task === task && c.model === model)
                  const score = cell?.score
                  const isHovered = hoveredCell?.task === task && hoveredCell?.model === model
                  const showBelow = rowIdx === 0
                  return (
                    <td key={model} className="p-1">
                      <div
                        className="relative group cursor-pointer rounded-md h-12 flex items-center justify-center transition-all"
                        style={{
                          backgroundColor: scoreToColor(score),
                          opacity: isHovered ? 1 : 0.85,
                          transform: isHovered ? 'scale(1.05)' : 'scale(1)',
                        }}
                        onMouseEnter={() => setHoveredCell({ task, model })}
                        onMouseLeave={() => setHoveredCell(null)}
                      >
                        <span className="text-xs font-mono font-bold text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]">
                          {score != null ? score.toFixed(2) : '—'}
                        </span>
                        {isHovered && cell && (
                          <div className={`absolute z-50 left-1/2 -translate-x-1/2 pointer-events-none ${showBelow ? 'top-full mt-2' : 'bottom-full mb-2'}`}>
                            <HeatmapTooltip payload={[{ payload: cell }]} />
                          </div>
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>

        <div className="flex items-center justify-center gap-2 mt-6 text-xs text-gray-400">
          <span>0.0</span>
          <div className="flex h-3 w-48 rounded overflow-hidden">
            {Array.from({ length: 20 }, (_, i) => (
              <div key={i} className="flex-1" style={{ backgroundColor: scoreToColor(i / 19) }} />
            ))}
          </div>
          <span>1.0</span>
        </div>
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-pulse text-gray-500 text-sm">Loading capability matrix...</div>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="bg-red-950/50 border border-red-800 rounded-lg px-6 py-4 text-red-400 text-sm">
        Failed to load data: {message}
      </div>
    </div>
  )
}
