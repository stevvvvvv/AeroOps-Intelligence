import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmt, STATIC } from '../api'

// Causes de retard : ordre catégoriel fixe (validé daltonisme en barres empilées adjacentes)
const CAUSES = [
  ['late_aircraft_min', 'Avion en retard (réactionnaire)', 'var(--s1)'],
  ['nas_min', 'ATC / capacité aéroport', 'var(--s2)'],
  ['weather_min', 'Météo', 'var(--s3)'],
  ['carrier_min', 'Compagnie / technique', 'var(--s4)'],
]
const axis = { stroke: 'var(--axis)', tick: { fill: 'var(--muted)', fontSize: 11 }, tickLine: false }

const Tip = ({ active, payload, label, unit = '' }) => active && payload?.length ? (
  <div className="tip"><b>{label}</b>{payload.map((p) => (
    <div key={p.dataKey}><span className="dot" style={{ background: p.color, marginRight: 6 }} />{p.name} : {typeof p.value === 'number' ? (unit === '%' ? fmt.pct(p.value) : `${fmt.int(p.value)}${unit}`) : p.value}</div>
  )).reverse()}</div>
) : null

function Tile({ label, value, foot }) {
  return <div className="card tile"><div className="label">{label}</div><div className="value">{value}</div><div className="foot">{foot}</div></div>
}

export default function Dashboard({ meta }) {
  const [range, setRange] = useState([meta.scored_dates[0], meta.end])
  const [k, setK] = useState(null)
  useEffect(() => { api.kpis(...range).then(setK) }, [range])

  const presets = [['14 j', meta.scored_dates[0]], ['30 j', shift(meta.end, -29)], ['Saison', meta.start]]
  if (!k) return <div className="empty">Chargement…</div>
  const g = k.kpi_global
  const daily = k.kpi_daily.map((d) => ({ ...d, date: d.flight_date.slice(5) }))

  return (
    <>
      <h2>Performance opérationnelle</h2>
      <p className="sub">Ponctualité, causes de retard et points de congestion du réseau.</p>
      <div className="filters">
        <div className="seg">{presets.map(([l, s]) => <button key={l} className={range[0] === s ? 'on' : ''} onClick={() => setRange([s, meta.end])}>{l}</button>)}</div>
        {!STATIC && <><label>Du<input type="date" value={range[0]} min={meta.start} max={range[1]} onChange={(e) => setRange([e.target.value, range[1]])} /></label>
        <label>Au<input type="date" value={range[1]} min={range[0]} max={meta.end} onChange={(e) => setRange([range[0], e.target.value])} /></label></>}
      </div>

      <div className="grid g4" style={{ marginBottom: 16 }}>
        <Tile label="Ponctualité à l'arrivée (OTP15)" value={fmt.pct(g.otp15)} foot={`${fmt.int(g.flights)} vols opérés`} />
        <Tile label="Retard moyen au départ" value={fmt.min(g.avg_dep_delay)} foot={`${fmt.int(g.total_delay_min)} min de retard cumulées`} />
        <Tile label="Part du retard réactionnaire" value={fmt.pct(g.reactionary_share, 0)} foot="Minutes causées par un avion arrivé en retard" />
        <Tile label="Vols ≥ 3 h de retard" value={fmt.int(g.flights_over_3h)} foot="Éligibles à indemnisation EU261" />
      </div>

      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Ponctualité quotidienne (OTP15)</h3>
          <p className="hint">Part des vols arrivés avec moins de 15 min de retard · ligne pointillée : objectif 80 %</p>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={daily} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" {...axis} minTickGap={24} />
              <YAxis {...axis} domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} axisLine={false} />
              <ReferenceLine y={0.8} stroke="var(--muted)" strokeDasharray="4 4" />
              <Tooltip content={<Tip unit="%" />} />
              <Line type="linear" dataKey="otp15" name="OTP15" stroke="var(--s1)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Minutes de retard par cause</h3>
          <p className="hint">Codification BTS · le retard réactionnaire domine : c'est l'effet cascade</p>
          <div className="legend">{CAUSES.map(([, l, c]) => <span key={l}><i className="dot" style={{ background: c }} />{l}</span>)}</div>
          <ResponsiveContainer width="100%" height={216}>
            <BarChart data={daily} margin={{ top: 4, right: 12, left: -4, bottom: 0 }} barCategoryGap={2}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="date" {...axis} minTickGap={24} />
              <YAxis {...axis} axisLine={false} />
              <Tooltip content={<Tip unit=" min" />} cursor={{ fill: '#f0efec' }} />
              {CAUSES.map(([key, l, c], i) => (
                <Bar key={key} dataKey={key} name={l} stackId="c" fill={c} stroke="var(--surface)" strokeWidth={1}
                  radius={i === CAUSES.length - 1 ? [3, 3, 0, 0] : 0} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid g2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h3>Risque de retard selon l'heure de départ</h3>
          <p className="hint">Part des départs ≥ 15 min · le retard s'accumule au fil de la journée</p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={k.kpi_by_hour} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="hour" {...axis} tickFormatter={(h) => `${h}h`} />
              <YAxis {...axis} axisLine={false} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
              <Tooltip content={<Tip unit="%" />} cursor={{ fill: '#f0efec' }} labelFormatter={(h) => `${h}h`} />
              <Bar dataKey="delay15_rate" name="Départs ≥ 15 min" fill="var(--s1)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h3>Aéroports de départ</h3>
          <p className="hint">Classés par retard moyen au départ</p>
          <table>
            <thead><tr><th>Aéroport</th><th className="num">Départs</th><th className="num">OTP15 départ</th><th className="num">Retard moy.</th><th className="num">ATC min/vol</th><th className="num">Météo min/vol</th></tr></thead>
            <tbody>{k.kpi_by_airport.slice(0, 7).map((a) => (
              <tr key={a.airport}><td><b>{a.airport}</b></td><td className="num">{a.departures}</td><td className="num">{fmt.pct(a.dep_otp15, 0)}</td>
                <td className="num">{fmt.min(a.avg_dep_delay)}</td><td className="num">{a.nas_min_per_flight?.toFixed(1)}</td><td className="num">{a.weather_min_per_flight?.toFixed(1)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>

      <div className="grid g2">
        <div className="card">
          <h3>Lignes les moins ponctuelles</h3>
          <table>
            <thead><tr><th>Ligne</th><th className="num">Vols</th><th className="num">Retard moy. arrivée</th><th className="num">Vols ≥ 15 min</th></tr></thead>
            <tbody>{k.kpi_worst_routes.map((r) => (
              <tr key={r.origin + r.dest}><td>{r.origin} → {r.dest}</td><td className="num">{r.flights}</td><td className="num">{fmt.min(r.avg_arr_delay)}</td><td className="num">{fmt.pct(r.delay15_rate, 0)}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <div className="card">
          <h3>Avions les plus exposés à la cascade</h3>
          <table>
            <thead><tr><th>Immatriculation</th><th className="num">Legs</th><th className="num">Retard réactionnaire</th><th className="num">Legs ≥ 15 min</th></tr></thead>
            <tbody>{k.kpi_tails.map((t) => (
              <tr key={t.tail_number}><td>{t.tail_number}</td><td className="num">{t.legs}</td><td className="num">{fmt.int(t.reactionary_min)} min</td><td className="num">{fmt.pct(t.delay15_rate, 0)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </div>
    </>
  )
}

function shift(iso, days) {
  const d = new Date(iso); d.setDate(d.getDate() + days); return d.toISOString().slice(0, 10)
}
