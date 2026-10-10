import { Component, type ErrorInfo, type ReactNode } from 'react'

import { StatePanel } from './StatePanel'

type ErrorBoundaryProps = {
  children: ReactNode
  // What went wrong, in the user's terms ("This page", "The application").
  what?: string
}

type ErrorBoundaryState = {
  failed: boolean
}

// Without a boundary, one unexpected value while drawing a screen blanks the
// whole app (mid-call included) until the page is reloaded. This keeps the
// damage to the part it wraps and offers the way out.
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('A screen failed to display', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) {
      return this.props.children
    }

    return (
      <StatePanel
        variant="error"
        title={`${this.props.what ?? 'This page'} could not be displayed`}
        description="Something unexpected happened while showing it. Your call and its data are not affected. Reload to continue."
        action={
          <div className="button-row">
            <button type="button" className="button" onClick={() => window.location.reload()}>
              Reload
            </button>
            <button
              type="button"
              className="button button--secondary"
              onClick={() => this.setState({ failed: false })}
            >
              Try again
            </button>
          </div>
        }
      />
    )
  }
}
