import { useState, useEffect } from 'react'
import ELI5Panel from '../components/ELI5Panel'
import { shortLabel } from '../lib/modelLabels'

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
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          True cost = call price + retry cost when it fails
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Cost Calculator</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          Cheap models that fail force expensive retries. This table shows the true expected cost of each
          (task, model) pair — including cascade-failure pricing — so you pick the option that's actually cheapest
          end-to-end. Cells marked <span className="font-semibold text-emerald-700">BEST</span> are the cost-optimal
          choice for that task.
        </p>
      </div>

      {/* Cost matrix table */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 overflow-x-auto mb-6 shadow-sm">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="text-left px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Task</th>
              {models.map(m => (
                <th key={m} className="text-center px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <span className="block truncate max-w-[100px]" title={m}>{shortLabel(m)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(task => (
              <tr key={task} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-3 text-slate-800 font-medium">{task}</td>
                {models.map(model => {
                  const cell = data.find(r => r.task === task && r.model === model)
                  if (!cell) return <td key={model} className="px-3 py-3 text-center text-slate-300">—</td>
                  const optimal = cell.is_cost_optimal
                  const passes = cell.passes_threshold
                  return (
                    <td key={model} className="px-3 py-3">
                      <div className={`text-center rounded-lg px-2 py-2 ${optimal ? 'bg-emerald-50 border border-emerald-300' : passes ? 'bg-slate-50 border border-slate-200' : 'bg-red-50 border border-red-200'}`}>
                        <div className={`font-mono text-sm font-semibold ${optimal ? 'text-emerald-700' : passes ? 'text-slate-800' : 'text-red-700'}`}>
                          {fmt$(cell.expected_cost_usd)}
                          {optimal && <span className="ml-1 text-[10px] text-emerald-700 font-bold tracking-wider">BEST</span>}
                        </div>
                        <div className="text-[11px] text-slate-500 mt-1">
                          score {cell.mean_score.toFixed(2)} · {cell.mean_latency_ms.toFixed(0)}ms
                        </div>
                        {!passes && (
                          <div className="text-[10px] text-red-600 mt-0.5">below threshold</div>
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
      <div className="bg-white border border-slate-200 rounded-xl p-6 mb-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">Cost Formula</h3>
        <code className="block text-xs text-indigo-700 bg-slate-100 border border-slate-200 rounded-lg p-3 font-mono leading-relaxed">
          expected_cost = (model_cost/token × mean_tokens) × P(success)<br />
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ retry_cost × P(failure) × cascade_depth
        </code>
        <p className="text-xs text-slate-500 mt-3">
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
  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading the cost matrix…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Computing expected cost per (model, task) pair: API price × tokens × P(success) + Haiku-fallback retry × P(failure).
        </div>
      </div>
    </div>
  )
}
function Err({ message }) {
  return <div className="flex items-center justify-center h-64"><div className="bg-red-50 border border-red-200 rounded-lg px-6 py-4 text-red-700 text-sm">Failed to load data: {message}</div></div>
}
function Empty() {
  return <div className="flex items-center justify-center h-64"><div className="bg-white border border-slate-200 rounded-lg px-6 py-4 text-slate-600 text-sm shadow-sm">No cost matrix data available.</div></div>
}
