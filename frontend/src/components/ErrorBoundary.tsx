import React, { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface Props {
  children?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null
  }

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error:', error, errorInfo)
  }

  public render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto', fontFamily: 'monospace' }}>
          <h1 style={{ color: '#e53935' }}>Something went wrong.</h1>
          <p>A rendering error occurred in the React tree.</p>
          <pre style={{ background: '#f5f5f5', padding: '1rem', overflowX: 'auto', borderRadius: '4px', color: '#333' }}>
            {this.state.error?.toString()}
          </pre>
          <pre style={{ background: '#f5f5f5', padding: '1rem', overflowX: 'auto', borderRadius: '4px', color: '#333', marginTop: '1rem' }}>
            {this.state.error?.stack}
          </pre>
          <button 
            onClick={() => window.location.reload()}
            style={{ marginTop: '1rem', padding: '0.5rem 1rem', background: '#4285F4', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Reload Page
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
