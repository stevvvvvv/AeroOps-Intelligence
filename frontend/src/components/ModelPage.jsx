import { useEffect, useState } from 'react'
import { api } from '../api'

const ROWS = [['mae_min', 'MAE (min)'], ['rmse_min', 'RMSE (min)'], ['r2', 'R²'], ['roc_auc', 'ROC AUC'], ['pr_auc', 'PR AUC'], ['brier', 'Brier'], ['f1@0.5', 'F1 @0,5']]
const BASE = { moyenne_globale: 'Moyenne globale', historique_ligne_28j: 'Historique de la ligne (28 j)', regle_propagation_simple: 'Règle de propagation simple' }

export default function ModelPage() {
  const [r, setR] = useState(null)
  useEffect(() => { api.report().then(setR) }, [])
  if (!r) return <div className="empty">Chargement…</div>
  const cols = [...Object.entries(BASE).map(([k, l]) => [l, r.baselines[k], true]),
    ['XGBoost stratégique (J-1)', r.models.strategic.metrics], ['XGBoost tactique (H-2)', r.models.tactical.metrics]]
  return (
    <>
      <h2>Modèle de prédiction</h2>
      <p className="sub">Validation temporelle : entraînement sur le passé, test sur les {r.n_test.toLocaleString('fr-FR')} vols du {r.test_period[0]} au {r.test_period[1]} (jamais vus). Entraîné le {r.trained_at.replace('T', ' à ')}.</p>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Comparaison aux références</h3>
        <p className="hint">Un modèle n'a de valeur que s'il bat les règles simples qu'un OCC utilise déjà</p>
        <table>
          <thead><tr><th>Métrique</th>{cols.map(([l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
          <tbody>{ROWS.map(([k, l]) => (
            <tr key={k}><td>{l}</td>{cols.map(([c, m]) => <td key={c} className="num" style={{ fontWeight: c.startsWith('XGBoost tactique') ? 600 : 400 }}>{m?.[k] == null ? '–' : m[k].toFixed(k.includes('min') ? 1 : 3)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
      <div className="grid g2">
        {['tactical', 'strategic'].map((name) => {
          const imp = Object.entries(r.models[name].shap_by_factor_min)
          const max = Math.max(...imp.map(([, v]) => v))
          return (
            <div className="card" key={name}>
              <h3>Importance des facteurs · modèle {name === 'tactical' ? 'tactique' : 'stratégique'}</h3>
              <p className="hint">Contribution moyenne absolue au retard prédit (SHAP, minutes)</p>
              {imp.map(([f, v]) => (
                <div key={f} style={{ display: 'grid', gridTemplateColumns: '230px 1fr 50px', gap: 10, alignItems: 'center', margin: '8px 0' }}>
                  <span style={{ fontSize: 13 }}>{f}</span>
                  <div style={{ height: 12, width: `${(v / max) * 100}%`, background: 'var(--s1)', borderRadius: 4 }} />
                  <span style={{ fontSize: 13, textAlign: 'right' }}>{v.toFixed(1)}</span>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </>
  )
}
