import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './', // chemins relatifs : fonctionne à la racine d'un Space comme dans un sous-dossier
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
