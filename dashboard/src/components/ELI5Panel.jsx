import { useState, useEffect, useCallback } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function ELI5Panel({ dataSummary, promptHint, taskName, warning, cascadeContext, refreshKey }) {
  const [explanation, setExplanation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetchExplanation = useCallback(() => {
    if (!dataSummary) return
    setLoading(true)
    setError(null)
    setExplanation(null)

    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 25_000)

    const body = { data_summary: dataSummary, prompt_hint: promptHint }
    if (taskName) body.task_name = taskName
    if (warning) body.warning = warning
    if (cascadeContext) body.cascade_context = cascadeContext

    fetch(`${API}/api/explain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(d => {
        if (d.error) throw new Error(d.error)
        setExplanation(d.explanation)
        setLoading(false)
      })
      .catch(err => {
        const msg = err.name === 'AbortError' ? 'Request timed out — try Refresh' : err.message
        setError(msg)
        setLoading(false)
      })
      .finally(() => clearTimeout(timer))
  }, [dataSummary, promptHint, taskName, warning, cascadeContext])

  useEffect(() => {
    fetchExplanation()
  }, [fetchExplanation, refreshKey])

  if (!dataSummary) return null

  return (
    <div className="mt-6 bg-gradient-to-br from-indigo-50 via-white to-teal-50 border border-indigo-100 rounded-xl p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <span className="inline-flex items-center gap-1.5 text-indigo-700 text-xs font-semibold tracking-wider uppercase">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-indigo-500" />
          What does this mean?
        </span>
        {!loading && explanation && (
          <button
            onClick={fetchExplanation}
            className="text-xs text-slate-500 hover:text-indigo-700 transition-colors ml-auto"
          >
            Refresh
          </button>
        )}
      </div>
      {loading && (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <svg className="animate-spin h-4 w-4 text-indigo-500" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
          Asking Claude to explain...
        </div>
      )}
      {error && (
        <p className="text-red-600 text-sm">Could not generate explanation: {error}</p>
      )}
      {explanation && (
        <p className="text-slate-700 text-sm leading-relaxed">{explanation}</p>
      )}
    </div>
  )
}
