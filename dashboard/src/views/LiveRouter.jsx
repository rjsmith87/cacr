import { useState } from 'react'
import { shortLabel, modelColor } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const TASK_OPTIONS = [
  { value: 'CodeReview', label: 'Code Review' },
  { value: 'SecurityVuln', label: 'Security Vuln' },
  { value: 'CodeSummarization', label: 'Code Summarization' },
]

const EXAMPLES = [
  {
    label: 'Simple code summary',
    task_type: 'CodeSummarization',
    task: `def add(a, b):
    """Return the sum of two numbers."""
    return a + b

def multiply(a, b):
    """Return the product of two numbers."""
    return a * b

Summarize what this module does in one sentence.`,
  },
  {
    label: 'CVE classification',
    task_type: 'SecurityVuln',
    task: `import os
import urllib.request

def fetch_user_avatar(url):
    # User-supplied URL — fetch and save locally
    data = urllib.request.urlopen(url).read()
    with open("/tmp/avatar.png", "wb") as f:
        f.write(data)

Is this code vulnerable? If so, name the vulnerability type and severity.`,
  },
  {
    label: 'Multi-hop reasoning',
    task_type: 'CodeReview',
    task: `def process_transactions(transactions, accounts):
    for tx in transactions:
        src = accounts.get(tx["from"])
        dst = accounts.get(tx["to"])
        if src is None or dst is None:
            continue
        if src["balance"] < tx["amount"]:
            continue
        src["balance"] -= tx["amount"]
        dst["balance"] += tx["amount"]
        tx["status"] = "ok"
    return transactions

Walk through this code: identify every concurrency, ordering, or
consistency issue that would surface if two threads called this
function on the same accounts dict in parallel. Rank issues by
severity.`,
  },
]

function fmtUsd(v) {
  if (v == null) return '—'
  if (v === 0) return '$0'
  if (v < 0.0001) return `$${v.toExponential(2)}`
  return `$${v.toFixed(6)}`
}

function fmtMs(v) {
  if (v == null) return '—'
  return `${Math.round(v)} ms`
}

function ConfidenceBadge({ confidence, signal, logprob }) {
  if (confidence == null && logprob == null) {
    return <span className="text-xs text-slate-400">no signal</span>
  }
  const isLogprob = signal === 'logprob' && logprob != null
  const value = isLogprob ? `${(logprob * 100).toFixed(0)}%` : `${confidence}/10`
  const label = isLogprob ? 'logprob' : 'self-report'
  const color = isLogprob
    ? 'bg-indigo-50 border-indigo-200 text-indigo-800'
    : 'bg-slate-50 border-slate-200 text-slate-700'
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs border rounded-full px-2 py-0.5 ${color}`}>
      <span className="font-mono font-semibold">{value}</span>
      <span className="text-[10px] uppercase tracking-wider opacity-75">{label}</span>
    </span>
  )
}

export default function LiveRouter() {
  const [task, setTask] = useState('')
  const [taskType, setTaskType] = useState('CodeReview')
  const [threshold, setThreshold] = useState(7)

  const [runResult, setRunResult] = useState(null)
  const [runLoading, setRunLoading] = useState(false)
  const [runError, setRunError] = useState(null)

  const [compareResult, setCompareResult] = useState(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareError, setCompareError] = useState(null)

  const loadExample = (ex) => {
    setTask(ex.task)
    setTaskType(ex.task_type)
    setRunResult(null)
    setRunError(null)
    setCompareResult(null)
    setCompareError(null)
  }

  const run = async () => {
    setRunLoading(true)
    setRunError(null)
    setRunResult(null)
    try {
      const res = await fetch(`${API}/api/route/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task,
          task_type: taskType,
          escalation_threshold: threshold,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      setRunResult(data)
    } catch (err) {
      setRunError(err.message)
    } finally {
      setRunLoading(false)
    }
  }

  const compare = async () => {
    setCompareLoading(true)
    setCompareError(null)
    setCompareResult(null)
    try {
      const res = await fetch(`${API}/api/route/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, task_type: taskType }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      setCompareResult(data)
    } catch (err) {
      setCompareError(err.message)
    } finally {
      setCompareLoading(false)
    }
  }

  const canRun = !!task.trim() && !!taskType

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          Interactive · Real model call
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Live Router</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          Send a task to the API. CACR classifies its complexity, picks the cheapest model
          that meets the accuracy floor for the task type, calls that model, and cascades up
          to the next cheapest qualifying model if confidence is below threshold.
          Compare against running all eight models to see what routing actually saves.
        </p>
      </div>

      {/* Quick-start examples */}
      <div className="mb-6 grid grid-cols-1 sm:grid-cols-3 gap-3">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            onClick={() => loadExample(ex)}
            className="text-left bg-white border border-slate-200 hover:border-teal-400 rounded-lg p-3 shadow-sm transition-colors"
          >
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1">
              Example
            </div>
            <div className="font-semibold text-slate-900 text-sm">{ex.label}</div>
            <div className="text-xs text-slate-500 mt-1">
              task_type: <span className="font-mono">{ex.task_type}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input form */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 flex flex-col gap-5 shadow-sm">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Task</label>
            <textarea
              value={task}
              onChange={(e) => setTask(e.target.value)}
              rows={10}
              placeholder="Paste a task, prompt, or code snippet to route..."
              className="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 font-mono placeholder:text-slate-400 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 focus:bg-white resize-y"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Task type</label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20"
              >
                {TASK_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Escalation threshold: <span className="font-mono font-semibold">{threshold}</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                step={1}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                className="w-full accent-teal-600"
              />
              <div className="text-xs text-slate-500 mt-0.5">
                Cascade up when self-reported confidence is below this.
              </div>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row gap-2">
            <button
              type="button"
              onClick={run}
              disabled={!canRun || runLoading}
              className="flex-1 bg-teal-600 hover:bg-teal-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm shadow-sm disabled:shadow-none"
            >
              {runLoading ? 'Routing…' : 'Route & run'}
            </button>
            <button
              type="button"
              onClick={compare}
              disabled={!canRun || compareLoading}
              className="flex-1 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm shadow-sm disabled:shadow-none"
            >
              {compareLoading ? 'Running all models…' : 'Compare all models'}
            </button>
          </div>
          <p className="text-xs text-slate-500 leading-relaxed">
            <span className="font-semibold">Route &amp; run</span> spends at most two model
            calls. <span className="font-semibold">Compare all models</span> fans out to all
            eight; expect 30–60 s and a 60 s cooldown.
          </p>
        </div>

        {/* Live route result */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm space-y-4">
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
            Route &amp; run result
          </div>

          {!runResult && !runError && !runLoading && (
            <div className="flex items-center justify-center py-10 text-sm text-slate-500 text-center px-4">
              Pick a task and hit "Route &amp; run" to see which model CACR picks,
              whether it cascades, and what it actually returns.
            </div>
          )}

          {runError && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">
              {runError}
            </div>
          )}

          {runResult && (
            <div className="space-y-4">
              {runResult.below_threshold && runResult.warning && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-amber-900 text-sm">
                  <div className="font-semibold mb-1">⚠ Below threshold</div>
                  <div className="text-amber-800">{runResult.warning}</div>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
                    Model used
                  </div>
                  <div
                    className="text-lg font-bold mt-0.5 tracking-tight"
                    style={{ color: modelColor(runResult.model_used) }}
                  >
                    {shortLabel(runResult.model_used)}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
                    Cascaded
                  </div>
                  <div className="text-lg font-bold mt-0.5 tracking-tight">
                    {runResult.cascaded ? (
                      <span className="text-amber-700">Yes — escalated</span>
                    ) : (
                      <span className="text-emerald-700">No</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
                    Cost estimate
                  </div>
                  <div className="text-lg font-mono font-bold text-emerald-700 mt-0.5">
                    {fmtUsd(runResult.cost_estimate)}
                  </div>
                </div>
                <div>
                  <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
                    Latency
                  </div>
                  <div className="text-lg font-mono font-bold text-slate-800 mt-0.5">
                    {fmtMs(runResult.latency_ms)}
                  </div>
                </div>
              </div>

              {/* Cascade trace */}
              <div className="border border-slate-200 rounded-lg overflow-hidden">
                <div className="bg-slate-50 px-3 py-2 text-xs uppercase tracking-wider text-slate-600 font-semibold border-b border-slate-200">
                  Trace
                </div>
                <div className="divide-y divide-slate-200">
                  <div className="px-3 py-2 flex items-center justify-between text-sm">
                    <div>
                      <span className="text-slate-500">Initial:</span>{' '}
                      <span className="font-mono font-semibold" style={{ color: modelColor(runResult.initial_model) }}>
                        {shortLabel(runResult.initial_model)}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <ConfidenceBadge
                        confidence={runResult.initial_confidence}
                        signal={runResult.confidence_signal}
                        logprob={null}
                      />
                      <span className="text-xs font-mono text-slate-500">
                        {fmtUsd(runResult.initial_cost)} · {fmtMs(runResult.initial_latency)}
                      </span>
                    </div>
                  </div>
                  {runResult.cascaded && runResult.escalation_model && (
                    <div className="px-3 py-2 flex items-center justify-between text-sm bg-amber-50/50">
                      <div>
                        <span className="text-amber-700">Escalation →</span>{' '}
                        <span className="font-mono font-semibold" style={{ color: modelColor(runResult.escalation_model) }}>
                          {shortLabel(runResult.escalation_model)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <ConfidenceBadge
                          confidence={runResult.escalation_confidence}
                          signal={runResult.confidence_signal}
                          logprob={null}
                        />
                        <span className="text-xs font-mono text-slate-500">
                          {fmtUsd(runResult.escalation_cost)} · {fmtMs(runResult.escalation_latency)}
                        </span>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Response body */}
              <div>
                <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1.5">
                  Response
                </div>
                <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs font-mono text-slate-800 whitespace-pre-wrap break-words max-h-96 overflow-auto">
                  {runResult.response || '(empty response)'}
                </pre>
              </div>

              {runResult.error && (
                <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-red-700 text-xs">
                  Model error: <span className="font-mono">{runResult.error}</span>
                </div>
              )}

              <div className="text-xs text-slate-500">
                Inferred complexity: <span className="font-mono">{runResult.complexity}</span> ·
                {' '}signal: <span className="font-mono">{runResult.confidence_signal}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Compare-all section */}
      <div className="mt-8 bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <div className="flex items-baseline justify-between mb-4">
          <div>
            <h3 className="text-xl font-bold text-slate-900 tracking-tight">All-models comparison</h3>
            <p className="text-sm text-slate-600 mt-0.5">
              Same task, every model, side by side. Routed pick is highlighted.
            </p>
          </div>
          {compareResult && (
            <div className="text-right text-sm">
              <div className="text-slate-500">If you ran all 8:</div>
              <div className="font-mono font-semibold text-slate-800">
                {fmtUsd(compareResult.total_cost_if_all_models_run)}
              </div>
              <div className="text-emerald-700 font-semibold text-xs">
                routing saved {fmtUsd(compareResult.cost_saved_vs_running_all)}
              </div>
            </div>
          )}
        </div>

        {compareError && (
          <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm mb-3">
            {compareError}
          </div>
        )}

        {compareLoading && (
          <div className="text-center py-10 text-sm text-slate-500">
            Running all eight models in parallel — this takes 30–60 seconds…
          </div>
        )}

        {!compareResult && !compareLoading && !compareError && (
          <div className="text-center py-10 text-sm text-slate-500">
            Hit "Compare all models" to fan out the same task to every model and see the cost spread.
          </div>
        )}

        {compareResult && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left border-b border-slate-200">
                  <th className="py-2 px-2 font-semibold text-slate-700">Model</th>
                  <th className="py-2 px-2 font-semibold text-slate-700 text-right">Cost</th>
                  <th className="py-2 px-2 font-semibold text-slate-700 text-right">Latency</th>
                  <th className="py-2 px-2 font-semibold text-slate-700 text-center">Conf</th>
                  <th className="py-2 px-2 font-semibold text-slate-700">Response (first 200 chars)</th>
                </tr>
              </thead>
              <tbody>
                {compareResult.results.map((r) => {
                  const isRouted = r.model === compareResult.routed_model
                  return (
                    <tr
                      key={r.model}
                      className={`border-b border-slate-100 ${isRouted ? 'bg-teal-50' : ''}`}
                    >
                      <td className="py-2 px-2">
                        <div className="flex items-center gap-2">
                          <span
                            className="inline-block w-2 h-2 rounded-full"
                            style={{ background: modelColor(r.model) }}
                          />
                          <span className="font-mono font-semibold">{shortLabel(r.model)}</span>
                          {isRouted && (
                            <span className="text-[10px] bg-teal-600 text-white rounded-full px-2 py-0.5 font-semibold uppercase tracking-wider">
                              routed
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 px-2 text-right font-mono">{fmtUsd(r.cost_usd)}</td>
                      <td className="py-2 px-2 text-right font-mono text-slate-600">{fmtMs(r.latency_ms)}</td>
                      <td className="py-2 px-2 text-center">
                        {r.logprob_confidence != null ? (
                          <span className="text-xs font-mono">{(r.logprob_confidence * 100).toFixed(0)}%</span>
                        ) : r.confidence != null ? (
                          <span className="text-xs font-mono">{r.confidence}/10</span>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className="py-2 px-2 text-xs text-slate-700 font-mono">
                        {r.error ? (
                          <span className="text-red-600">error: {r.error}</span>
                        ) : (
                          <span className="line-clamp-2">{(r.response || '').slice(0, 200)}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {compareResult.routed_below_threshold && compareResult.routed_warning && (
              <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-amber-900 text-xs">
                {compareResult.routed_warning}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
