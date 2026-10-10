import { BrowserRouter } from 'react-router-dom'

import { AuthProvider } from './app/auth/AuthContext'
import { ErrorBoundary } from './app/components/ErrorBoundary'
import { AppRoutes } from './app/routes/AppRoutes'
import { ShellLayoutProvider } from './app/shell/ShellLayoutProvider'

function App() {
  return (
    <ErrorBoundary what="The application">
      <BrowserRouter>
        <AuthProvider>
          <ShellLayoutProvider>
            <AppRoutes />
          </ShellLayoutProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
