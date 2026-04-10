import { useState, useEffect } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function formatCost(val) {
  if (val == null) return '—'
  return `$${Number(val).toFixed(4)}`
}

function formatLatency(val) {
  if (val == null) return '—'
  return `${Number(val).toFixed(0)}ms`
}

function formatPct(val) {
  if (val == null) return '—'
  return `${(Number(val) * 100).toFixed(1)}%`
}

const STRATEGY_META = {
  'all-haiku': { label: 'All Haiku', desc: 'Every request routed to Claude Haiku', accent: 'amber' },
  'all-lite': { label: 'All Flash Lite', desc: 'Every request routed to Gemini Flash Lite', accent: 'emerald' },
  'cacr-routed': { label: 'CACR Routed', desc: 'Cascade-aware confidence routing', accent: 'indigo' },
}

function accentClasses(accent) {
  const map = {
    amber: { border: 'border-amber-500/30', bg: 'bg-amber-500/10', text: 'text-amber-400', badge: 'bg-amber-500' },
    emerald: { border: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-400', badge: 'bg-emerald-500' },
    indigo: { border: 'border-indigo-500/30', bg: 'bg-indigo-500/10', text: 'text-indigo-400', badge: 'bg-indigo-500' },
  }
  return map[accent] || map.indigo
}

export default function PipelineCost() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/pipeline-cost`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(raw => {
        // API returns: {strategy, total_cost_usd, mean_latency_ms,
        //   step1_accuracy, step2_accuracy, step3_accuracy, cascade_failure_rate, n}
        // Frontend expects: {strategy, cost, latency, accuracy}
        const rows = Array.isArray(raw) ? raw : raw?.strategies || []
        const mapped = rows.map(r => ({
          strategy: r.strategy,
          cost: r.total_cost_usd,
          latency: r.mean_latency_ms,
          accuracy: r.step3_accuracy,
          step1_accuracy: r.step1_accuracy,
          step2_accuracy: r.step2_accuracy,
          cascade_failure_rate: r.cascade_failure_rate,
          n: r.n,
        }))
        setData(mapped)
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />

  const strategies = Array.isArray(data) ? data : []
  if (strategies.length === 0) {
    return <EmptyState />
  }

  // Find best values for highlighting
  const bestCost = Math.min(...strategies.map(s => s.cost ?? Infinity))
  const bestLatency = Math.min(...strategies.map(s => s.latency ?? Infinity))
  const bestAccuracy = Math.max(...strategies.map(s => s.accuracy ?? -Infinity))

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Pipeline Cost Comparison</h2>
        <p className="text-gray-400 mt-1">Side-by-side comparison of routing strategies on cost, latency, and accuracy.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {strategies.map(strategy => {
          const key = strategy.name || strategy.strategy || 'unknown'
          const meta = STRATEGY_META[key] || { label: key, desc: '', accent: 'indigo' }
          const ac = accentClasses(meta.accent)
          return (
            <div key={key} className={`bg-gray-900 border ${ac.border} rounded-xl p-6 flex flex-col`}>
              <div className="flex items-center gap-2 mb-1">
                <div className={`w-2 h-2 rounded-full ${ac.badge}`} />
                <h3 className="text-lg font-semibold text-white">{meta.label}</h3>
              </div>
              <p className="text-xs text-gray-500 mb-5">{meta.desc}</p>

              <div className="space-y-4 flex-1">
                <MetricRow
                  label="Cost per request"
                  value={formatCost(strategy.cost)}
                  isBest={strategy.cost != null && strategy.cost === bestCost}
                />
                <MetricRow
                  label="Avg latency"
                  value={formatLatency(strategy.latency)}
                  isBest={strategy.latency != null && strategy.latency === bestLatency}
                />
                <MetricRow
                  label="Accuracy"
                  value={formatPct(strategy.accuracy)}
                  isBest={strategy.accuracy != null && strategy.accuracy === bestAccuracy}
                />
                {strategy.step1_accuracy != null && (
                  <div className="pt-2 border-t border-gray-800 space-y-2">
                    <MetricRow label="Step 1 (severity)" value={formatPct(strategy.step1_accuracy)} />
                    <MetricRow label="Step 2 (bug type)" value={formatPct(strategy.step2_accuracy)} />
                    <MetricRow label="Cascade failures" value={formatPct(strategy.cascade_failure_rate)} />
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Comparison table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-4 py-3 text-gray-400 font-medium">Strategy</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Cost</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Latency</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Step 1</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Step 2</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Step 3</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Cascade Fail</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map(strategy => {
              const key = strategy.name || strategy.strategy || 'unknown'
              const meta = STRATEGY_META[key] || { label: key, accent: 'indigo' }
              return (
                <tr key={key} className="border-b border-gray-800/50 last:border-0">
                  <td className="px-4 py-3 text-gray-200 font-medium">{meta.label}</td>
                  <td className={`px-4 py-3 text-right font-mono ${strategy.cost === bestCost ? 'text-emerald-400' : 'text-gray-300'}`}>
                    {formatCost(strategy.cost)}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono ${strategy.latency === bestLatency ? 'text-emerald-400' : 'text-gray-300'}`}>
                    {formatLatency(strategy.latency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-300">{formatPct(strategy.step1_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-300">{formatPct(strategy.step2_accuracy)}</td>
                  <td className={`px-4 py-3 text-right font-mono ${strategy.accuracy === bestAccuracy ? 'text-emerald-400' : 'text-gray-300'}`}>
                    {formatPct(strategy.accuracy)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-red-400">{formatPct(strategy.cascade_failure_rate)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MetricRow({ label, value, isBest }) {
  return (
    <div className="flex justify-between items-baseline">
      <span className="text-sm text-gray-400">{label}</span>
      <span className={`font-mono text-sm ${isBest ? 'text-emerald-400 font-semibold' : 'text-gray-200'}`}>
        {value}
        {isBest && <span className="ml-1.5 text-[10px] text-emerald-500 uppercase tracking-wider">best</span>}
      </span>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-pulse text-gray-500 text-sm">Loading pipeline cost data...</div>
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

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-64 gap-3">
      <div className="text-4xl text-gray-700">&#x2699;</div>
      <p className="text-gray-400 text-sm">Run pipeline simulation first</p>
      <p className="text-gray-600 text-xs">No strategy comparison data available yet.</p>
    </div>
  )
}
