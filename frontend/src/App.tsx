import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from './app/auth/AuthContext'
import { AppRoutes } from './app/routes/AppRoutes'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
