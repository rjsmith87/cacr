import { useState, useEffect } from 'react'
import ELI5Panel from '../components/ELI5Panel'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function fmt$(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (n === 0) return '$0.00'
  // Always use fixed notation — find enough decimals to show 3 significant digits
  const decimals = Math.max(6, -Math.floor(Math.log10(Math.abs(n))) + 2)
  return `$${n.toFixed(Math.min(decimals, 10))}`
}

export default function CostModel() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/cost-matrix`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(raw => {
        const rows = (Array.isArray(raw) ? raw : []).map(r => ({
          ...r,
          expected_cost_usd: Number(r.expected_cost_usd || 0),
          mean_score: Number(r.mean_score || 0),
          cost_per_token: Number(r.cost_per_token || 0),
          mean_latency_ms: Number(r.mean_latency_ms || 0),
        }))
        setData(rows)
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  if (loading) return <Loader />
  if (error) return <Err message={error} />
  if (!data || data.length === 0) return <Empty />

  const tasks = [...new Set(data.map(r => r.task))]
  const models = [...new Set(data.map(r => r.model))]

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Cascade Cost Model</h2>
        <p className="text-gray-400 mt-1">
          Expected cost per (task, model) pair including cascade failure retry pricing.
          Starred cells are the cost-optimal choice for each task.
        </p>
      </div>

      {/* Cost matrix table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 overflow-x-auto mb-6">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="text-left px-3 py-2 text-gray-400 font-medium">Task</th>
              {models.map(m => (
                <th key={m} className="text-center px-3 py-2 text-gray-400 font-medium">
                  <span className="block truncate max-w-[130px]" title={m}>{m}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(task => (
              <tr key={task} className="border-b border-gray-800/50">
                <td className="px-3 py-3 text-gray-300 font-medium">{task}</td>
                {models.map(model => {
                  const cell = data.find(r => r.task === task && r.model === model)
                  if (!cell) return <td key={model} className="px-3 py-3 text-center text-gray-600">—</td>
                  const optimal = cell.is_cost_optimal
                  const passes = cell.passes_threshold
                  return (
                    <td key={model} className="px-3 py-3">
                      <div className={`text-center rounded-lg px-2 py-2 ${optimal ? 'bg-emerald-500/10 border border-emerald-500/30' : passes ? 'bg-gray-800/50' : 'bg-red-950/30 border border-red-800/20'}`}>
                        <div className={`font-mono text-sm font-semibold ${optimal ? 'text-emerald-400' : passes ? 'text-gray-200' : 'text-red-400'}`}>
                          {fmt$(cell.expected_cost_usd)}
                          {optimal && <span className="ml-1 text-[10px] text-emerald-500">BEST</span>}
                        </div>
                        <div className="text-[11px] text-gray-500 mt-1">
                          score {cell.mean_score.toFixed(2)} · {cell.mean_latency_ms.toFixed(0)}ms
                        </div>
                        {!passes && (
                          <div className="text-[10px] text-red-500 mt-0.5">below threshold</div>
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Formula explanation */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-3">Cost Formula</h3>
        <code className="block text-xs text-indigo-300 bg-gray-950 rounded-lg p-3 font-mono leading-relaxed">
          expected_cost = (model_cost/token × mean_tokens) × P(success)<br />
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ retry_cost × P(failure) × cascade_depth
        </code>
        <p className="text-xs text-gray-500 mt-3">
          cascade_depth = 3 (pipeline length) · retry_cost = one Haiku call as fallback ·
          P(success) = mean_score from benchmark · mean_tokens ≈ 230
        </p>
      </div>

      <ELI5Panel
        dataSummary={data.filter(r => r.is_cost_optimal).map(r =>
          `${r.task}: optimal=${r.model}, cost=${fmt$(r.expected_cost_usd)}, score=${r.mean_score.toFixed(2)}`
        ).join('\n') + '\n\nAll entries:\n' + data.map(r =>
          `${r.model} on ${r.task}: cost=${fmt$(r.expected_cost_usd)}, score=${r.mean_score.toFixed(2)}, passes=${r.passes_threshold}`
        ).join('\n')}
        promptHint="You are explaining a cascade cost model to a non-technical engineer. Explain what 'expected cost including cascade failure' means in plain terms — why a cheap model that fails sometimes can cost more than a slightly more expensive one that always succeeds. Point out which model is cost-optimal for each task and why."
      />
    </div>
  )
}

function Loader() {
  return <div className="flex items-center justify-center h-64"><div className="animate-pulse text-gray-500 text-sm">Loading cost model...</div></div>
}
function Err({ message }) {
  return <div className="flex items-center justify-center h-64"><div className="bg-red-950/50 border border-red-800 rounded-lg px-6 py-4 text-red-400 text-sm">Failed to load data: {message}</div></div>
}
function Empty() {
  return <div className="flex items-center justify-center h-64"><div className="bg-gray-900 border border-gray-800 rounded-lg px-6 py-4 text-gray-400 text-sm">No cost matrix data available.</div></div>
}
