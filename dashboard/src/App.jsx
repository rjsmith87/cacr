import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import CapabilityMatrix from './views/CapabilityMatrix'
import CalibrationExplorer from './views/CalibrationExplorer'
import CascadeDemo from './views/CascadeDemo'
import RouterPlayground from './views/RouterPlayground'
import CostModel from './views/CostModel'

const navItems = [
  { to: '/', label: 'Live Demo', accent: true },
  { to: '/capability', label: 'Which Model Wins What' },
  { to: '/calibration', label: 'Confidence Accuracy' },
  { to: '/router', label: 'Try the Router' },
  { to: '/cost-model', label: 'Cost Calculator' },
]

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-slate-50 text-slate-800">
        {/* Always-on framing banner — answers "what is this?" before the user
            has to click anything. Sits above the header so it stays visible
            even when the tab bar is sticky-pinned. */}
        <div className="sticky top-0 z-[60] bg-slate-900 text-slate-100 text-xs sm:text-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2 flex items-center justify-center gap-2 text-center leading-snug">
            <span className="hidden sm:inline-flex h-1.5 w-1.5 rounded-full bg-teal-400 shrink-0" aria-hidden="true" />
            <span>
              <span className="font-semibold text-white">CACR routes AI tasks to the cheapest model that can handle them</span>
              <span className="hidden sm:inline text-slate-400"> — empirically validated across 4 models, 3 task types, 30 trials each.</span>
            </span>
          </div>
        </div>
        <header className="border-b border-slate-200 bg-white/90 backdrop-blur-md sticky top-[40px] sm:top-[36px] z-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <div className="flex items-center gap-3 shrink-0">
                <div className="flex items-center gap-2">
                  <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-teal-600 text-white text-xs font-bold tracking-tight shadow-sm">
                    C
                  </span>
                  <h1 className="text-lg font-bold text-slate-900 tracking-tight">CACR</h1>
                </div>
                <span className="hidden sm:inline text-sm text-slate-500 border-l border-slate-200 pl-3">
                  Cascade-Aware Confidence Routing
                </span>
              </div>
              <div className="hidden md:flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Research framework
                </span>
              </div>
            </div>
            <nav className="flex gap-1 -mb-px overflow-x-auto pb-px scrollbar-none">
              {navItems.map(({ to, label, accent }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `whitespace-nowrap px-3 py-2.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                      isActive
                        ? 'border-teal-600 text-teal-700 font-semibold'
                        : accent
                          ? 'border-transparent text-indigo-600 hover:text-indigo-700 hover:border-indigo-200'
                          : 'border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300'
                    }`
                  }
                >
                  {accent && <span className="inline-block w-1.5 h-1.5 rounded-full bg-indigo-500" aria-hidden="true" />}
                  {label}
                </NavLink>
              ))}
            </nav>
          </div>
        </header>

        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<CascadeDemo />} />
            <Route path="/capability" element={<CapabilityMatrix />} />
            <Route path="/calibration" element={<CalibrationExplorer />} />
            <Route path="/router" element={<RouterPlayground />} />
            <Route path="/cost-model" element={<CostModel />} />
          </Routes>
        </main>

        <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-500">
          CACR Dashboard — Cascade-Aware Confidence Routing
        </footer>
      </div>
    </BrowserRouter>
  )
}

export default App
