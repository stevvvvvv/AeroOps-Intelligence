// Deux modes :
// - normal : appels à l'API FastAPI ;
// - statique (VITE_STATIC=1, démo Hugging Face) : JSON pré-calculés par
//   scripts/export_static.py, simulation recalculée dans le navigateur.
export const STATIC = import.meta.env.VITE_STATIC === '1'

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

const apiLive = {
  meta: () => get('/meta'),
  kpis: (start, end) => get('/kpis', { start, end }),
  flights: (date, model, airport) => get('/flights', { date, model, airport }),
  explain: (id, model) => get(`/flights/${id}/explain`, { model }),
  rotations: (date, model) => get('/rotations', { date, model }),
  simulate: (flight_id, delay_min) => post('/simulate', { flight_id, delay_min }),
  report: () => get('/model/report'),
}

// ----------------------------------------------------------------- mode statique
const files = new Map()
const json = (rel) => {
  if (!files.has(rel)) {
    files.set(rel, fetch(`${import.meta.env.BASE_URL}data/${rel}`).then((r) => {
      if (!r.ok) throw new Error(`Donnée indisponible dans la démo statique (${rel})`)
      return r.json()
    }))
  }
  return files.get(rel)
}
const dateOf = (flightId) => { const d = flightId.slice(-8); return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` }
const simulators = new Map()

const apiStatic = {
  meta: () => json('meta.json'),
  kpis: (start, end) => json(`kpis/${start}_${end}.json`),
  flights: async (date, model, airport) => {
    const rows = await json(`flights/${date}_${model}.json`)
    return airport ? rows.filter((r) => r.origin === airport || r.dest === airport) : rows
  },
  explain: async (id, model) => (await json(`explain/${dateOf(id)}_${model}.json`))[id],
  rotations: (date) => json(`rotations/${date}.json`),
  simulate: async (flightId, delay) => {
    const date = dateOf(flightId)
    if (!simulators.has(date)) {
      const [{ DisruptionSimulator }, data, meta] = await Promise.all([import('./sim/simulation.js'), json(`sim/${date}.json`), json('meta.json')])
      simulators.set(date, new DisruptionSimulator(data.legs, data.aircraft, meta.ops_params))
    }
    return simulators.get(date).simulate(flightId, delay)
  },
  report: () => json('model/report.json'),
}

export const api = STATIC ? apiStatic : apiLive

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
