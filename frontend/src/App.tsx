import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from './app/auth/AuthContext'
import { AppRoutes } from './app/routes/AppRoutes'
import { ShellLayoutProvider } from './app/shell/ShellLayoutProvider'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ShellLayoutProvider>
          <AppRoutes />
        </ShellLayoutProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
