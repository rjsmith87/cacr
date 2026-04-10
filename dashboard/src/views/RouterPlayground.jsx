import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function RouterPlayground() {
  const [form, setForm] = useState({
    code_snippet: '',
    task: 'CodeReview',
    complexity: 'easy',
    pipeline_position: 1,
  })
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res = await fetch(`${API}/api/route`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: form.code_snippet,
          task: form.task,
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

  const updateField = (field, value) => setForm(prev => ({ ...prev, [field]: value }))

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
            disabled={loading || !form.code_snippet.trim()}
            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-medium py-2.5 rounded-lg transition-colors text-sm mt-auto"
          >
            {loading ? 'Routing...' : 'Route Request'}
          </button>
        </form>

        {/* Results */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          {!result && !error && (
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
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
