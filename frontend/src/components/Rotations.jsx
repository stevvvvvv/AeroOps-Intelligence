import { useEffect, useState } from 'react'
import { api, delayStatus, fmt } from '../api'

const H0 = 5, H1 = 25          // fenêtre affichée : 05h -> 01h
const LEFT = 92, ROW = 30, PX_PER_H = 64

const toH = (iso) => { const d = new Date(iso); return d.getHours() + d.getMinutes() / 60 }
const x = (h) => LEFT + (h - H0) * PX_PER_H

export default function Rotations({ date, onSimulate }) {
  const [data, setData] = useState(null)
  const [hover, setHover] = useState(null)
  const [sort, setSort] = useState('tail')
  useEffect(() => { setData(null); api.rotations(date).then(setData) }, [date])
  if (!data) return <div className="empty">Chargement…</div>

  const tails = [...data.tails].sort((a, b) => sort === 'delay' ? b.reactionary_min - a.reactionary_min : a.tail_number.localeCompare(b.tail_number))
  const W = x(H1) + 10, H = tails.length * ROW + 30

  return (
    <>
      <h2>Rotations des avions</h2>
      <p className="sub">Programme (contour) et réalisé (bloc plein) de chaque appareil · cliquer un vol pour simuler une perturbation.</p>
      <div className="filters">
        <div className="seg"><button className={sort === 'tail' ? 'on' : ''} onClick={() => setSort('tail')}>Par immatriculation</button>
          <button className={sort === 'delay' ? 'on' : ''} onClick={() => setSort('delay')}>Plus retardés d'abord</button></div>
        <div className="legend" style={{ margin: 0 }}>
          {[0, 30, 90, 200].map((m) => { const s = delayStatus(m); return <span key={m}><i className="dot" style={{ background: s.color }} />{s.label}</span> })}
          <span><i style={{ width: 14, height: 8, border: '1.5px solid var(--ink-2)', display: 'inline-block', borderRadius: 2 }} />Créneau programmé</span>
        </div>
        <span className="badge">Réserves : {data.spares.map((s) => `${s.tail_number} (${s.base})`).join(', ')}</span>
      </div>
      <div className="card gantt-wrap" style={{ position: 'relative' }}>
        <svg width={W} height={H} style={{ display: 'block' }}>
          {Array.from({ length: H1 - H0 + 1 }, (_, i) => H0 + i).map((h) => (
            <g key={h}>
              <line x1={x(h)} x2={x(h)} y1={20} y2={H} stroke="var(--grid)" />
              <text x={x(h)} y={12} fontSize={11} fill="var(--muted)" textAnchor="middle">{`${h % 24}h`}</text>
            </g>
          ))}
          {tails.map((t, i) => {
            const y = 24 + i * ROW
            return (
              <g key={t.tail_number}>
                <text x={8} y={y + 15} fontSize={12} fill="var(--ink)">{t.tail_number}</text>
                <text x={8} y={y + 26} fontSize={9} fill="var(--muted)">{t.ac_type} · {t.base}</text>
                {t.legs.map((l) => {
                  const s0 = toH(l.sched_dep), s1 = toH(l.sched_arr)
                  const a0 = s0 + (l.dep_delay ?? 0) / 60, a1 = s1 + (l.arr_delay ?? 0) / 60
                  const st = delayStatus(l.arr_delay)
                  return (
                    <g key={l.flight_id} style={{ cursor: 'pointer' }}
                      onMouseEnter={(e) => setHover({ l, t, st, px: x(a0), py: y })} onMouseLeave={() => setHover(null)}
                      onClick={() => onSimulate(l.flight_id, l.pred_delay_min ?? l.dep_delay)}>
                      <rect x={x(s0)} y={y + 3} width={Math.max((s1 - s0) * PX_PER_H, 2)} height={20} rx={4} fill="none" stroke="var(--ink-2)" strokeWidth={1.2} strokeDasharray="3 2" />
                      <rect x={x(a0)} y={y + 6} width={Math.max((a1 - a0) * PX_PER_H, 2)} height={14} rx={4} fill={st.color} stroke="var(--surface)" strokeWidth={1} />
                      {(a1 - a0) * PX_PER_H > 46 && <text x={x(a0) + 4} y={y + 17} fontSize={9.5} fill={l.arr_delay >= 180 ? '#fff' : 'var(--ink)'}>{l.dest}</text>}
                    </g>
                  )
                })}
              </g>
            )
          })}
        </svg>
        {hover && (
          <div className="tip" style={{ position: 'absolute', left: Math.min(hover.px + 30, W - 220), top: hover.py + 40, pointerEvents: 'none', width: 220 }}>
            <b>{hover.l.flight_number} · {hover.l.origin} → {hover.l.dest}</b>
            <div>{hover.t.tail_number} · prévu {fmt.time(hover.l.sched_dep)}–{fmt.time(hover.l.sched_arr)}</div>
            <div>Retard départ {fmt.min(hover.l.dep_delay)} · arrivée {fmt.min(hover.l.arr_delay)}</div>
            <div>Prédiction : {fmt.min(hover.l.pred_delay_min)} ({fmt.pct(hover.l.prob_delay15, 0)} de risque)</div>
            <div style={{ color: 'var(--muted)', marginTop: 4 }}>{hover.st.label} · cliquer pour simuler</div>
          </div>
        )}
      </div>
    </>
  )
}
