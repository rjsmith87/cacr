import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, Cell,
} from 'recharts'
import ELI5Panel from '../components/ELI5Panel'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const MODEL_COLORS = {
  'gemini-2.5-flash-lite': '#34d399',
  'flash-lite': '#34d399',
  'claude-haiku-4-5': '#fbbf24',
  'haiku': '#fbbf24',
  'gemini-2.5-flash': '#60a5fa',
  'flash': '#60a5fa',
  'gpt-4o-mini': '#f472b6',
}

const FALLBACK_COLORS = ['#818cf8', '#34d399', '#fbbf24', '#f472b6', '#60a5fa', '#a78bfa', '#fb923c', '#2dd4bf']

function getModelColor(model, index) {
  const lower = model.toLowerCase()
  for (const [key, color] of Object.entries(MODEL_COLORS)) {
    if (lower.includes(key)) return color
  }
  return FALLBACK_COLORS[index % FALLBACK_COLORS.length]
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 shadow-xl text-sm">
      <p className="font-semibold text-white mb-1">{label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex justify-between gap-4 text-gray-300">
          <span style={{ color: entry.color }}>{entry.name}</span>
          <span className="font-mono">{Number(entry.value).toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

export default function ModelEfficiency() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/cost-matrix`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(raw => {
        // API returns {expected_cost_usd, mean_score, ...}
        // Component expects {cost, score, ...}
        const rows = Array.isArray(raw) ? raw : raw?.entries || []
        const mapped = rows.map(r => ({
          ...r,
          cost: r.expected_cost_usd ?? r.cost,
          score: r.mean_score ?? r.score,
        }))
        setData(mapped)
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />

  const entries = Array.isArray(data) ? data : []
  if (entries.length === 0) return <EmptyState />

  // Build efficiency data: score/cost ratio per model per task
  const models = [...new Set(entries.map(e => e.model))]
  const tasks = [...new Set(entries.map(e => e.task))]

  const chartData = tasks.map(task => {
    const row = { task }
    for (const model of models) {
      const entry = entries.find(e => e.task === task && e.model === model)
      if (entry && entry.cost && entry.cost > 0) {
        row[model] = (entry.score || 0) / entry.cost
      } else {
        row[model] = 0
      }
    }
    return row
  })

  // Summary cards: average efficiency per model
  const modelSummaries = models.map((model, idx) => {
    const modelEntries = entries.filter(e => e.model === model && e.cost > 0)
    const avgEfficiency = modelEntries.length > 0
      ? modelEntries.reduce((sum, e) => sum + (e.score || 0) / e.cost, 0) / modelEntries.length
      : 0
    const avgScore = modelEntries.length > 0
      ? modelEntries.reduce((sum, e) => sum + (e.score || 0), 0) / modelEntries.length
      : 0
    const avgCost = modelEntries.length > 0
      ? modelEntries.reduce((sum, e) => sum + e.cost, 0) / modelEntries.length
      : 0
    return { model, avgEfficiency, avgScore, avgCost, color: getModelColor(model, idx) }
  }).sort((a, b) => b.avgEfficiency - a.avgEfficiency)

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-white">Model Efficiency</h2>
        <p className="text-gray-400 mt-1">
          Score-to-cost ratio per model per task. Higher bars = more value per dollar.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {modelSummaries.map((m, i) => (
          <div key={m.model} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: m.color }} />
              <span className="text-sm font-medium text-gray-200 truncate" title={m.model}>{m.model}</span>
            </div>
            <p className="text-2xl font-bold font-mono" style={{ color: m.color }}>
              {m.avgEfficiency.toFixed(1)}
            </p>
            <p className="text-xs text-gray-500 mt-1">avg score/cost ratio</p>
            <div className="mt-2 flex justify-between text-xs text-gray-500">
              <span>Score: {m.avgScore.toFixed(2)}</span>
              <span>Cost: ${m.avgCost.toFixed(4)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Bar chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <ResponsiveContainer width="100%" height={Math.max(400, tasks.length * 50)}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 10, right: 30, bottom: 10, left: 100 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fill: '#9ca3af', fontSize: 12 }}
              label={{ value: 'Score / Cost Ratio', position: 'bottom', offset: 0, fill: '#9ca3af', fontSize: 13 }}
            />
            <YAxis
              type="category"
              dataKey="task"
              tick={{ fill: '#9ca3af', fontSize: 12 }}
              width={90}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(107, 114, 128, 0.1)' }} />
            <Legend wrapperStyle={{ color: '#d1d5db', paddingTop: '16px' }} />
            {models.map((model, i) => (
              <Bar
                key={model}
                dataKey={model}
                name={model}
                fill={getModelColor(model, i)}
                fillOpacity={0.85}
                radius={[0, 4, 4, 0]}
                barSize={16}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <ELI5Panel
        dataSummary={modelSummaries.map(m => `${m.model}: avg efficiency=${m.avgEfficiency.toFixed(1)}, avg score=${m.avgScore.toFixed(2)}, avg cost=$${m.avgCost.toFixed(6)}`).join('\n')}
        promptHint="You are explaining a model efficiency chart (score-to-cost ratio) to a non-technical engineer. Explain the score/cost ratio concept in plain English. Which model gives the most value per dollar and why that matters more than raw accuracy alone? Use the actual model names and numbers."
      />
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-pulse text-gray-500 text-sm">Loading cost matrix data...</div>
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
    <div className="flex items-center justify-center h-64">
      <div className="bg-gray-900 border border-gray-800 rounded-lg px-6 py-4 text-gray-400 text-sm">
        No cost matrix data available. Run benchmarks first.
      </div>
    </div>
  )
}
