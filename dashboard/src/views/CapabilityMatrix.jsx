import { useState, useEffect, useCallback, useMemo } from 'react'
import ELI5Panel from '../components/ELI5Panel'
import ModelEfficiency from './ModelEfficiency'
import { shortLabel } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function scoreToColor(score) {
  if (score == null) return '#F1F5F9'
  const clamped = Math.max(0, Math.min(1, score))
  const r = Math.round(clamped < 0.5 ? 220 : 220 - (clamped - 0.5) * 2 * 180)
  const g = Math.round(clamped < 0.5 ? clamped * 2 * 180 : 180)
  const b = Math.round(40)
  return `rgb(${r}, ${g}, ${b})`
}

function TooltipContent({ data }) {
  if (!data) return null
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl text-sm min-w-max">
      <p className="font-semibold text-white mb-1">{data.model} / {data.task}</p>
      <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5 text-slate-200 whitespace-nowrap">
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
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          8 models · 3 tasks · 30 trials each
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Which Model Wins What</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          Every model isn't great at every task. This heatmap shows where Haiku beats GPT-5, where Flash Lite is enough,
          and which (model, task) combinations underperform — measured across the same 360 benchmark trials the router
          uses to make its routing decisions. Hover any cell for the full numbers.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 overflow-x-auto shadow-sm">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500 p-2 min-w-[140px]">Task</th>
              {models.map(model => (
                <th key={model} className="text-center text-xs font-semibold uppercase tracking-wider text-slate-500 p-2 min-w-[80px]">
                  <span className="block truncate max-w-[100px]" title={model}>{shortLabel(model)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(task => (
              <tr key={task}>
                <td className="text-sm text-slate-800 p-2 font-medium">{task}</td>
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
                          boxShadow: isHovered ? '0 4px 12px rgba(15, 23, 42, 0.12)' : 'none',
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

        <div className="flex items-center justify-center gap-2 mt-6 text-xs text-slate-500">
          <span className="font-mono">0.0</span>
          <div className="flex h-3 w-48 rounded overflow-hidden border border-slate-200">
            {Array.from({ length: 20 }, (_, i) => (
              <div key={i} className="flex-1" style={{ backgroundColor: scoreToColor(i / 19) }} />
            ))}
          </div>
          <span className="font-mono">1.0</span>
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

      {/* ── Cost-Normalized Efficiency ──────────────────────────────────
          Folded in from the former "Efficiency Ratios" tab. Same charts,
          same data, same ELI5 — just one tab now. The matrix above answers
          "which model is most accurate?"; this section answers "which model
          is most accurate per dollar?" */}
      <section className="mt-12 pt-8 border-t border-slate-200">
        <div className="mb-6">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-indigo-600 font-semibold mb-2">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-500" />
            Score ÷ Cost
          </div>
          <h3 className="text-2xl font-bold text-slate-900 tracking-tight">Cost-Normalized Efficiency</h3>
          <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
            The same models from the matrix above, divided by expected cost. Higher bars = more value per dollar.
            Useful when you have a fixed budget per request and want the most accuracy your money can buy.
          </p>
        </div>
        <ModelEfficiency />
      </section>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading the benchmark heatmap…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Pulling 360 trial results — 8 models × 3 tasks × 30 trials — and grading them on a 0-to-1 score.
        </div>
      </div>
    </div>
  )
}

function ErrorState({ message }) {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="bg-red-50 border border-red-200 rounded-lg px-6 py-4 text-red-700 text-sm">
        Failed to load data: {message}
      </div>
    </div>
  )
}
