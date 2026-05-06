import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import ELI5Panel from '../components/ELI5Panel'
import { scanDangerousPatterns } from '../lib/dangerousPatterns'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function RouterPlayground() {
  const [form, setForm] = useState({
    code_snippet: '',
    task: '',
    complexity: 'auto',
    pipeline_position: 1,
  })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  // mismatchWarning: { patterns: string[], originalTask: string } | null
  // Set when the pasted code contains dangerous patterns and the user
  // routed it under a non-SecurityVuln task. Banner is informational
  // only — submission is never blocked.
  const [mismatchWarning, setMismatchWarning] = useState(null)

  // Extracted so the "Switch to Security Vuln" button can call it with
  // an explicit task override without going through React's async state
  // update (which would race the re-fetch).
  const route = async (task) => {
    setLoading(true)
    setError(null)
    setResult(null)

    // Client-side dangerous-pattern scan — do this BEFORE the network
    // call so the banner is in place by the time the result lands.
    const matched = scanDangerousPatterns(form.code_snippet)
    if (matched.length > 0 && task !== 'SecurityVuln') {
      setMismatchWarning({ patterns: matched, originalTask: task })
    } else {
      setMismatchWarning(null)
    }

    try {
      const res = await fetch(`${API}/api/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: form.code_snippet,
          task,
          complexity: form.complexity,
          pipeline_position: form.pipeline_position,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    route(form.task)
  }

  const switchToSecurityVuln = () => {
    setForm(prev => ({ ...prev, task: 'SecurityVuln' }))
    route('SecurityVuln')
  }

  const updateField = (field, value) => setForm(prev => ({ ...prev, [field]: value }))

  const TASK_LABELS = {
    CodeReview: 'Code Review',
    SecurityVuln: 'Security Vuln',
    CodeSummarization: 'Code Summarization',
  }

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          Interactive · Single routing decision
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Try the Router</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          Paste any code snippet and watch CACR pick a model, justify the choice, and quote the expected cost. Same
          routing logic that powers the live demo, exposed as an interactive sandbox so you can probe edge cases.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input form */}
        <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-6 flex flex-col gap-5 shadow-sm">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">Code Snippet</label>
            <textarea
              value={form.code_snippet}
              onChange={(e) => updateField('code_snippet', e.target.value)}
              rows={8}
              placeholder="Paste your code snippet here..."
              className="w-full bg-slate-50 border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 font-mono placeholder:text-slate-400 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20 focus:bg-white resize-y"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Task</label>
              <select
                value={form.task}
                onChange={(e) => updateField('task', e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20"
              >
                <option value="" disabled>Select task type...</option>
                <option value="CodeReview">Code Review</option>
                <option value="SecurityVuln">Security Vuln</option>
                <option value="CodeSummarization">Code Summarization</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Complexity</label>
              <select
                value={form.complexity}
                onChange={(e) => updateField('complexity', e.target.value)}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20"
              >
                <option value="auto">Auto (infer from code)</option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">Pipeline Position</label>
              <select
                value={form.pipeline_position}
                onChange={(e) => updateField('pipeline_position', Number(e.target.value))}
                className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-500/20"
              >
                <option value={1}>1 (First)</option>
                <option value={2}>2 (Middle)</option>
                <option value={3}>3 (Last)</option>
              </select>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !form.code_snippet.trim() || !form.task}
            className="w-full bg-teal-600 hover:bg-teal-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-semibold py-2.5 rounded-lg transition-colors text-sm mt-auto shadow-sm disabled:shadow-none"
          >
            {loading ? 'Routing...' : 'Route Request'}
          </button>
        </form>

        {/* Results */}
        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-4 shadow-sm">
          {/* Content-mismatch warning — sits above all result rendering */}
          {mismatchWarning && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-amber-900 text-sm">
              <div className="font-semibold mb-1">⚠ Heads up: this code contains patterns commonly associated with security vulnerabilities</div>
              <div className="text-amber-800 mb-3">
                Detected: <span className="font-mono">{mismatchWarning.patterns.join(', ')}</span>.
                You selected <span className="font-semibold">{TASK_LABELS[mismatchWarning.originalTask] || mismatchWarning.originalTask}</span> —
                did you mean Security Vuln?
              </div>
              <button
                type="button"
                onClick={switchToSecurityVuln}
                className="bg-amber-600 hover:bg-amber-700 text-white font-semibold text-xs px-3 py-1.5 rounded transition-colors shadow-sm"
              >
                Switch to Security Vuln
              </button>
            </div>
          )}

          {!result && !error && !mismatchWarning && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center max-w-xs px-4">
                <div className="text-sm font-medium text-slate-700">Pick a task and hit "Route Request"</div>
                <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
                  CACR will return: which model it picked, the expected cost, a confidence interval, and a written
                  justification you can audit.
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">
              Error: {error}
            </div>
          )}

          {result && (
            <div className="space-y-5">
              {/* Below-threshold warning — first thing inside the result block */}
              {result.below_threshold && result.warning && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-amber-900 text-sm">
                  <div className="font-semibold mb-1">⚠ All models below threshold</div>
                  <div className="text-amber-800">{result.warning}</div>
                </div>
              )}

              {/* Inferred complexity badge */}
              {result.inferred_complexity && (
                <div className="flex items-center gap-2">
                  <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full px-3 py-1 font-medium">
                    Complexity inferred: {result.inferred_complexity}
                  </span>
                </div>
              )}

              {/* Recommended model */}
              <div>
                <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Recommended Model</span>
                <p className="text-2xl font-bold text-teal-700 mt-0.5 tracking-tight">{result.recommended_model || result.model || '—'}</p>
              </div>

              {/* Confidence interval bar */}
              {result.confidence_interval && (
                <div>
                  <div className="flex justify-between items-baseline mb-1.5">
                    <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Confidence Interval</span>
                    <span className="text-sm font-mono text-slate-700">
                      {(result.confidence_interval[0] * 100).toFixed(0)}% – {(result.confidence_interval[1] * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="relative w-full bg-slate-100 rounded-full h-3 overflow-hidden">
                    <div
                      className="absolute h-full rounded-full transition-all duration-500"
                      style={{
                        left: `${result.confidence_interval[0] * 100}%`,
                        width: `${(result.confidence_interval[1] - result.confidence_interval[0]) * 100}%`,
                        background: `linear-gradient(90deg, #0D9488, #6366F1)`,
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Cost */}
              {result.expected_cost != null && (
                <div>
                  <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold">Expected Cost</span>
                  <p className="text-lg font-mono font-bold text-emerald-700 mt-0.5">${Number(result.expected_cost).toFixed(4)}</p>
                </div>
              )}

              {/* Reasoning */}
              {result.reasoning && (
                <div>
                  <span className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-2 block">Reasoning</span>
                  <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 text-sm text-slate-700 prose prose-slate prose-sm max-w-none">
                    <ReactMarkdown>{result.reasoning}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Extra fields */}
              {result.cascade_step != null && (
                <div className="flex gap-6 pt-3 border-t border-slate-200">
                  <div>
                    <span className="text-xs text-slate-500 uppercase tracking-wider">Cascade Step</span>
                    <p className="text-sm font-mono text-slate-700">{result.cascade_step}</p>
                  </div>
                  {result.escalated != null && (
                    <div>
                      <span className="text-xs text-slate-500 uppercase tracking-wider">Escalated</span>
                      <p className="text-sm font-mono text-slate-700">{result.escalated ? 'Yes' : 'No'}</p>
                    </div>
                  )}
                </div>
              )}
              <ELI5Panel
                dataSummary={`Task: ${form.task}, Recommended model: ${result.recommended_model}, Expected cost: $${result.expected_cost?.toFixed(6)}, Complexity: ${result.inferred_complexity || result.complexity || 'unknown'}, Reasoning: ${result.reasoning}`}
                promptHint="You are explaining an AI routing decision to a non-technical person. In plain English, explain why this model was picked for this task, what it costs, and whether this is a sensible recommendation. Don't use technical jargon — explain it like you're talking to a product manager."
                taskName={form.task}
                warning={result.warning}
                refreshKey={`${result.recommended_model}|${form.task}|${result.below_threshold ? 'below' : 'ok'}`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
