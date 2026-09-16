// ============================================================
// Academix AI — Login Page
// Google-style clean login form
// ============================================================
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/contexts/AuthContext'
import { GraduationCap, Eye, EyeOff } from 'lucide-react'
import toast from 'react-hot-toast'

export default function LoginPage() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      await signIn(email, password)
      toast.success('Welcome back!')
      navigate('/dashboard')
    } catch (err: any) {
      toast.error(err?.message || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #F8F9FA 0%, #E8F0FE 100%)',
      padding: 24,
    }}>
      <div className="card" style={{
        width: '100%',
        maxWidth: 420,
        padding: '48px 40px',
        textAlign: 'center',
      }}>
        {/* Logo */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          marginBottom: 8,
        }}>
          <GraduationCap size={36} color="#4285F4" />
          <h1 style={{ fontSize: 28, fontWeight: 700, color: '#4285F4' }}>
            Academix AI
          </h1>
        </div>
        <p className="text-muted" style={{ marginBottom: 32 }}>
          RAG-Powered Quiz Generation Platform
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="input-group" style={{ textAlign: 'left' }}>
            <label className="input-label">Email</label>
            <input
              className="input"
              type="email"
              placeholder="you@college.edu"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>

          <div className="input-group" style={{ textAlign: 'left', position: 'relative' }}>
            <label className="input-label">Password</label>
            <input
              className="input"
              type={showPw ? 'text' : 'password'}
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              style={{ paddingRight: 42 }}
            />
            <button
              type="button"
              onClick={() => setShowPw(!showPw)}
              className="btn btn-ghost btn-icon"
              style={{
                position: 'absolute',
                right: 4,
                bottom: 4,
                padding: 6,
              }}
            >
              {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          <button
            className="btn btn-primary"
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '12px',
              fontSize: 15,
              justifyContent: 'center',
              marginTop: 8,
            }}
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <p style={{ marginTop: 24, fontSize: 12, color: 'var(--color-text-3)' }}>
          Contact your admin if you need an account
        </p>
      </div>
    </div>
  )
}
