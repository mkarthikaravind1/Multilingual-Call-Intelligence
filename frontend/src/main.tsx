import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './app/design/tokens.css'
import './styles/app-shell.css'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
