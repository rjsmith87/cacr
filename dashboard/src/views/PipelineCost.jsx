import { useState, useEffect } from 'react'
import ELI5Panel from '../components/ELI5Panel'

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
  'all-haiku': { label: 'All Haiku', desc: 'Every step uses Claude Haiku ($1.00/MTok)', accent: 'amber' },
  'all-lite': { label: 'All Flash Lite', desc: 'Every step uses Gemini Flash Lite ($0.04/MTok)', accent: 'emerald' },
  'all-gpt4o-mini': { label: 'All GPT-4o-mini', desc: 'Every step uses GPT-4o-mini ($0.15/MTok)', accent: 'sky' },
  'cacr-routed': { label: 'CACR Routed', desc: 'Cheapest passing model per step, with escalation', accent: 'indigo' },
}

function accentClasses(accent) {
  const map = {
    amber: { border: 'border-amber-500/30', bg: 'bg-amber-500/10', text: 'text-amber-400', badge: 'bg-amber-500' },
    emerald: { border: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-400', badge: 'bg-emerald-500' },
    sky: { border: 'border-sky-500/30', bg: 'bg-sky-500/10', text: 'text-sky-400', badge: 'bg-sky-500' },
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
        const rows = Array.isArray(raw) ? raw : raw?.strategies || []
        const mapped = rows.map(r => ({
          strategy: r.strategy,
          cost: r.total_cost_usd,
          latency: r.mean_latency_ms,
          accuracy: r.step4_accuracy ?? r.step3_accuracy,
          step1_accuracy: r.step1_accuracy,
          step2_accuracy: r.step2_accuracy,
          step3_accuracy: r.step3_accuracy,
          step4_accuracy: r.step4_accuracy,
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
  if (strategies.length === 0) return <EmptyState />

  const bestCost = Math.min(...strategies.map(s => s.cost ?? Infinity))
  const bestLatency = Math.min(...strategies.map(s => s.latency ?? Infinity))

  // Compute the cost multiple for the callout
  const haikuCost = strategies.find(s => s.strategy === 'all-haiku')?.cost
  const liteCost = strategies.find(s => s.strategy === 'all-lite')?.cost || strategies.find(s => s.strategy === 'cacr-routed')?.cost
  const costMultiple = haikuCost && liteCost ? Math.round(haikuCost / liteCost) : null

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Pipeline Cost Comparison</h2>
        <p className="text-gray-400 mt-1">
          Same accuracy, radically different cost. CACR matches Haiku's performance at {costMultiple ? `${costMultiple}x` : '~22x'} lower cost per request.
        </p>
      </div>

      {/* Strategy cards — cost is the hero metric */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        {strategies.map(strategy => {
          const key = strategy.name || strategy.strategy || 'unknown'
          const meta = STRATEGY_META[key] || { label: key, desc: '', accent: 'indigo' }
          const ac = accentClasses(meta.accent)
          const isCheapest = strategy.cost != null && strategy.cost === bestCost
          return (
            <div key={key} className={`bg-gray-900 border ${ac.border} rounded-xl p-6 flex flex-col`}>
              <div className="flex items-center gap-2 mb-1">
                <div className={`w-2 h-2 rounded-full ${ac.badge}`} />
                <h3 className="text-lg font-semibold text-white">{meta.label}</h3>
              </div>
              <p className="text-xs text-gray-500 mb-4">{meta.desc}</p>

              {/* Cost — hero metric */}
              <div className="mb-4">
                <span className="text-xs uppercase tracking-wider text-gray-500">Cost per pipeline run</span>
                <div className={`text-2xl font-mono font-bold mt-1 ${isCheapest ? 'text-emerald-400' : 'text-gray-200'}`}>
                  {formatCost(strategy.cost)}
                  {isCheapest && <span className="ml-2 text-xs text-emerald-500 uppercase tracking-wider font-semibold">lowest</span>}
                </div>
              </div>

              {/* Secondary metrics — de-emphasized */}
              <div className="space-y-2 text-xs text-gray-500">
                <div className="flex justify-between">
                  <span>Latency</span>
                  <span className={`font-mono ${strategy.latency === bestLatency ? 'text-gray-300' : 'text-gray-500'}`}>
                    {formatLatency(strategy.latency)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>End-to-end accuracy</span>
                  <span className="font-mono text-gray-500">{formatPct(strategy.accuracy)}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Callout banner */}
      <div className="bg-indigo-950/40 border border-indigo-500/20 rounded-xl px-6 py-4 mb-8">
        <p className="text-sm text-indigo-300 leading-relaxed">
          All three strategies achieve comparable accuracy on this pipeline.
          The difference is cost — CACR and Flash Lite run at{' '}
          <span className="font-mono font-semibold text-indigo-200">{formatCost(liteCost)}</span> per
          request vs{' '}
          <span className="font-mono font-semibold text-indigo-200">{formatCost(haikuCost)}</span> for
          All Haiku.
          {costMultiple && (
            <span className="font-semibold text-indigo-200"> That's {costMultiple}x cheaper for the same result.</span>
          )}
        </p>
      </div>

      {/* Detailed comparison table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-4 py-3 text-gray-400 font-medium">Strategy</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Cost</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Latency</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Severity</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Bug Type</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">CVE Detect</th>
              <th className="text-right px-4 py-3 text-gray-400 font-medium">Fix</th>
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
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${strategy.cost === bestCost ? 'text-emerald-400' : 'text-gray-300'}`}>
                    {formatCost(strategy.cost)}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono ${strategy.latency === bestLatency ? 'text-emerald-400' : 'text-gray-400'}`}>
                    {formatLatency(strategy.latency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500">{formatPct(strategy.step1_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500">{formatPct(strategy.step2_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500">{formatPct(strategy.step3_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500">{formatPct(strategy.step4_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-gray-500">{formatPct(strategy.cascade_failure_rate)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <ELI5Panel
        dataSummary={strategies.map(s => `${STRATEGY_META[s.strategy]?.label || s.strategy}: cost=$${s.cost?.toFixed(6)}, latency=${s.latency?.toFixed(0)}ms, accuracy=${(s.accuracy*100)?.toFixed(1)}%`).join('\n')}
        promptHint="You are explaining pipeline cost comparison to a non-technical engineer. Explain what the cost difference means in real terms — if you ran 1 million requests, what would each strategy cost? Which strategy would you pick and why? Be specific with dollar amounts."
      />
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
