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

  const showDay = tab !== 'dashboard' && tab !== 'model'
  const strike = meta.atc_strike_days.includes(date)

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M2.5 13.5 21 6l-3.2 9.6-6.3-2.4-2.6 4.3-.6-5.3z" fill="currentColor" /></svg>
          <div>AeroOps<small>Intelligence</small></div>
        </div>
        <nav aria-label="Sections">
          {TABS.map(([k, l]) => (
            <button key={k} className={`nav ${tab === k ? 'active' : ''}`} aria-current={tab === k ? 'page' : undefined} onClick={() => setTab(k)}>
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">{ICONS[k]}</svg>{l}
            </button>
          ))}
        </nav>
        <div className="rail-foot">
          {STATIC && <p title="Données de démonstration pré-calculées ; la simulation est recalculée dans le navigateur">Démo statique · données générées</p>}
          <a href="https://github.com/stevvvvvv/AeroOps-Intelligence" target="_blank" rel="noreferrer">Code source sur GitHub</a>
        </div>
      </aside>
      <div className="stage">
        {showDay && (
          <header className="dayline">
            <div>
              <span className="dayline-label">Journée d'exploitation</span>
              <span className="dayline-date">{longDate(date)}</span>
              {strike && <span className="flag">Grève du contrôle aérien</span>}
            </div>
            <div className="daypick" role="group" aria-label="Changer de journée">
              <button onClick={() => step(-1)} disabled={meta.scored_dates.indexOf(date) === 0} aria-label="Journée précédente">‹</button>
              <select value={date} onChange={(e) => setDate(e.target.value)} aria-label="Journée d'exploitation">
                {meta.scored_dates.map((d) => <option key={d} value={d}>{d}{meta.atc_strike_days.includes(d) ? ' · grève ATC' : ''}</option>)}
              </select>
              <button onClick={() => step(1)} disabled={meta.scored_dates.indexOf(date) === meta.scored_dates.length - 1} aria-label="Journée suivante">›</button>
            </div>
          </header>
        )}
        <main>
          {tab === 'dashboard' && <Dashboard meta={meta} />}
          {tab === 'risk' && <RiskBoard date={date} meta={meta} onSimulate={openSim} />}
          {tab === 'rotations' && <Rotations date={date} onSimulate={openSim} />}
          {tab === 'sim' && <Simulator date={date} target={simTarget} />}
          {tab === 'model' && <ModelPage />}
        </main>
      </div>
    </div>
  )

  function step(n) {
    const i = meta.scored_dates.indexOf(date) + n
    if (i >= 0 && i < meta.scored_dates.length) setDate(meta.scored_dates[i])
  }
}

const longDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

const ICONS = {
  dashboard: <path d="M4 19h16M7 16V9m5 7V5m5 11v-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />,
  risk: <path d="M12 4 3 19h18L12 4Zm0 6v4m0 2.5v.5" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" fill="none" />,
  rotations: <path d="M4 7h7M8 12h9M5 17h11" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />,
  sim: <path d="M5 5v14m0-7h6l3-5h5M14 12l3 5h2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />,
  model: <path d="M6 18a3 3 0 1 1 0-6m0 0a3 3 0 1 1 6 0m-6 0h6m0 0a3 3 0 1 1 6 0 3 3 0 0 1-6 0Zm6 0V6" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" />,
}

createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
