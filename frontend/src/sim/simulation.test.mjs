// Vérifie que le simulateur JS reproduit exactement les résultats Python.
// Usage : node src/sim/simulation.test.mjs <dossier data exporté> <reference.json>
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { DisruptionSimulator } from './simulation.js'

const [dataDir, refPath] = process.argv.slice(2)
const reference = JSON.parse(readFileSync(refPath, 'utf8'))
const meta = JSON.parse(readFileSync(join(dataDir, 'meta.json'), 'utf8'))
const cache = new Map()

const norm = (r) => JSON.stringify(r, (k, v) => (k === 'sched_dep' || k === 'sched_arr' ? v.slice(0, 16) : v))
let failures = 0
for (const ref of reference) {
  const date = `${ref.flight_id.slice(-8, -4)}-${ref.flight_id.slice(-4, -2)}-${ref.flight_id.slice(-2)}`
  if (!cache.has(date)) {
    const d = JSON.parse(readFileSync(join(dataDir, 'sim', `${date}.json`), 'utf8'))
    cache.set(date, new DisruptionSimulator(d.legs, d.aircraft, meta.ops_params))
  }
  const got = cache.get(date).simulate(ref.flight_id, ref.initial_delay_min)
  if (norm(got) !== norm(ref)) {
    failures++
    if (failures <= 3) {
      console.error(`ÉCART ${ref.flight_id} retard ${ref.initial_delay_min}`)
      console.error(' python :', ref.scenarios.map((s) => `${s.key}=${s.total_cost}`).join(' '))
      console.error(' js     :', got.scenarios.map((s) => `${s.key}=${s.total_cost}`).join(' '))
    }
  }
}
console.log(`${reference.length - failures}/${reference.length} simulations identiques à Python`)
process.exit(failures ? 1 : 0)
