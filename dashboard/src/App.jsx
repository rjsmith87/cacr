import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import CapabilityMatrix from './views/CapabilityMatrix'
import CalibrationExplorer from './views/CalibrationExplorer'
import PipelineCost from './views/PipelineCost'
import RouterPlayground from './views/RouterPlayground'
import ModelEfficiency from './views/ModelEfficiency'
import CostModel from './views/CostModel'

const navItems = [
  { to: '/', label: 'Capability Matrix' },
  { to: '/calibration', label: 'Calibration Explorer' },
  { to: '/cost-model', label: 'Cost Model' },
  { to: '/pipeline', label: 'Pipeline Cost' },
  { to: '/router', label: 'Router Playground' },
  { to: '/efficiency', label: 'Model Efficiency' },
]

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        <header className="border-b border-gray-800 bg-gray-950/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center gap-3 shrink-0">
                <h1 className="text-xl font-bold text-white tracking-tight">CACR</h1>
                <span className="hidden sm:inline text-sm text-gray-500 border-l border-gray-700 pl-3">
                  Cascade-Aware Confidence Routing
                </span>
              </div>
            </div>
            <nav className="flex gap-1 -mb-px overflow-x-auto pb-px scrollbar-none">
              {navItems.map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `whitespace-nowrap px-3 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                      isActive
                        ? 'border-indigo-500 text-indigo-400'
                        : 'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-600'
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>

        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<CapabilityMatrix />} />
            <Route path="/calibration" element={<CalibrationExplorer />} />
            <Route path="/cost-model" element={<CostModel />} />
            <Route path="/pipeline" element={<PipelineCost />} />
            <Route path="/router" element={<RouterPlayground />} />
            <Route path="/efficiency" element={<ModelEfficiency />} />
          </Routes>
        </main>

        <footer className="border-t border-gray-800 py-4 text-center text-xs text-gray-600">
          CACR Dashboard — Cascade-Aware Confidence Routing
        </footer>
      </div>
    </BrowserRouter>
  )
}

export default App
