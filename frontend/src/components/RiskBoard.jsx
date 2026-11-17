import { useEffect, useMemo, useState } from 'react'
import { api, delayStatus, fmt } from '../api'

const MODELS = [['tactical', 'Tactique (H-2)'], ['strategic', 'Stratégique (J-1)']]

function ProbCell({ p }) {
  const color = p >= 0.7 ? 'var(--critical)' : p >= 0.4 ? 'var(--serious)' : 'var(--s1)'
  return <><span className="probbar"><i style={{ width: `${(p ?? 0) * 100}%`, background: color }} /></span>{fmt.pct(p, 0)}</>
}

function Explain({ flight, model, onSimulate }) {
  const [e, setE] = useState(null)
  useEffect(() => { setE(null); api.explain(flight.flight_id, model).then(setE) }, [flight.flight_id, model])
  if (!e) return <div className="card"><div className="empty">Calcul des facteurs…</div></div>
  const max = Math.max(...e.factors.map((f) => Math.abs(f.minutes)), 1)
  const ev = e.evidence
  return (
    <div className="card">
      <h3>{e.flight.flight_number} · {e.flight.origin} → {e.flight.dest} · {e.flight.tail_number}</h3>
      <p className="hint">Départ prévu {fmt.time(flight.sched_dep)} · décomposition SHAP du retard prédit</p>
      <div style={{ display: 'flex', gap: 24, margin: '6px 0 14px' }}>
        <div><div className="hint" style={{ margin: 0 }}>Retard prédit</div><div style={{ fontSize: 26, fontWeight: 650 }}>{fmt.min(e.pred_delay_min)}</div></div>
        <div><div className="hint" style={{ margin: 0 }}>P(retard ≥ 15 min)</div><div style={{ fontSize: 26, fontWeight: 650 }}>{fmt.pct(e.prob_delay15, 0)}</div></div>
        <div><div className="hint" style={{ margin: 0 }}>Réalisé</div><div style={{ fontSize: 26, fontWeight: 650, color: 'var(--ink-2)' }}>{fmt.min(e.actual_dep_delay)}</div></div>
      </div>
      <div className="legend"><span><i className="dot" style={{ background: 'var(--s2)' }} />ajoute du retard</span><span><i className="dot" style={{ background: 'var(--s1)' }} />en retire</span><span>Point de départ (moyenne réseau) : {fmt.min(e.base_min)}</span></div>
      {e.factors.map((f) => (
        <div key={f.factor} style={{ display: 'grid', gridTemplateColumns: '210px 1fr 64px', alignItems: 'center', gap: 10, margin: '7px 0' }}>
          <span style={{ fontSize: 13 }}>{f.factor}</span>
          <div style={{ position: 'relative', height: 14 }}>
            <div style={{ position: 'absolute', left: '50%', top: -2, bottom: -2, width: 1, background: 'var(--axis)' }} />
            <div style={{ position: 'absolute', height: 14, borderRadius: 4, background: f.minutes >= 0 ? 'var(--s2)' : 'var(--s1)',
              left: f.minutes >= 0 ? '50%' : `${50 - (Math.abs(f.minutes) / max) * 50}%`, width: `${(Math.abs(f.minutes) / max) * 50}%` }} />
          </div>
          <span style={{ textAlign: 'right', fontSize: 13 }}>{f.minutes > 0 ? '+' : ''}{f.minutes.toFixed(1)}</span>
        </div>
      ))}
      <h3 style={{ marginTop: 16 }}>Éléments observés</h3>
      <table style={{ fontSize: 13 }}><tbody>
        <tr><td>Retard au départ du leg entrant</td><td className="num">{ev.prev_leg_dep_delay == null ? '1er vol de la journée' : fmt.min(ev.prev_leg_dep_delay)}</td></tr>
        <tr><td>Marge de rotation (au-delà du demi-tour mini)</td><td className="num">{ev.turn_slack_min == null ? '–' : fmt.min(ev.turn_slack_min)}</td></tr>
        <tr><td>Sévérité météo départ / arrivée</td><td className="num">{ev.o_sev?.toFixed(1)} / {ev.d_sev?.toFixed(1)}{(ev.o_thunderstorm || ev.d_thunderstorm) ? ' · orage' : ''}</td></tr>
        <tr><td>Visibilité au départ</td><td className="num">{ev.o_visibility_km} km</td></tr>
        <tr><td>Retard moyen de la ligne (28 j)</td><td className="num">{fmt.min(ev.route_mean_arr_delay_28d)}</td></tr>
      </tbody></table>
      <div style={{ marginTop: 14 }}><button className="btn" onClick={() => onSimulate(flight.flight_id, e.pred_delay_min)}>Simuler l'impact sur les rotations →</button></div>
    </div>
  )
}

export default function RiskBoard({ date, meta, onSimulate }) {
  const [model, setModel] = useState('tactical')
  const [airport, setAirport] = useState('')
  const [rows, setRows] = useState(null)
  const [sel, setSel] = useState(null)
  useEffect(() => { setRows(null); api.flights(date, model, airport).then((r) => { setRows(r); setSel(r[0] ?? null) }) }, [date, model, airport])

  const stats = useMemo(() => rows && {
    high: rows.filter((r) => r.prob_delay15 >= 0.7).length,
    hits: rows.filter((r) => r.prob_delay15 >= 0.5 && r.dep_delay >= 15).length,
    flagged: rows.filter((r) => r.prob_delay15 >= 0.5).length,
  }, [rows])

  return (
    <>
      <h2>Vols à risque</h2>
      <p className="sub">Probabilité de retard ≥ 15 min et facteurs explicatifs, vol par vol.</p>
      <div className="filters">
        <div className="seg">{MODELS.map(([k, l]) => <button key={k} className={model === k ? 'on' : ''} onClick={() => setModel(k)}>{l}</button>)}</div>
        <label>Aéroport<select value={airport} onChange={(e) => setAirport(e.target.value)}>
          <option value="">Tous</option>{meta.airports.map((a) => <option key={a.iata} value={a.iata}>{a.iata} – {a.name}</option>)}
        </select></label>
        {stats && <span className="badge">{stats.high} vols à risque élevé (≥ 70 %) · {stats.hits}/{stats.flagged} alertes confirmées</span>}
      </div>
      {!rows ? <div className="empty">Chargement…</div> : (
        <div className="grid g32" style={{ alignItems: 'start' }}>
          <div className="card" style={{ maxHeight: 760, overflow: 'auto', padding: 0 }}>
            <table>
              <thead style={{ position: 'sticky', top: 0, background: 'var(--surface)' }}><tr>
                <th>Vol</th><th>Ligne</th><th>Départ</th><th>Risque</th><th className="num">Prédit</th><th>Facteur principal</th><th className="num">Réalisé</th>
              </tr></thead>
              <tbody>{rows.map((r) => {
                const st = delayStatus(r.dep_delay)
                return (
                  <tr key={r.flight_id} className={`click ${sel?.flight_id === r.flight_id ? 'sel' : ''}`} onClick={() => setSel(r)}>
                    <td><b>{r.flight_number}</b><div style={{ fontSize: 11, color: 'var(--muted)' }}>{r.tail_number}</div></td>
                    <td>{r.origin} → {r.dest}</td><td>{fmt.time(r.sched_dep)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}><ProbCell p={r.prob_delay15} /></td>
                    <td className="num">{fmt.min(r.pred_delay_min)}</td>
                    <td style={{ fontSize: 12 }}>{r.top_factor}</td>
                    <td className="num"><span className="badge" title={st.label}><i className="dot" style={{ background: st.color }} />{fmt.min(r.dep_delay)}</span></td>
                  </tr>
                )
              })}</tbody>
            </table>
          </div>
          {sel && <Explain flight={sel} model={model} onSimulate={onSimulate} />}
        </div>
      )}
    </>
  )
}
