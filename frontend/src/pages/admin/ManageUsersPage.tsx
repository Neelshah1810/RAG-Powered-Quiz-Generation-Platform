// ============================================================
// Academix AI — Manage Users Page (Admin)
// User list with search and 3 role tabs (Admin, Teachers, Students)
// ============================================================
import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '@/lib/api'
import type { User } from '@/lib/types'
import { Users, Plus, Search, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

type RoleTab = 'admin' | 'teacher' | 'student'

function isValidTab(value: string | null): value is RoleTab {
  return value === 'admin' || value === 'teacher' || value === 'student'
}

export default function ManageUsersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  // Initialise tab from the URL query parameter, default to 'admin'
  const tabFromUrl = searchParams.get('tab')
  const [activeTab, setActiveTab] = useState<RoleTab>(
    isValidTab(tabFromUrl) ? tabFromUrl : 'admin'
  )

  const [showCreate, setShowCreate] = useState(false)

  const [formEmail, setFormEmail] = useState('')
  const [formName, setFormName] = useState('')
  const [formPassword, setFormPassword] = useState('')
  const [formRole, setFormRole] = useState('student')
  const [formDept, setFormDept] = useState('')

  // Sync the URL when the tab changes, so browser back/forward works
  const changeTab = (tab: RoleTab) => {
    setActiveTab(tab)
    setSearchParams(tab === 'admin' ? {} : { tab }, { replace: true })
  }

  // Also react if someone navigates here with a different ?tab while already mounted
  useEffect(() => {
    const newTab = searchParams.get('tab')
    if (isValidTab(newTab) && newTab !== activeTab) {
      setActiveTab(newTab)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  useEffect(() => { loadUsers() }, [activeTab, search])

  const loadUsers = async () => {
    setLoading(true)
    try {
      const params: any = { role: activeTab }
      if (search) params.search = search
      const { data } = await api.get('/users/', { params })
      setUsers(data || [])
    } catch { /* ignore */ }
    setLoading(false)
  }

  const createUser = async () => {
    if (!formEmail || !formName || !formPassword) { toast.error('Fill all required fields'); return }
    try {
      await api.post('/auth/signup', {
        email: formEmail, full_name: formName,
        password: formPassword, role: formRole,
        department: formDept || null,
      })
      toast.success('User created')
      setShowCreate(false)
      setFormEmail(''); setFormName(''); setFormPassword(''); setFormRole('student'); setFormDept('')
      loadUsers()
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Failed to create user')
    }
  }

  const deleteUser = async (userId: string, userName: string) => {
    if (!confirm(`Delete user "${userName}"? This cannot be undone.`)) return
    try {
      await api.delete(`/users/${userId}`)
      toast.success('User deleted')
      loadUsers()
    } catch { toast.error('Failed to delete') }
  }

  const roleColors: Record<string, string> = { admin: 'badge-purple', teacher: 'badge-blue', student: 'badge-green' }
  const tabCounts: Record<RoleTab, string> = {
    admin: 'Admins',
    teacher: 'Teachers',
    student: 'Students',
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Manage Users</h1>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          <Plus size={16} /> Add User
        </button>
      </div>

      {/* Search */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ position: 'relative' }}>
          <Search size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-3)' }} />
          <input className="input" placeholder="Search by name or email..."
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ paddingLeft: 36 }} />
        </div>
      </div>

      {/* 3 Role Tabs */}
      <div className="tabs" style={{ marginBottom: 20 }}>
        {(['admin', 'teacher', 'student'] as RoleTab[]).map(role => (
          <div key={role}
            className={`tab ${activeTab === role ? 'active' : ''}`}
            onClick={() => changeTab(role)}>
            {tabCounts[role]}
          </div>
        ))}
      </div>

      {/* Users Table */}
      <div className="card" style={{ overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--color-surface-2)', borderBottom: '1px solid var(--color-border)' }}>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: 'var(--color-text-2)', textTransform: 'uppercase' }}>User</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: 'var(--color-text-2)', textTransform: 'uppercase' }}>Email</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: 'var(--color-text-2)', textTransform: 'uppercase' }}>Role</th>
              <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 600, color: 'var(--color-text-2)', textTransform: 'uppercase' }}>Department</th>
              <th style={{ padding: '12px 16px', width: 60 }}></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{ padding: 40, textAlign: 'center' }} className="text-muted">Loading...</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 40, textAlign: 'center' }} className="text-muted">No {tabCounts[activeTab].toLowerCase()} found</td></tr>
            ) : users.map(u => (
              <tr key={u.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                <td style={{ padding: '12px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div className="avatar" style={{ width: 32, height: 32, fontSize: 12 }}>
                      {u.full_name?.charAt(0)}
                    </div>
                    <span className="font-medium">{u.full_name}</span>
                  </div>
                </td>
                <td style={{ padding: '12px 16px' }} className="text-muted">{u.email}</td>
                <td style={{ padding: '12px 16px' }}>
                  <span className={`badge ${roleColors[u.role] || 'badge-gray'}`}>{u.role}</span>
                </td>
                <td style={{ padding: '12px 16px' }} className="text-muted">{u.department || '—'}</td>
                <td style={{ padding: '12px 16px' }}>
                  <button className="btn btn-ghost btn-icon" onClick={() => deleteUser(u.id, u.full_name)}
                    style={{ color: 'var(--color-danger)' }}>
                    <Trash2 size={16} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create User Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Add User</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">Full Name *</label>
                <input className="input" value={formName} onChange={e => setFormName(e.target.value)} />
              </div>
              <div className="input-group">
                <label className="input-label">Email *</label>
                <input className="input" type="email" value={formEmail} onChange={e => setFormEmail(e.target.value)} />
              </div>
              <div className="input-group">
                <label className="input-label">Password *</label>
                <input className="input" type="password" value={formPassword} onChange={e => setFormPassword(e.target.value)} />
              </div>
              <div className="grid-2">
                <div className="input-group">
                  <label className="input-label">Role</label>
                  <select className="input" value={formRole} onChange={e => setFormRole(e.target.value)}>
                    <option value="student">Student</option>
                    <option value="teacher">Teacher</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div className="input-group">
                  <label className="input-label">Department</label>
                  <input className="input" value={formDept} onChange={e => setFormDept(e.target.value)} />
                </div>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createUser}>Create User</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
