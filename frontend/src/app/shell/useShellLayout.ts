import { useContext } from 'react'

import { ShellLayoutContext, type ShellLayoutContextValue } from './shell-layout-context'

export function useShellLayout(): ShellLayoutContextValue {
  const context = useContext(ShellLayoutContext)
  if (!context) {
    throw new Error('useShellLayout must be used within ShellLayoutProvider')
  }
  return context
}
