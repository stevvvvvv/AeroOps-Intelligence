// Port JavaScript de src/aeroops/ops/simulation.py, pour la démo statique.
// Toute modification de la logique Python doit être reportée ici :
// simulation.test.mjs vérifie l'équivalence sur un échantillon de cas.

export const DEFAULT_OPS = {
  min_turn_min: 35, quick_turn_min: 25, enroute_recovery_min: 4.0, otp_threshold_min: 15,
  cost_per_delay_min: 100.0, cancel_cost_per_pax: 150.0, spare_aircraft_cost: 12000.0,
  quick_turn_cost: 1500.0, swap_cost: 2000.0, curfew_penalty: 25000.0, load_factor: 0.85, seats: 180,
}
const CURFEWS = { ORY: '23:30' }
const EU261_THRESHOLD_MIN = 180
const MIN = 60000

const eu261Amount = (km) => (km <= 1500 ? 250 : km <= 3500 ? 400 : 600)
const ts = (iso) => Date.parse(`${iso.slice(0, 16)}:00Z`) // heures "naïves" traitées en UTC
const iso = (t) => new Date(t).toISOString().slice(0, 16)
const pyRound = (x) => { // arrondi bancaire, comme round() en Python
  const r = Math.round(x)
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r
}
const sum = (a) => a.reduce((s, v) => s + v, 0)

function makeLeg(r, ops) {
  return { flight_id: r.flight_id, flight_number: r.flight_number, tail: r.tail_number, origin: r.origin, dest: r.dest,
    dep: ts(r.sched_dep), arr: ts(r.sched_arr), distance_km: +r.distance_km, seats: +(r.seats || ops.seats), own: 0 }
}

function propagate(chain, tail, initial, ops, minTurn = ops.min_turn_min, readyBeforeFirst = null) {
  const out = []
  let prev = null
  chain.forEach((leg, k) => {
    let dep
    if (k === 0) {
      dep = Math.max(initial, leg.own)
      if (readyBeforeFirst !== null) dep = Math.max(dep, readyBeforeFirst)
    } else {
      const slack = (leg.dep - prev.leg.arr) / MIN - minTurn
      dep = Math.max(leg.own, prev.arr_delay - slack, 0)
    }
    const arr = dep > 0 ? Math.max(dep - ops.enroute_recovery_min, 0) : 0
    prev = { leg, tail, dep_delay: dep, arr_delay: arr, status: tail === leg.tail ? 'operated' : 'reassigned' }
    out.push(prev)
  })
  return out
}

function breachesCurfew(r) {
  const c = CURFEWS[r.leg.dest]
  if (!c) return false
  const [hh, mm] = c.split(':').map(Number)
  const day = Math.floor(r.leg.arr / 86400000) * 86400000
  return r.leg.arr + r.arr_delay * MIN > day + (hh * 60 + mm) * MIN
}

function summary(s, ops) {
  const pax = (r) => r.leg.seats * ops.load_factor
  const op = s.legs.filter((r) => r.status !== 'cancelled')
  const cancelled = s.legs.filter((r) => r.status === 'cancelled')
  const delayCost = sum(op.map((r) => Math.max(r.arr_delay, 0))) * ops.cost_per_delay_min
  const eu261 = sum(op.filter((r) => r.arr_delay >= EU261_THRESHOLD_MIN).map((r) => pax(r) * eu261Amount(r.leg.distance_km)))
    + sum(cancelled.map((r) => pax(r) * eu261Amount(r.leg.distance_km)))
  const cancelCost = sum(cancelled.map((r) => pax(r) * ops.cancel_cost_per_pax))
  const curfew = op.filter(breachesCurfew)
  const costs = { retards: delayCost, eu261, annulations: cancelCost, couvre_feu: curfew.length * ops.curfew_penalty, action: s.action_cost }
  return {
    key: s.key, label: s.label, description: s.description, feasible: s.feasible,
    total_delay_min: pyRound(sum(op.map((r) => Math.max(r.arr_delay, 0)))),
    flights_impacted: op.filter((r) => r.arr_delay >= ops.otp_threshold_min).length,
    pax_delayed15: pyRound(sum(op.filter((r) => r.arr_delay >= ops.otp_threshold_min).map(pax))),
    pax_eu261: pyRound(sum(op.filter((r) => r.arr_delay >= EU261_THRESHOLD_MIN).map(pax)) + sum(cancelled.map(pax))),
    flights_cancelled: cancelled.length, curfew_breaches: curfew.length,
    costs: Object.fromEntries(Object.entries(costs).map(([k, v]) => [k, pyRound(v)])),
    total_cost: pyRound(sum(Object.values(costs))),
    legs: s.legs.map((r) => ({
      flight_id: r.leg.flight_id, flight_number: r.leg.flight_number, tail_number: r.tail, original_tail: r.leg.tail,
      origin: r.leg.origin, dest: r.leg.dest, sched_dep: iso(r.leg.dep), sched_arr: iso(r.leg.arr),
      dep_delay: pyRound(r.dep_delay), arr_delay: pyRound(r.arr_delay), status: r.status,
    })),
  }
}

const scenario = (key, label, description, extra = {}) => ({ key, label, description, feasible: true, legs: [], action_cost: 0, ...extra })

export class DisruptionSimulator {
  constructor(dayLegs, aircraft, ops = DEFAULT_OPS) {
    this.ops = { ...DEFAULT_OPS, ...ops }
    const legs = dayLegs.map((r) => makeLeg(r, this.ops))
      .sort((a, b) => (a.tail < b.tail ? -1 : a.tail > b.tail ? 1 : a.dep - b.dep))
    this.byTail = new Map()
    for (const l of legs) {
      if (!this.byTail.has(l.tail)) this.byTail.set(l.tail, [])
      this.byTail.get(l.tail).push(l)
    }
    this.aircraft = new Map(aircraft.map((a) => [a.tail_number, a]))
    this.spares = aircraft.filter((a) => a.is_spare === 1)
  }

  locate(flightId) {
    for (const [tail, chain] of this.byTail) {
      const i = chain.findIndex((l) => l.flight_id === flightId)
      if (i >= 0) return [tail, i]
    }
    throw new Error(`Vol ${flightId} introuvable pour cette journée`)
  }

  noAction(tail, i, d) {
    return scenario('no_action', 'Aucune action', 'Le retard est absorbé uniquement par les marges de rotation.',
      { legs: propagate(this.byTail.get(tail).slice(i), tail, d, this.ops) })
  }

  quickTurn(tail, i, d) {
    const o = this.ops
    const s = scenario('quick_turn', 'Demi-tours accélérés',
      `Moyens sol renforcés : demi-tour ramené de ${o.min_turn_min} à ${o.quick_turn_min} min sur les escales suivantes.`,
      { legs: propagate(this.byTail.get(tail).slice(i), tail, d, o, o.quick_turn_min) })
    const compressed = s.legs.slice(0, -1).filter((r) => r.arr_delay > 0).length
    s.action_cost = o.quick_turn_cost * Math.max(compressed, 1)
    return s
  }

  spare(tail, i, d) {
    const chain = this.byTail.get(tail)
    for (let j = i + 1; j < chain.length; j++) {
      const avail = this.spares.filter((a) => a.base === chain[j].origin)
      if (avail.length) {
        const sp = avail[0].tail_number
        return scenario('spare', `Avion de réserve ${sp}`,
          `${sp} (réserve à ${chain[j].origin}) reprend la rotation à partir du ${chain[j].flight_number}.`,
          { legs: [...propagate(chain.slice(i, j), tail, d, this.ops), ...propagate(chain.slice(j), sp, 0, this.ops)],
            action_cost: this.ops.spare_aircraft_cost })
      }
    }
    return scenario('spare', 'Avion de réserve', 'Aucun avion de réserve positionné sur la rotation.', { feasible: false })
  }

  swap(tail, i, d) {
    const o = this.ops
    const chain = this.byTail.get(tail)
    const delayed = propagate(chain.slice(i), tail, d, o)
    const seats = chain[i].seats
    let best = null
    for (let j = i + 1; j < chain.length; j++) {
      const station = chain[j].origin, tJ = chain[j].dep
      const tLate = chain[j - 1].arr + delayed[j - 1 - i].arr_delay * MIN
      for (const [t2, c2] of this.byTail) {
        if (t2 === tail || this.aircraft.get(t2).seats < seats * o.load_factor) continue
        const arrived = c2.map((l, k) => [l, k]).filter(([l]) => l.dest === station && l.arr + o.min_turn_min * MIN <= tJ)
        if (!arrived.length) continue
        const k = arrived[arrived.length - 1][1]
        if (k + 1 < c2.length && c2[k + 1].dep <= tJ) continue
        const rest2 = c2.slice(k + 1)
        if (rest2.length && rest2[0].origin !== station) continue
        const ready = rest2.length ? (tLate + o.min_turn_min * MIN - rest2[0].dep) / MIN : 0
        const s = scenario('swap', `Échange d'avion ${tail} ↔ ${t2}`,
          `À ${station}, ${t2} (au sol) prend le ${chain[j].flight_number} et la suite de la rotation ; `
          + `${tail} récupère le programme de ${t2}` + (rest2.length ? ` à partir du ${rest2[0].flight_number}.` : '.'),
          { legs: [...delayed.slice(0, j - i), ...propagate(chain.slice(j), t2, 0, o),
            ...(rest2.length ? propagate(rest2, tail, 0, o, o.min_turn_min, Math.max(ready, 0)) : [])],
            action_cost: o.swap_cost })
        const cost = summary(s, o).total_cost
        if (best === null || cost < best[0]) best = [cost, s]
      }
    }
    return best ? best[1] : scenario('swap', "Échange d'avion", 'Aucun appareil compatible disponible au sol sur la rotation.', { feasible: false })
  }

  cancelRoundTrip(tail, i, d) {
    const o = this.ops
    const chain = this.byTail.get(tail)
    for (let j = i + 1; j < chain.length - 1; j++) {
      const a = chain[j], b = chain[j + 1]
      if (a.origin === b.dest) {
        const before = propagate(chain.slice(i, j), tail, d, o)
        const after = chain.slice(j + 2)
        const last = before[before.length - 1]
        const ready = after.length ? (last.leg.arr + (last.arr_delay + o.min_turn_min) * MIN - after[0].dep) / MIN : 0
        const cancel = (leg) => ({ leg, tail, dep_delay: 0, arr_delay: 0, status: 'cancelled' })
        return scenario('cancel_rt', `Annulation ${a.flight_number}/${b.flight_number}`,
          `Annulation de l'aller-retour ${a.origin}-${a.dest}-${b.dest} pour remettre l'avion à l'heure.`,
          { legs: [...before, cancel(a), cancel(b), ...(after.length ? propagate(after, tail, 0, o, o.min_turn_min, Math.max(ready, 0)) : [])] })
      }
    }
    return scenario('cancel_rt', 'Annulation aller-retour', "Pas d'aller-retour annulable après ce vol.", { feasible: false })
  }

  simulate(flightId, delayMin) {
    const [tail, i] = this.locate(flightId)
    const summaries = [this.noAction, this.quickTurn, this.spare, this.swap, this.cancelRoundTrip]
      .map((f) => summary(f.call(this, tail, i, delayMin), this.ops))
    const best = summaries.filter((s) => s.feasible).reduce((b, s) => (b === null || s.total_cost < b.total_cost ? s : b), null)
    const base = summaries.find((s) => s.key === 'no_action')
    for (const s of summaries) s.saving_vs_no_action = s.feasible ? base.total_cost - s.total_cost : null
    const sorted = summaries.map((s, idx) => [s, idx])
      .sort(([a, ia], [b, ib]) => (a.feasible === b.feasible ? a.total_cost - b.total_cost || ia - ib : a.feasible ? -1 : 1))
      .map(([s]) => s)
    return { flight_id: flightId, tail_number: tail, initial_delay_min: delayMin, recommended: best.key, scenarios: sorted }
  }
}
