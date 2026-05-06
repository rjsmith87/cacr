import { useState, useEffect } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, Cell,
} from 'recharts'
import ELI5Panel from '../components/ELI5Panel'
import { modelColor, shortLabel } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function getModelColor(model, index) {
  return modelColor(model, index)
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl text-sm">
      <p className="font-semibold text-white mb-1">{label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex justify-between gap-4 text-slate-200">
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
      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {modelSummaries.map((m, i) => (
          <div key={m.model} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: m.color }} />
              <span className="text-sm font-medium text-slate-800 truncate" title={m.model}>{shortLabel(m.model)}</span>
            </div>
            <p className="text-3xl font-bold font-mono tracking-tight" style={{ color: m.color }}>
              {m.avgEfficiency.toFixed(1)}
            </p>
            <p className="text-xs text-slate-500 mt-1 uppercase tracking-wider font-semibold">avg score/cost ratio</p>
            <div className="mt-3 pt-3 border-t border-slate-100 flex justify-between text-xs text-slate-500 font-mono">
              <span>Score: {m.avgScore.toFixed(2)}</span>
              <span>Cost: ${m.avgCost.toFixed(4)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Bar chart */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <ResponsiveContainer
          width="100%"
          height={Math.max(500, tasks.length * (models.length * 18 + 60))}
        >
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 10, right: 30, bottom: 10, left: 100 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" horizontal={false} />
            <XAxis
              type="number"
              tick={{ fill: '#475569', fontSize: 12 }}
              stroke="#CBD5E1"
              label={{ value: 'Score / Cost Ratio', position: 'bottom', offset: 0, fill: '#64748B', fontSize: 13 }}
            />
            <YAxis
              type="category"
              dataKey="task"
              tick={{ fill: '#475569', fontSize: 12 }}
              stroke="#CBD5E1"
              width={90}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(13, 148, 136, 0.08)' }} />
            <Legend wrapperStyle={{ color: '#334155', paddingTop: '16px' }} />
            {models.map((model, i) => (
              <Bar
                key={model}
                dataKey={model}
                name={shortLabel(model)}
                fill={getModelColor(model, i)}
                fillOpacity={0.92}
                radius={[0, 4, 4, 0]}
                barSize={14}
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
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading efficiency ratios…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Dividing each model's mean score by its expected cost on each task to surface the per-dollar winner.
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
    <div className="flex items-center justify-center h-64">
      <div className="bg-white border border-slate-200 rounded-lg px-6 py-4 text-slate-600 text-sm shadow-sm">
        No cost matrix data available. Run benchmarks first.
      </div>
    </div>
  )
}
