import { useState, useEffect } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ZAxis,
} from 'recharts'
import ELI5Panel from '../components/ELI5Panel'
import { modelColor, modelShape, shortLabel } from '../lib/modelLabels'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function CustomTooltip({ active, payload }) {
  if (!active || !payload || payload.length === 0) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 shadow-xl text-sm">
      <p className="font-semibold text-white mb-1">{d.model}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-slate-200">
        <span>Confidence:</span>
        <span className="text-right font-mono">{d.confidence_score}</span>
        <span>Actual Score:</span>
        <span className="text-right font-mono">{d.score?.toFixed(3)}</span>
        {d.task && <><span>Task:</span><span className="text-right">{d.task}</span></>}
      </div>
    </div>
  )
}

function CalibrationELI5({ points }) {
  // Summarize per model for the prompt
  const byModel = {}
  for (const p of points) {
    const m = p.model || 'unknown'
    if (!byModel[m]) byModel[m] = { confs: [], scores: [] }
    if (p.confidence_score != null) byModel[m].confs.push(p.confidence_score)
    if (p.score != null) byModel[m].scores.push(p.score)
  }
  const summary = Object.entries(byModel).map(([model, d]) => {
    const mc = d.confs.length ? (d.confs.reduce((a, b) => a + b, 0) / d.confs.length).toFixed(1) : 'N/A'
    const ms = d.scores.length ? (d.scores.reduce((a, b) => a + b, 0) / d.scores.length).toFixed(3) : 'N/A'
    return `${model}: ${d.confs.length} points, mean confidence=${mc}/10, mean accuracy=${ms}`
  }).join('\n')

  return (
    <ELI5Panel
      dataSummary={summary}
      promptHint="You are explaining a calibration scatter plot to a non-technical engineer. Explain what this chart shows, which model is best calibrated (confidence matches accuracy), which is worst, and what that means in plain English for someone running an AI pipeline in production."
    />
  )
}

export default function CalibrationExplorer() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API}/api/calibration`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(d => { setData(d); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [])

  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />

  const points = Array.isArray(data) ? data : data?.points || []
  if (points.length === 0) {
    return <EmptyState />
  }

  const byModel = {}
  for (const p of points) {
    const model = p.model || 'unknown'
    if (!byModel[model]) byModel[model] = []
    byModel[model].push(p)
  }
  const modelNames = Object.keys(byModel)

  const refLineData = Array.from({ length: 11 }, (_, i) => ({
    confidence_score: i,
    score: i / 10,
  }))

  return (
    <div>
      <div className="mb-6">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-teal-700 font-semibold mb-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-500" />
          Self-reported confidence vs. actual accuracy
        </div>
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight">Confidence Accuracy</h2>
        <p className="text-slate-600 mt-2 max-w-3xl leading-relaxed">
          Models that say "9/10 confident" should be right 90% of the time. This chart shows which models are honest
          about uncertainty — and which are dangerously overconfident. Points on the dashed line are perfectly calibrated;
          points above are pessimistic, points below are overconfident.
        </p>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
        <ResponsiveContainer width="100%" height={500}>
          <ScatterChart margin={{ top: 20, right: 30, bottom: 20, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" />
            <XAxis
              type="number" dataKey="confidence_score" name="Confidence"
              domain={[0, 10]}
              tick={{ fill: '#475569', fontSize: 12 }}
              stroke="#CBD5E1"
              label={{ value: 'Confidence Score (1-10)', position: 'bottom', offset: 0, fill: '#64748B', fontSize: 13 }}
            />
            <YAxis
              type="number" dataKey="score" name="Actual Score"
              domain={[0, 1]}
              tick={{ fill: '#475569', fontSize: 12 }}
              stroke="#CBD5E1"
              label={{ value: 'Actual Score (0-1)', angle: -90, position: 'insideLeft', offset: 10, fill: '#64748B', fontSize: 13 }}
            />
            <ZAxis range={[40, 40]} />
            <Tooltip content={<CustomTooltip />} cursor={{ strokeDasharray: '3 3', stroke: '#94A3B8' }} />
            <Legend wrapperStyle={{ color: '#334155', paddingTop: '16px' }} />

            <Scatter
              name="Perfect Calibration" data={refLineData}
              fill="none" stroke="#94A3B8" strokeDasharray="6 4"
              line={{ strokeWidth: 2 }} legendType="line" shape={() => null}
            />

            {modelNames.map((model, i) => (
              <Scatter
                key={model} name={shortLabel(model)} data={byModel[model]}
                fill={modelColor(model, i)} fillOpacity={0.85}
                shape={modelShape(model)}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>

      <CalibrationELI5 points={points} />
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm px-6">
        <div className="animate-pulse text-slate-700 text-sm font-medium">Loading calibration scatter…</div>
        <div className="text-xs text-slate-500 mt-1.5 leading-relaxed">
          Each point pairs a model's self-reported confidence with how it actually scored on that trial.
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
        No calibration data available. Run calibration experiments first.
      </div>
    </div>
  )
}
