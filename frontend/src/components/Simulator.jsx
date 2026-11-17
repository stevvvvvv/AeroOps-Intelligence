import { useEffect, useState } from 'react'
import { api, delayStatus, fmt } from '../api'

const COST_LABELS = { retards: 'Minutes de retard', eu261: 'Indemnités EU261', annulations: 'Annulations', couvre_feu: 'Couvre-feu', action: "Coût de l'action" }

export default function Simulator({ date, target }) {
  const [flights, setFlights] = useState([])
  const [flightId, setFlightId] = useState(target?.flight_id ?? '')
  const [delay, setDelay] = useState(target?.delay ?? 60)
  const [res, setRes] = useState(null)
  const [sel, setSel] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    api.flights(date, 'tactical').then((r) => {
      const sorted = [...r].sort((a, b) => a.sched_dep.localeCompare(b.sched_dep))
      setFlights(sorted)
      // par défaut : le vol du matin le plus à risque (longue rotation en aval -> cascade visible)
      const morning = r.filter((f) => f.sched_dep.slice(11, 13) < '11')
      if (!sorted.find((f) => f.flight_id === flightId)) setFlightId((morning[0] ?? r[0])?.flight_id ?? '')
    })
  }, [date])
  useEffect(() => { if (target) { setFlightId(target.flight_id); setDelay(target.delay) } }, [target])

  const run = () => {
    if (!flightId) return
    setLoading(true)
    api.simulate(flightId, delay).then((r) => { setRes(r); setSel(r.recommended) }).finally(() => setLoading(false))
  }
  useEffect(run, [flightId])

  const f = flights.find((x) => x.flight_id === flightId)
  const scen = res?.scenarios.find((s) => s.key === sel)
  const base = res?.scenarios.find((s) => s.key === 'no_action')

  return (
    <>
      <h2>Simulation de scénarios de réorganisation</h2>
      <p className="sub">Injecter un retard sur un vol, mesurer la cascade sur les rotations et comparer les décisions possibles du centre de contrôle des opérations.</p>
      <div className="filters">
        <label>Vol perturbé<select value={flightId} onChange={(e) => setFlightId(e.target.value)} style={{ minWidth: 300 }}>
          {flights.map((x) => <option key={x.flight_id} value={x.flight_id}>{fmt.time(x.sched_dep)} · {x.flight_number} {x.origin}→{x.dest} · {x.tail_number}</option>)}
        </select></label>
        <label>Retard initial au départ : <b style={{ color: 'var(--ink)' }}>{delay} min</b>
          <input type="range" min={15} max={300} step={5} value={delay} onChange={(e) => setDelay(+e.target.value)} style={{ width: 260 }} /></label>
        <button className="btn" onClick={run} disabled={loading}>{loading ? 'Calcul…' : 'Simuler'}</button>
        {f && <span className="badge">Retard prédit par le modèle : {fmt.min(f.pred_delay_min)} ({fmt.pct(f.prob_delay15, 0)})</span>}
      </div>

      {res && (
        <>
          <div className="grid scen-grid">
            {res.scenarios.map((s) => (
              <div key={s.key} className={`scen ${s.key === res.recommended ? 'best' : ''} ${s.key === sel ? 'sel' : ''} ${s.feasible ? '' : 'off'}`}
                onClick={() => s.feasible && setSel(s.key)}>
                <div className="scen-head">
                  {s.key === res.recommended && <span className="scen-reco">✓ Recommandé</span>}
                  <b>{s.label}</b>
                </div>
                {s.feasible ? <>
                  <div className="cost">{fmt.eur(s.total_cost)}</div>
                  <div className="meta"><span>{fmt.int(s.total_delay_min)} min cumulées</span><span>{s.flights_impacted} vols ≥ 15 min</span>
                    {s.flights_cancelled > 0 && <span>{s.flights_cancelled} annulés</span>}{s.pax_eu261 > 0 && <span>{s.pax_eu261} pax EU261</span>}</div>
                  {s.key !== 'no_action' && s.saving_vs_no_action != null && (
                    <div style={{ fontSize: 12, marginTop: 6, color: s.saving_vs_no_action > 0 ? '#006300' : 'var(--critical)' }}>
                      {s.saving_vs_no_action > 0 ? '▼ ' : '▲ '}{fmt.eur(Math.abs(s.saving_vs_no_action))} vs aucune action</div>)}
                </> : <p className="hint" style={{ marginTop: 8 }}>{s.description}</p>}
              </div>
            ))}
          </div>

          {scen && (
            <div className="grid g32" style={{ alignItems: 'start' }}>
              <div className="card">
                <h3>{scen.label}</h3>
                <p className="hint">{scen.description}</p>
                <CascadeChart base={base} scen={scen} />
                <table className="nowrap" style={{ marginTop: 12 }}>
                  <thead><tr><th>Vol</th><th>Ligne</th><th>Avion</th><th>Départ prévu</th><th className="num">Retard départ</th><th className="num">Retard arrivée</th><th>Statut</th></tr></thead>
                  <tbody>{scen.legs.map((l) => {
                    const st = l.status === 'cancelled' ? { color: 'var(--critical)', label: 'Annulé' } : delayStatus(l.arr_delay)
                    return (
                      <tr key={l.flight_id + l.tail_number}>
                        <td><b>{l.flight_number}</b></td><td>{l.origin} → {l.dest}</td>
                        <td>{l.tail_number}{l.tail_number !== l.original_tail && <span style={{ color: 'var(--muted)' }}> (ex {l.original_tail})</span>}</td>
                        <td>{fmt.time(l.sched_dep)}</td>
                        <td className="num">{l.status === 'cancelled' ? '–' : fmt.min(l.dep_delay)}</td>
                        <td className="num">{l.status === 'cancelled' ? '–' : fmt.min(l.arr_delay)}</td>
                        <td><span className="badge"><i className="dot" style={{ background: st.color }} />{st.label}</span></td>
                      </tr>
                    )
                  })}</tbody>
                </table>
              </div>
              <div className="card">
                <h3>Décomposition du coût</h3>
                <p className="hint">Hypothèses : 100 €/min de retard, barème EU261 (250/400/600 €), 150 €/pax annulé, coefficient de remplissage 85 %</p>
                <table><tbody>
                  {Object.entries(scen.costs).map(([k, v]) => (
                    <tr key={k}><td>{COST_LABELS[k]}</td><td className="num">{fmt.eur(v)}</td><td className="num" style={{ color: 'var(--muted)' }}>{fmt.eur(base.costs[k])}</td></tr>
                  ))}
                  <tr><td><b>Total</b></td><td className="num"><b>{fmt.eur(scen.total_cost)}</b></td><td className="num" style={{ color: 'var(--muted)' }}>{fmt.eur(base.total_cost)}</td></tr>
                </tbody></table>
                <p className="hint" style={{ marginTop: 10 }}>Colonne grise : scénario « Aucune action ». Non modélisé : légalité des équipages (FTL), correspondances passagers.</p>
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}

function CascadeChart({ base, scen }) {
  // Retard à l'arrivée par leg, dans l'ordre chronologique : sans action vs scénario
  const legs = scen.legs.map((l, i) => ({ ...l, i }))
  const single = scen.key === 'no_action'
  const baseBy = Object.fromEntries(base.legs.map((l) => [l.flight_id, l.arr_delay]))
  const max = Math.max(60, ...legs.map((l) => l.arr_delay), ...base.legs.map((l) => l.arr_delay))
  const W = 560, H = 170, pad = 30, bw = Math.min(18, (W - pad) / legs.length / 2.6)
  const step = (W - pad) / legs.length
  return (
    <div>
      <div className="legend"><span><i className="dot" style={{ background: 'var(--s1)' }} />Aucune action</span>{!single && <span><i className="dot" style={{ background: 'var(--s2)' }} />{scen.label}</span>}</div>
      <svg viewBox={`0 0 ${W} ${H + 24}`} width="100%">
        {[0, 0.5, 1].map((t) => (
          <g key={t}><line x1={pad} x2={W} y1={H - t * (H - 10)} y2={H - t * (H - 10)} stroke="var(--grid)" />
            <text x={pad - 4} y={H - t * (H - 10) + 4} fontSize={10} fill="var(--muted)" textAnchor="end">{Math.round(t * max)}</text></g>
        ))}
        {legs.map((l) => {
          const cx = pad + step * l.i + step / 2
          const b = baseBy[l.flight_id] ?? 0
          const s = l.status === 'cancelled' ? 0 : l.arr_delay
          const h = (v) => (v / max) * (H - 10)
          return (
            <g key={l.flight_id + l.i}>
              <rect x={single ? cx - bw / 2 : cx - bw - 1} y={H - h(b)} width={bw} height={h(b)} rx={3} fill="var(--s1)"><title>{`${l.flight_number} sans action : ${Math.round(b)} min`}</title></rect>
              {!single && <rect x={cx + 1} y={H - h(s)} width={bw} height={h(s)} rx={3} fill={l.status === 'cancelled' ? 'none' : 'var(--s2)'} stroke={l.status === 'cancelled' ? 'var(--critical)' : 'none'} strokeDasharray="2 2">
                <title>{`${l.flight_number} scénario : ${l.status === 'cancelled' ? 'annulé' : Math.round(s) + ' min'}`}</title></rect>}
              <text x={cx} y={H + 14} fontSize={9.5} fill="var(--muted)" textAnchor="middle">{l.flight_number}</text>
            </g>
          )
        })}
        <line x1={pad} x2={W} y1={H} y2={H} stroke="var(--axis)" />
      </svg>
    </div>
  )
}
