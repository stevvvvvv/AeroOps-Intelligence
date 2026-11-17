import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import { api, STATIC } from './api'
import Dashboard from './components/Dashboard'
import RiskBoard from './components/RiskBoard'
import Rotations from './components/Rotations'
import Simulator from './components/Simulator'
import ModelPage from './components/ModelPage'

const TABS = [
  ['dashboard', 'Performance'],
  ['risk', 'Vols à risque'],
  ['rotations', 'Rotations'],
  ['sim', 'Simulation'],
  ['model', 'Modèle'],
]

function App() {
  const [meta, setMeta] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('dashboard')
  const [date, setDate] = useState(null)
  const [simTarget, setSimTarget] = useState(null) // {flight_id, delay}

  useEffect(() => {
    api.meta().then((m) => { setMeta(m); setDate(m.scored_dates.at(-1)) }).catch((e) => setError(e.message))
  }, [])

  const openSim = (flight_id, delay) => { setSimTarget({ flight_id, delay: Math.max(15, Math.round(delay || 45)) }); setTab('sim') }

  if (error) return <div className="empty">{STATIC ? `Données de démo introuvables (${error})` : <>API injoignable ({error}). Lancer : <code>uvicorn aeroops.api.main:app</code></>}</div>
  if (!meta) return <div className="empty">Chargement…</div>

  return (
    <>
      <header className="topbar">
        <div className="brand">AeroOps Intelligence<span>Supervision des opérations</span></div>
        {STATIC && <span className="badge" title="Données de démonstration pré-calculées ; la simulation est recalculée dans le navigateur">Démo statique</span>}
        <nav className="tabs">
          {TABS.map(([k, l]) => <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>)}
        </nav>
        <div className="spacer" />
        {tab !== 'dashboard' && tab !== 'model' && (
          <label style={{ fontSize: 12, color: 'var(--ink-2)' }}>Journée d'exploitation{' '}
            <select value={date} onChange={(e) => setDate(e.target.value)}>
              {meta.scored_dates.map((d) => <option key={d} value={d}>{d}{meta.atc_strike_days.includes(d) ? ' (grève ATC)' : ''}</option>)}
            </select>
          </label>
        )}
      </header>
      <main>
        {tab === 'dashboard' && <Dashboard meta={meta} />}
        {tab === 'risk' && <RiskBoard date={date} meta={meta} onSimulate={openSim} />}
        {tab === 'rotations' && <Rotations date={date} onSimulate={openSim} />}
        {tab === 'sim' && <Simulator date={date} target={simTarget} />}
        {tab === 'model' && <ModelPage />}
      </main>
    </>
  )
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
