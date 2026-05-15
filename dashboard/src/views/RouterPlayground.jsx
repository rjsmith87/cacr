import { useEffect, useMemo, useState } from 'react'
import ELI5Panel from '../components/ELI5Panel'
import { modelColor, shortLabel } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Mirrors router/policy.py — the global accuracy floor a model must
// clear before the router will recommend it without a warning.
const MIN_ACCEPTABLE_SCORE = 0.70

const TASK_LABELS = {
  CodeReview: 'Code Review',
  SecurityVuln: 'Security Vuln',
  CodeSummarization: 'Code Summary',
}

function fmt$(v) {
  if (v == null || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (n === 0) return '$0'
  const abs = Math.abs(n)
  if (abs >= 1000) return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
  if (abs >= 100) return `$${n.toFixed(0)}`
  if (abs >= 1) return `$${n.toFixed(2)}`
  if (abs >= 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(6)}`
}

function fmtScore(v) {
  if (v == null || Number.isNaN(v)) return '—'
  return Number(v).toFixed(2)
}

export default function CostOfBadRouting() {
  const [matrix, setMatrix] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [monthlyVolume, setMonthlyVolume] = useState(10000)

  useEffect(() => {
    fetch(`${API}/api/cost-matrix`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(raw => {
        const rows = (Array.isArray(raw) ? raw : []).map(r => ({
          ...r,
          mean_score: Number(r.mean_score || 0),
          expected_cost_usd: Number(r.expected_cost_usd || 0),
          cost_per_token: Number(r.cost_per_token || 0),
        }))
        setMatrix(rows)
      })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const analysis = useMemo(() => {
    if (!matrix || matrix.length === 0) return null

    const tasks = [...new Set(matrix.map(r => r.task))].sort()
    const models = [...new Set(matrix.map(r => r.model))]
    const perTaskVolume = monthlyVolume / tasks.length

    const buildStrategy = (label, picks, kind, model = null) => {
      const taskCosts = {}
      const taskScores = {}
      let total = 0
      let scoreSum = 0
      let passing = 0
      picks.forEach(({ task, row }) => {
        const cost = (row?.expected_cost_usd || 0) * perTaskVolume
        taskCosts[task] = cost
        taskScores[task] = row?.mean_score ?? null
        total += cost
        scoreSum += row?.mean_score || 0
        if (row && row.mean_score >= MIN_ACCEPTABLE_SCORE) passing += 1
      })
      return {
        kind,
        label,
        model,
        total,
        meanScore: scoreSum / Math.max(1, tasks.length),
        taskCosts,
        taskScores,
        picks,
        passingTasks: passing,
        taskCount: tasks.length,
      }
    }

    const naiveStrategies = models.map(m => {
      const picks = tasks.map(t => ({
        task: t,
        row: matrix.find(r => r.task === t && r.model === m),
      }))
      return buildStrategy(`Always ${shortLabel(m)}`, picks, 'naive', m)
    })

    // CACR routing: per task pick the cheapest passing model (>= 0.70);
    // if nothing passes, pick the best-available (highest mean_score)
    // and inherit a below-threshold flag for that task.
    const cacrPicks = tasks.map(t => {
      const rows = matrix.filter(r => r.task === t)
      const passing = rows.filter(r => r.mean_score >= MIN_ACCEPTABLE_SCORE)
      const row = passing.length
        ? passing.reduce((best, r) => r.expected_cost_usd < best.expected_cost_usd ? r : best)
        : rows.reduce((best, r) => r.mean_score > best.mean_score ? r : best, rows[0])
      return { task: t, row, passing: passing.length > 0 }
    })
    const cacrStrategy = buildStrategy('CACR routing', cacrPicks, 'cacr')

    const allStrategies = [...naiveStrategies, cacrStrategy].sort((a, b) => a.total - b.total)
    const cheapestNaive = naiveStrategies.reduce((best, s) => s.total < best.total ? s : best)
    const mostExpensiveNaive = naiveStrategies.reduce((worst, s) => s.total > worst.total ? s : worst)

    // Dominated-strategy detector: any naive strategy where another
    // naive strategy is BOTH cheaper AND scores higher. Rational actor
    // would never pick a dominated option. Surfaces the classic
    // cheap-trap: a per-token-cheap model that fails so often the
    // cascade-retry cost pushes its total above a more capable model.
    const dominated = naiveStrategies
      .map(s => {
        const dominator = naiveStrategies.find(other =>
          other !== s && other.total < s.total && other.meanScore > s.meanScore
        )
        return dominator ? { strategy: s, dominator } : null
      })
      .filter(Boolean)
      .sort((a, b) => b.strategy.total - a.strategy.total)

    return {
      tasks, models, perTaskVolume,
      strategies: allStrategies,
      naiveStrategies,
      cacr: cacrStrategy,
      cheapestNaive,
      mostExpensiveNaive,
      dominated,
    }
  }, [matrix, monthlyVolume])

  if (loading) return <Loader />
  if (error) return <ErrorView message={error} />
  if (!analysis) return <EmptyView />

  const { tasks, strategies, cacr, cheapestNaive, mostExpensiveNaive, dominated } = analysis

  const cacrVsMostExpensive = mostExpensiveNaive.total - cacr.total
  const cacrVsCheapest = cacr.total - cheapestNaive.total

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          Original thesis · Cascade failure pricing
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Cost of Bad Routing</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          What does it cost when you don't route intelligently? Static per-token pricing
          hides the real bill: when a model fails, cascade retries compound the cost. A
          cheap-and-unreliable model can end up more expensive than smart routing — and
          a few dominated strategies are strictly worse than CACR's pick on every axis.
          This view rolls per-call expected cost up to a monthly total at your volume so
          you can see the price of never routing.
        </p>
      </div>

      {/* Volume control */}
      <div className="mb-6 bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-baseline justify-between mb-2">
          <label className="text-sm font-medium text-slate-700">
            Monthly task volume
          </label>
          <div className="text-sm text-slate-500">
            <span className="font-mono font-bold text-slate-900">{monthlyVolume.toLocaleString()}</span>{' '}
            tasks · ~<span className="font-mono">{Math.round(monthlyVolume / tasks.length).toLocaleString()}</span> per task type
          </div>
        </div>
        <input
          type="range"
          min={100}
          max={1000000}
          step={100}
          value={monthlyVolume}
          onChange={(e) => setMonthlyVolume(Number(e.target.value))}
          className="w-full accent-teal-600"
        />
        <div className="flex justify-between text-xs text-slate-500 mt-1">
          <span>100</span>
          <span>10K</span>
          <span>100K</span>
          <span>1M</span>
        </div>
        <p className="text-xs text-slate-500 mt-3 leading-relaxed">
          Volume is split evenly across the {tasks.length} benchmark task types. Real workloads
          are skewed; the absolute dollar amounts will rescale linearly but the strategy
          ordering and the size of the spread are what matter.
        </p>
      </div>

      {/* Spotlight cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <SpotlightCard
          title="Most expensive naive"
          subtitle="Send every task to this one model"
          strategy={mostExpensiveNaive}
          accent="red"
        />
        <SpotlightCard
          title="Cheapest naive"
          subtitle="Send every task to this one model"
          strategy={cheapestNaive}
          accent="amber"
        />
        <SpotlightCard
          title="CACR routing"
          subtitle="Per-task cost-optimal pick"
          strategy={cacr}
          accent="teal"
        />
      </div>

      {/* Headline comparison */}
      <div className="mb-6 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
            CACR vs always-most-expensive
          </div>
          <div className="text-3xl font-mono font-bold text-emerald-700">
            {fmt$(cacrVsMostExpensive)}<span className="text-sm text-slate-500 font-sans"> saved / mo</span>
          </div>
          <p className="text-xs text-slate-600 mt-2 leading-relaxed">
            CACR scores <span className="font-mono">{fmtScore(cacr.meanScore)}</span> avg vs
            {' '}<span className="font-mono">{fmtScore(mostExpensiveNaive.meanScore)}</span> for
            {' '}{mostExpensiveNaive.label} — almost the same quality at a fraction of the price.
          </p>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2">
            CACR vs always-cheapest
          </div>
          <div className="text-3xl font-mono font-bold text-slate-900">
            {cacrVsCheapest >= 0 ? '+' : '-'}{fmt$(Math.abs(cacrVsCheapest))}
            <span className="text-sm text-slate-500 font-sans"> / mo</span>
          </div>
          <p className="text-xs text-slate-600 mt-2 leading-relaxed">
            CACR passes the 0.70 floor on <span className="font-mono">{cacr.passingTasks}/{cacr.taskCount}</span> tasks vs
            {' '}<span className="font-mono">{cheapestNaive.passingTasks}/{cheapestNaive.taskCount}</span> for
            {' '}{cheapestNaive.label}. The premium buys quality coverage, not just headline accuracy.
          </p>
        </div>
      </div>

      {/* Dominated strategies (cheap-trap callout) */}
      {dominated.length > 0 && (
        <div className="mb-6 bg-indigo-50 border border-indigo-200 rounded-xl p-5 text-sm text-indigo-900">
          <div className="font-bold mb-2">The cheap trap — dominated strategies</div>
          <p className="leading-relaxed mb-2">
            {dominated.length === 1 ? 'One naive strategy is' : `${dominated.length} naive strategies are`} strictly dominated:
            another model is BOTH cheaper AND higher-scoring across the board. No reason to ever pick these.
          </p>
          <ul className="space-y-1.5">
            {dominated.slice(0, 3).map(({ strategy, dominator }) => (
              <li key={strategy.label} className="text-xs">
                <span className="font-mono font-semibold">{strategy.label}</span>{' '}
                ({fmt$(strategy.total)}/mo, score {fmtScore(strategy.meanScore)})
                {' '}is dominated by{' '}
                <span className="font-mono font-semibold">{dominator.label}</span>{' '}
                ({fmt$(dominator.total)}/mo, score {fmtScore(dominator.meanScore)})
                {' '}— {fmt$(strategy.total - dominator.total)} cheaper and{' '}
                +{(dominator.meanScore - strategy.meanScore).toFixed(2)} accuracy.
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Strategy table */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 overflow-x-auto mb-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">
          All strategies, sorted cheapest first
        </h3>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-slate-200">
              <th className="text-left px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Strategy</th>
              {tasks.map(t => (
                <th key={t} className="text-right px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
                  {TASK_LABELS[t] || t}
                </th>
              ))}
              <th className="text-right px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Total / mo</th>
              <th className="text-right px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Avg score</th>
              <th className="text-center px-3 py-2 text-xs font-semibold uppercase tracking-wider text-slate-500">≥0.7</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => {
              const isCacr = s.kind === 'cacr'
              const rowCls = isCacr
                ? 'bg-teal-50 border-y-2 border-teal-300'
                : ''
              return (
                <tr key={`${s.kind}-${s.label}`} className={`border-b border-slate-100 last:border-0 ${rowCls}`}>
                  <td className="px-3 py-3 text-slate-800">
                    <div className="flex items-center gap-2">
                      {s.model && (
                        <span
                          className="inline-block w-2 h-2 rounded-full shrink-0"
                          style={{ background: modelColor(s.model) }}
                          aria-hidden="true"
                        />
                      )}
                      {isCacr && (
                        <span className="text-[10px] bg-teal-600 text-white rounded-full px-2 py-0.5 font-semibold uppercase tracking-wider">
                          smart
                        </span>
                      )}
                      <span className={isCacr ? 'font-bold text-teal-900' : 'font-medium'}>{s.label}</span>
                    </div>
                  </td>
                  {tasks.map(t => (
                    <td key={t} className="px-3 py-3 text-right">
                      <div className="font-mono text-slate-700">{fmt$(s.taskCosts[t])}</div>
                      <div className={`text-[10px] font-mono mt-0.5 ${(s.taskScores[t] ?? 0) >= MIN_ACCEPTABLE_SCORE ? 'text-emerald-600' : 'text-red-500'}`}>
                        score {fmtScore(s.taskScores[t])}
                      </div>
                    </td>
                  ))}
                  <td className={`px-3 py-3 text-right font-mono font-bold ${isCacr ? 'text-teal-700' : 'text-slate-900'}`}>
                    {fmt$(s.total)}
                  </td>
                  <td className="px-3 py-3 text-right font-mono text-slate-700">
                    {fmtScore(s.meanScore)}
                  </td>
                  <td className="px-3 py-3 text-center text-xs">
                    <span className={`font-mono ${s.passingTasks === s.taskCount ? 'text-emerald-700 font-semibold' : s.passingTasks === 0 ? 'text-red-700' : 'text-amber-700'}`}>
                      {s.passingTasks}/{s.taskCount}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-slate-500 leading-relaxed">
          Per-task scores below 0.70 are shown in red. CACR routing's "≥0.7" count is the number of tasks where
          a model actually exists that clears the global floor — when nothing exists (e.g. Code Summary on this
          dataset) CACR returns best-available with a below-threshold warning rather than silently picking a
          sub-floor model.
        </p>
      </div>

      {/* Formula */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 mb-6 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wider mb-3">
          The expected cost formula
        </h3>
        <code className="block text-xs text-indigo-700 bg-slate-100 border border-slate-200 rounded-lg p-3 font-mono leading-relaxed">
          expected_cost = (cost_per_token × mean_tokens) × P(success)<br />
          &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ retry_cost × P(failure) × cascade_depth
        </code>
        <p className="text-xs text-slate-500 mt-3 leading-relaxed">
          P(failure) = 1 − mean_score. cascade_depth = 3 (one pipeline run). retry_cost = one Haiku
          fallback call. A model with 40% accuracy on a task pays the retry cost 60% of the time, three
          times over — which is why the model with the lowest sticker price often isn't the cheapest
          when you bake in failure pricing.
        </p>
      </div>

      <ELI5Panel
        dataSummary={[
          `Monthly volume: ${monthlyVolume} tasks, split across ${tasks.length} task types (${tasks.join(', ')}).`,
          `CACR routing: ${fmt$(cacr.total)}/mo, avg score ${fmtScore(cacr.meanScore)}, passes 0.70 floor on ${cacr.passingTasks}/${cacr.taskCount} tasks.`,
          `Cheapest naive (${cheapestNaive.label}): ${fmt$(cheapestNaive.total)}/mo, avg score ${fmtScore(cheapestNaive.meanScore)}, passes on ${cheapestNaive.passingTasks}/${cheapestNaive.taskCount} tasks.`,
          `Most expensive naive (${mostExpensiveNaive.label}): ${fmt$(mostExpensiveNaive.total)}/mo, avg score ${fmtScore(mostExpensiveNaive.meanScore)}, passes on ${mostExpensiveNaive.passingTasks}/${mostExpensiveNaive.taskCount} tasks.`,
          dominated.length > 0
            ? `Dominated strategies (worse than another on every axis): ${dominated.map(d => d.strategy.label).join(', ')}.`
            : 'No strictly dominated strategies at this volume.',
        ].join('\n')}
        promptHint="You are explaining cascade-aware routing economics to a non-technical engineer. In plain English, describe what 'cost of bad routing' means: per-token sticker price is misleading because a model that fails forces retry costs that compound. Compare CACR's total to the cheapest-naive and most-expensive-naive totals — quote the actual dollar amounts and accuracy numbers. Call out any dominated strategies if present. Do not use marketing phrases like 'best of both worlds', 'smart trade-off', or 'good value' — describe what the numbers show and let the reader judge."
        warning={cacr.passingTasks < cacr.taskCount
          ? `CACR routing still falls below the 0.70 accuracy floor on ${cacr.taskCount - cacr.passingTasks} of ${cacr.taskCount} task type(s) because no model in the benchmark passes the floor for those tasks. The dollar comparison here is an economic spread, not a quality endorsement.`
          : undefined}
        refreshKey={`cobr|vol=${monthlyVolume}|cacr=${cacr.total.toFixed(2)}`}
      />
    </div>
  )
}

function SpotlightCard({ title, subtitle, strategy, accent }) {
  const accentMap = {
    red: { border: 'border-red-300', bg: 'bg-red-50', text: 'text-red-700' },
    amber: { border: 'border-amber-300', bg: 'bg-amber-50', text: 'text-amber-700' },
    teal: { border: 'border-teal-300', bg: 'bg-teal-50', text: 'text-teal-700' },
  }
  const a = accentMap[accent] || accentMap.teal
  return (
    <div className={`border rounded-xl p-5 ${a.bg} ${a.border}`}>
      <div className="text-xs uppercase tracking-wider font-semibold text-slate-500">{title}</div>
      <div className={`text-base font-bold mt-1 ${a.text}`}>
        {strategy.model && (
          <span
            className="inline-block w-2 h-2 rounded-full mr-2 align-middle"
            style={{ background: modelColor(strategy.model) }}
          />
        )}
        {strategy.label}
      </div>
      <div className="text-xs text-slate-500 mt-0.5">{subtitle}</div>
      <div className="text-2xl font-mono font-bold text-slate-900 mt-3">
        {fmt$(strategy.total)}<span className="text-sm text-slate-500 font-sans"> / mo</span>
      </div>
      <div className="text-xs text-slate-600 mt-1">
        avg score <span className="font-mono">{fmtScore(strategy.meanScore)}</span> ·
        passes <span className="font-mono">{strategy.passingTasks}/{strategy.taskCount}</span> tasks
      </div>
    </div>
  )
}

function Loader() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading the cost matrix…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Computing per-strategy monthly totals: naive (always-one-model) and CACR routing.
        </div>
      </div>
    </div>
  )
}

function ErrorView({ message }) {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="bg-red-50 border border-red-200 rounded-lg px-6 py-4 text-red-700 text-sm">
        Failed to load cost matrix: {message}
      </div>
    </div>
  )
}

function EmptyView() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="bg-white border border-slate-200 rounded-lg px-6 py-4 text-slate-600 text-sm shadow-sm">
        No cost matrix data available.
      </div>
    </div>
  )
}
