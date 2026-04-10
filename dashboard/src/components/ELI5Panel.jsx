import { useState, useEffect, useCallback } from 'react'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function ELI5Panel({ dataSummary, promptHint, refreshKey }) {
  const [explanation, setExplanation] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const fetchExplanation = useCallback(() => {
    if (!dataSummary) return
    setLoading(true)
    setError(null)
    setExplanation(null)

    fetch(`${API}/api/explain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_summary: dataSummary, prompt_hint: promptHint }),
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
      .catch(err => { setError(err.message); setLoading(false) })
  }, [dataSummary, promptHint])

  useEffect(() => {
    fetchExplanation()
  }, [fetchExplanation, refreshKey])

  if (!dataSummary) return null

  return (
    <div className="mt-6 bg-gray-900/60 border border-gray-700 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-indigo-400 text-sm font-semibold tracking-wide uppercase">What does this mean?</span>
        {!loading && explanation && (
          <button
            onClick={fetchExplanation}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors ml-auto"
          >
            Refresh
          </button>
        )}
      </div>
      {loading && (
        <div className="flex items-center gap-2 text-gray-500 text-sm">
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
          Asking Claude to explain...
        </div>
      )}
      {error && (
        <p className="text-red-400 text-sm">Could not generate explanation: {error}</p>
      )}
      {explanation && (
        <p className="text-gray-300 text-sm leading-relaxed">{explanation}</p>
      )}
    </div>
  )
}
