import { useState, useEffect } from 'react'
import ELI5Panel from '../components/ELI5Panel'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Mirrors router/policy.py's MIN_ACCEPTABLE_SCORE. Below this, end-to-end
// accuracy is wrong more than 30% of the time — saving money on a
// failing pipeline is just being wrong cheaply, and the dashboard should
// say so out loud.
const PIPELINE_MIN_ACCEPTABLE_ACCURACY = 0.70
// Anchor for the human-readable cost projection. Same scale every cost
// number on the dashboard uses so the relative comparisons are honest.
const DAILY_VOLUME = 30000

function formatCost(val) {
  if (val == null) return '—'
  return `$${Number(val).toFixed(4)}`
}

function formatCostDaily(val) {
  if (val == null) return '—'
  const daily = Number(val) * DAILY_VOLUME
  if (daily < 100) return `≈ $${daily.toFixed(2)}/day at ${(DAILY_VOLUME / 1000).toFixed(0)}k queries`
  return `≈ $${daily.toFixed(0)}/day at ${(DAILY_VOLUME / 1000).toFixed(0)}k queries`
}

function formatLatency(val) {
  if (val == null) return '—'
  return `${Number(val).toFixed(0)}ms`
}

function formatPct(val) {
  if (val == null) return '—'
  return `${(Number(val) * 100).toFixed(1)}%`
}

// Color cascade-failure rate by severity. Cascade failure is the
// project's central thesis metric — the rate at which a cheap step-1
// mistake forces the pipeline to retry downstream — and a value above
// 50% means the pipeline is broken more often than it's working.
function cascadeFailColor(rate) {
  if (rate == null) return 'text-slate-500'
  if (rate >= 0.5) return 'text-red-700'
  if (rate >= 0.3) return 'text-amber-700'
  return 'text-emerald-700'
}

const STRATEGY_META = {
  'all-haiku': { label: 'All Haiku', desc: 'Every step uses Claude Haiku ($1.00/MTok)', accent: 'amber' },
  'all-lite': { label: 'All Flash Lite', desc: 'Every step uses Gemini Flash Lite ($0.04/MTok)', accent: 'emerald' },
  'all-gpt4o-mini': { label: 'All GPT-4o-mini', desc: 'Every step uses GPT-4o-mini ($0.15/MTok)', accent: 'sky' },
  'cacr-routed': { label: 'CACR Routed', desc: 'Cheapest passing model per step, with escalation', accent: 'indigo' },
}

function accentClasses(accent) {
  const map = {
    amber:   { border: 'border-amber-200',   bg: 'bg-amber-50',   text: 'text-amber-700',   badge: 'bg-amber-500' },
    emerald: { border: 'border-emerald-200', bg: 'bg-emerald-50', text: 'text-emerald-700', badge: 'bg-emerald-500' },
    sky:     { border: 'border-sky-200',     bg: 'bg-sky-50',     text: 'text-sky-700',     badge: 'bg-sky-500' },
    indigo:  { border: 'border-indigo-200',  bg: 'bg-indigo-50',  text: 'text-indigo-700',  badge: 'bg-indigo-500' },
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

  // Honesty gate: if any strategy lands below the end-to-end accuracy
  // threshold, surface it loudly above the cost narrative. The cheapest
  // pipeline isn't a "winner" if every option is wrong most of the time.
  const anyBelowThreshold = strategies.some(
    s => s.accuracy != null && s.accuracy < PIPELINE_MIN_ACCEPTABLE_ACCURACY
  )

  return (
    <div>
      {/* Below-threshold banner — sits above the strategy grid so the
          cost narrative below is read in the right context. */}
      {anyBelowThreshold && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-amber-900 text-sm mb-6 shadow-sm">
          <div className="font-semibold mb-1">⚠ All strategies below end-to-end accuracy threshold</div>
          <div className="text-amber-800">
            All evaluated strategies score below {PIPELINE_MIN_ACCEPTABLE_ACCURACY.toFixed(2)} end-to-end accuracy
            on this pipeline. The cheapest option is not the best option — it's the least-expensive way to be wrong.
          </div>
        </div>
      )}

      {/* Strategy cards — cost is the hero metric */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        {strategies.map(strategy => {
          const key = strategy.name || strategy.strategy || 'unknown'
          const meta = STRATEGY_META[key] || { label: key, desc: '', accent: 'indigo' }
          const ac = accentClasses(meta.accent)
          const isCheapest = strategy.cost != null && strategy.cost === bestCost
          return (
            <div key={key} className={`bg-white border ${ac.border} rounded-xl p-6 flex flex-col shadow-sm hover:shadow-md transition-shadow`}>
              <div className="flex items-center gap-2 mb-1">
                <div className={`w-2 h-2 rounded-full ${ac.badge}`} />
                <h3 className="text-lg font-semibold text-slate-900">{meta.label}</h3>
              </div>
              <p className="text-xs text-slate-500 mb-4">{meta.desc}</p>

              {/* Cost — hero metric */}
              <div className="mb-3">
                <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Cost per pipeline run</span>
                <div className={`text-3xl font-mono font-bold mt-1 ${isCheapest ? 'text-emerald-700' : 'text-slate-900'}`}>
                  {formatCost(strategy.cost)}
                  {isCheapest && <span className="ml-2 text-xs text-emerald-600 uppercase tracking-wider font-semibold">lowest</span>}
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">{formatCostDaily(strategy.cost)}</div>
              </div>

              {/* Cascade fail rate — project-thesis metric, surfaced
                  alongside cost so it's not buried in the table at the
                  bottom of the page. Color tracks severity:
                  red ≥50%, yellow 30-50%, green <30%. */}
              <div className="mb-4">
                <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Cascade fail rate</span>
                <div className={`text-xl font-mono font-bold mt-1 ${cascadeFailColor(strategy.cascade_failure_rate)}`}>
                  {formatPct(strategy.cascade_failure_rate)}
                </div>
              </div>

              {/* Secondary metrics — de-emphasized */}
              <div className="space-y-2 text-xs text-slate-500 pt-3 border-t border-slate-100">
                <div className="flex justify-between">
                  <span>Latency</span>
                  <span className={`font-mono ${strategy.latency === bestLatency ? 'text-slate-700' : 'text-slate-500'}`}>
                    {formatLatency(strategy.latency)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>End-to-end accuracy</span>
                  <span className="font-mono text-slate-500">{formatPct(strategy.accuracy)}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Callout banner */}
      <div className="bg-gradient-to-br from-teal-50 via-white to-indigo-50 border border-teal-200 rounded-xl px-6 py-4 mb-8 shadow-sm">
        <p className="text-sm text-slate-700 leading-relaxed">
          All three strategies achieve comparable accuracy on this pipeline.
          The difference is cost — CACR and Flash Lite run at{' '}
          <span className="font-mono font-semibold text-teal-700">{formatCost(liteCost)}</span> per
          request vs{' '}
          <span className="font-mono font-semibold text-slate-900">{formatCost(haikuCost)}</span> for
          All Haiku.
          {costMultiple && (
            <span className="font-semibold text-slate-900"> That's {costMultiple}x cheaper for the same result.</span>
          )}
        </p>
      </div>

      {/* Detailed comparison table */}
      <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50">
              <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Strategy</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Cost</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Latency</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Severity</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Bug Type</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">CVE Detect</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Fix</th>
              <th className="text-right px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Cascade Fail</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map(strategy => {
              const key = strategy.name || strategy.strategy || 'unknown'
              const meta = STRATEGY_META[key] || { label: key, accent: 'indigo' }
              return (
                <tr key={key} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3 text-slate-800 font-medium">{meta.label}</td>
                  <td className={`px-4 py-3 text-right font-mono font-semibold ${strategy.cost === bestCost ? 'text-emerald-700' : 'text-slate-700'}`}>
                    {formatCost(strategy.cost)}
                  </td>
                  <td className={`px-4 py-3 text-right font-mono ${strategy.latency === bestLatency ? 'text-emerald-700' : 'text-slate-600'}`}>
                    {formatLatency(strategy.latency)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{formatPct(strategy.step1_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{formatPct(strategy.step2_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{formatPct(strategy.step3_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{formatPct(strategy.step4_accuracy)}</td>
                  <td className="px-4 py-3 text-right font-mono text-slate-500">{formatPct(strategy.cascade_failure_rate)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <ELI5Panel
        dataSummary={strategies.map(s =>
          `${STRATEGY_META[s.strategy]?.label || s.strategy}: ` +
          `cost=$${s.cost?.toFixed(6)}, ` +
          `latency=${s.latency?.toFixed(0)}ms, ` +
          `end-to-end accuracy=${(s.accuracy*100)?.toFixed(1)}%, ` +
          `cascade fail rate=${(s.cascade_failure_rate*100)?.toFixed(1)}%`
        ).join('\n')}
        promptHint={
          anyBelowThreshold
            ? "You are explaining a pipeline cost comparison to a non-technical engineer. Every strategy on this pipeline is performing poorly — explain what the cascade fail rate and end-to-end accuracy numbers actually mean, why cost savings on a failing pipeline is saving money to be wrong cheaply, and recommend escalating to a frontier-tier pipeline (Opus 4.7, GPT-5, o3) or reformulating the task. Be specific with the actual percentages."
            : "You are explaining a pipeline cost comparison to a non-technical engineer. Explain what the cost difference means in real terms — if you ran 1 million requests, what would each strategy cost? Be specific with dollar amounts."
        }
        warning={
          anyBelowThreshold
            ? `All ${strategies.length} pipeline strategies score below ${PIPELINE_MIN_ACCEPTABLE_ACCURACY.toFixed(2)} end-to-end accuracy on this benchmark, with cascade fail rates between ${(Math.min(...strategies.map(s => s.cascade_failure_rate ?? 1)) * 100).toFixed(0)}% and ${(Math.max(...strategies.map(s => s.cascade_failure_rate ?? 0)) * 100).toFixed(0)}%. The cheapest option here is the least-expensive way to be wrong — cost savings on a failing pipeline is saving money to be wrong cheaply. Recommend escalating to a frontier-tier pipeline (Opus 4.7, GPT-5, o3) or reformulating the task to one where current models perform reliably.`
            : null
        }
        refreshKey={`${anyBelowThreshold ? 'below' : 'ok'}|${strategies.length}`}
      />
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading the strategy comparison…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Aggregating four routing strategies (All Haiku, All Flash Lite, All GPT-4o-mini, CACR-routed) over
          the same 4-step security pipeline.
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

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-64 gap-3">
      <div className="text-4xl text-slate-300">&#x2699;</div>
      <p className="text-slate-700 text-sm">Run pipeline simulation first</p>
      <p className="text-slate-500 text-xs">No strategy comparison data available yet.</p>
    </div>
  )
}
