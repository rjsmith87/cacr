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
        <h2 className="text-2xl font-bold text-white">Router Playground</h2>
        <p className="text-gray-400 mt-1">Submit a task and see how the CACR router decides which model to use.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input form */}
        <form onSubmit={handleSubmit} className="bg-gray-900 border border-gray-800 rounded-xl p-6 flex flex-col gap-5">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1.5">Code Snippet</label>
            <textarea
              value={form.code_snippet}
              onChange={(e) => updateField('code_snippet', e.target.value)}
              rows={8}
              placeholder="Paste your code snippet here..."
              className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 font-mono placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 resize-y"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Task</label>
              <select
                value={form.task}
                onChange={(e) => updateField('task', e.target.value)}
                className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
              >
                <option value="" disabled>Select task type...</option>
                <option value="CodeReview">Code Review</option>
                <option value="SecurityVuln">Security Vuln</option>
                <option value="CodeSummarization">Code Summarization</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Complexity</label>
              <select
                value={form.complexity}
                onChange={(e) => updateField('complexity', e.target.value)}
                className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
              >
                <option value="auto">Auto (infer from code)</option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Pipeline Position</label>
              <select
                value={form.pipeline_position}
                onChange={(e) => updateField('pipeline_position', Number(e.target.value))}
                className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-100 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30"
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
            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm mt-auto"
          >
            {loading ? 'Routing...' : 'Route Request'}
          </button>
        </form>

        {/* Results */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
          {/* Content-mismatch warning — sits above all result rendering */}
          {mismatchWarning && (
            <div className="bg-yellow-950/40 border border-yellow-600/50 rounded-lg px-4 py-3 text-yellow-200 text-sm">
              <div className="font-semibold mb-1">⚠ Heads up: this code contains patterns commonly associated with security vulnerabilities</div>
              <div className="text-yellow-200/90 mb-3">
                Detected: <span className="font-mono">{mismatchWarning.patterns.join(', ')}</span>.
                You selected <span className="font-semibold">{TASK_LABELS[mismatchWarning.originalTask] || mismatchWarning.originalTask}</span> —
                did you mean Security Vuln?
              </div>
              <button
                type="button"
                onClick={switchToSecurityVuln}
                className="bg-yellow-600 hover:bg-yellow-500 text-yellow-950 font-semibold text-xs px-3 py-1.5 rounded transition-colors"
              >
                Switch to Security Vuln
              </button>
            </div>
          )}

          {!result && !error && !mismatchWarning && (
            <div className="flex items-center justify-center h-full text-gray-600 text-sm">
              Submit a task to see routing results
            </div>
          )}

          {error && (
            <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3 text-red-400 text-sm">
              Error: {error}
            </div>
          )}

          {result && (
            <div className="space-y-5">
              {/* Below-threshold warning — first thing inside the result block */}
              {result.below_threshold && result.warning && (
                <div className="bg-amber-950/40 border border-amber-700/50 rounded-lg px-4 py-3 text-amber-300 text-sm">
                  <div className="font-semibold mb-1">⚠ All models below threshold</div>
                  <div className="text-amber-200/90">{result.warning}</div>
                </div>
              )}

              {/* Inferred complexity badge */}
              {result.inferred_complexity && (
                <div className="flex items-center gap-2">
                  <span className="text-xs bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded-full px-3 py-1 font-medium">
                    Complexity inferred: {result.inferred_complexity}
                  </span>
                </div>
              )}

              {/* Recommended model */}
              <div>
                <span className="text-xs uppercase tracking-wider text-gray-500 font-medium">Recommended Model</span>
                <p className="text-xl font-bold text-indigo-400 mt-0.5">{result.recommended_model || result.model || '—'}</p>
              </div>

              {/* Confidence interval bar */}
              {result.confidence_interval && (
                <div>
                  <div className="flex justify-between items-baseline mb-1.5">
                    <span className="text-xs uppercase tracking-wider text-gray-500 font-medium">Confidence Interval</span>
                    <span className="text-sm font-mono text-gray-300">
                      {(result.confidence_interval[0] * 100).toFixed(0)}% – {(result.confidence_interval[1] * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div className="relative w-full bg-gray-800 rounded-full h-3 overflow-hidden">
                    <div
                      className="absolute h-full rounded-full transition-all duration-500"
                      style={{
                        left: `${result.confidence_interval[0] * 100}%`,
                        width: `${(result.confidence_interval[1] - result.confidence_interval[0]) * 100}%`,
                        background: `linear-gradient(90deg, #6366f1, #818cf8)`,
                      }}
                    />
                  </div>
                </div>
              )}

              {/* Cost */}
              {result.expected_cost != null && (
                <div>
                  <span className="text-xs uppercase tracking-wider text-gray-500 font-medium">Expected Cost</span>
                  <p className="text-lg font-mono text-emerald-400 mt-0.5">${Number(result.expected_cost).toFixed(4)}</p>
                </div>
              )}

              {/* Reasoning */}
              {result.reasoning && (
                <div>
                  <span className="text-xs uppercase tracking-wider text-gray-500 font-medium mb-2 block">Reasoning</span>
                  <div className="bg-gray-950 border border-gray-800 rounded-lg p-4 text-sm text-gray-300 prose prose-invert prose-sm max-w-none">
                    <ReactMarkdown>{result.reasoning}</ReactMarkdown>
                  </div>
                </div>
              )}

              {/* Extra fields */}
              {result.cascade_step != null && (
                <div className="flex gap-6 pt-2 border-t border-gray-800">
                  <div>
                    <span className="text-xs text-gray-500">Cascade Step</span>
                    <p className="text-sm font-mono text-gray-300">{result.cascade_step}</p>
                  </div>
                  {result.escalated != null && (
                    <div>
                      <span className="text-xs text-gray-500">Escalated</span>
                      <p className="text-sm font-mono text-gray-300">{result.escalated ? 'Yes' : 'No'}</p>
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
