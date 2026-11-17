const get = async (path, params = {}) => {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '')).toString()
  const r = await fetch(`/api${path}${qs ? `?${qs}` : ''}`)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}
const post = async (path, body) => {
  const r = await fetch(`/api${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  meta: () => get('/meta'),
  kpis: (start, end) => get('/kpis', { start, end }),
  flights: (date, model, airport) => get('/flights', { date, model, airport }),
  explain: (id, model) => get(`/flights/${id}/explain`, { model }),
  rotations: (date, model) => get('/rotations', { date, model }),
  simulate: (flight_id, delay_min) => post('/simulate', { flight_id, delay_min }),
  report: () => get('/model/report'),
}

export const fmt = {
  pct: (v, d = 1) => (v == null ? '–' : `${(v * 100).toFixed(d)} %`),
  min: (v) => (v == null ? '–' : `${Math.round(v)} min`),
  eur: (v) => (v == null ? '–' : `${Math.round(v).toLocaleString('fr-FR')} €`),
  time: (iso) => (iso ? iso.slice(11, 16) : '–'),
  int: (v) => (v == null ? '–' : Math.round(v).toLocaleString('fr-FR')),
}

// Statut d'un retard : couleur + libellé (jamais la couleur seule)
export const delayStatus = (m) => {
  if (m == null) return { color: '#c3c2b7', label: 'n/d' }
  if (m < 15) return { color: 'var(--good)', label: "À l'heure" }
  if (m < 60) return { color: 'var(--warning)', label: 'Retard' }
  if (m < 180) return { color: 'var(--serious)', label: 'Retard important' }
  return { color: 'var(--critical)', label: '≥ 3 h (EU261)' }
}
