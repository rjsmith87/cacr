import { useState, useEffect, useCallback, useMemo } from 'react'
import ELI5Panel from '../components/ELI5Panel'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function scoreToColor(score) {
  if (score == null) return '#1f2937'
  const clamped = Math.max(0, Math.min(1, score))
  const r = Math.round(clamped < 0.5 ? 220 : 220 - (clamped - 0.5) * 2 * 180)
  const g = Math.round(clamped < 0.5 ? clamped * 2 * 180 : 180)
  const b = Math.round(40)
  return `rgb(${r}, ${g}, ${b})`
}

function TooltipContent({ data }) {
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
  // tooltip: { cell, top, left } or null
  const [tooltip, setTooltip] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/capability-matrix`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(data => {
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

  const handleMouseEnter = useCallback((e, cell) => {
    const rect = e.currentTarget.getBoundingClientRect()
    // Position tooltip centered below the cell, clamped to viewport
    const tooltipW = 220
    let left = rect.left + rect.width / 2 - tooltipW / 2
    left = Math.max(8, Math.min(left, window.innerWidth - tooltipW - 8))
    const top = rect.bottom + 8
    setTooltip({ cell, top, left })
  }, [])

  const handleMouseLeave = useCallback(() => {
    setTooltip(null)
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
            {tasks.map(task => (
              <tr key={task}>
                <td className="text-sm text-gray-300 p-2 font-medium">{task}</td>
                {models.map(model => {
                  const cell = cells.find(c => c.task === task && c.model === model)
                  const score = cell?.score
                  const isHovered = tooltip?.cell?.task === task && tooltip?.cell?.model === model
                  return (
                    <td key={model} className="p-1">
                      <div
                        className="cursor-pointer rounded-md h-12 flex items-center justify-center transition-all"
                        style={{
                          backgroundColor: scoreToColor(score),
                          opacity: isHovered ? 1 : 0.85,
                          transform: isHovered ? 'scale(1.05)' : 'scale(1)',
                        }}
                        onMouseEnter={(e) => cell && handleMouseEnter(e, cell)}
                        onMouseLeave={handleMouseLeave}
                      >
                        <span className="text-xs font-mono font-bold text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.8)]">
                          {score != null ? score.toFixed(2) : '—'}
                        </span>
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

      {/* Fixed-position tooltip rendered outside the table flow */}
      {tooltip && (
        <div
          className="fixed z-[9999] pointer-events-none"
          style={{ top: tooltip.top, left: tooltip.left }}
        >
          <TooltipContent data={tooltip.cell} />
        </div>
      )}

      <ELI5Panel
        dataSummary={cells.map(c => `${c.model} on ${c.task}: score=${c.score?.toFixed(2)}, latency=${c.latency?.toFixed(0)}ms, passes=${c.passes_threshold}`).join('\n')}
        promptHint="You are explaining a capability matrix heatmap to a non-technical engineer. Explain which models are strong and weak on which tasks. Call out any red cells (low scores) specifically and explain what that means for someone building a multi-step AI pipeline in production."
      />
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
