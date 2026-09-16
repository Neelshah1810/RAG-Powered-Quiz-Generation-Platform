// ============================================================
// Academix AI — Scheduler Page
// Google Calendar-style month grid with color-coded events
// ============================================================
import { useState, useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import api from '@/lib/api'
import type { CalendarEvent, User } from '@/lib/types'
import { ChevronLeft, ChevronRight, Plus, X, Trash2 } from 'lucide-react'
import {
  format, startOfMonth, endOfMonth, startOfWeek, endOfWeek,
  eachDayOfInterval, isSameMonth, isToday, isSameDay,
  addMonths, subMonths,
} from 'date-fns'
import toast from 'react-hot-toast'

// Event colors matching backend EVENT_TYPE_COLORS
const EVENT_COLORS: Record<string, string> = {
  lecture: '#FBC02D',       // Yellow
  meeting: '#4285F4',      // Blue
  exam: '#DB4437',         // Red
  assignment_due: '#F4B400', // Yellow
  holiday: '#0F9D58',      // Green
  other: '#9E9E9E',        // Grey
}

export default function SchedulerPage() {
  const { user } = useAuth()
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [loading, setLoading] = useState(true)

  // Form state
  const [formTitle, setFormTitle] = useState('')
  const [formType, setFormType] = useState(user?.role === 'student' ? 'meeting' : 'lecture')
  const [formStart, setFormStart] = useState('')
  const [formEnd, setFormEnd] = useState('')
  const [formDate, setFormDate] = useState('') // Date-only for holidays
  const [formDesc, setFormDesc] = useState('')
  const [formCourseId, setFormCourseId] = useState('')
  const [formPersonId, setFormPersonId] = useState('')
  const [formSemester, setFormSemester] = useState('everyone')
  const [courses, setCourses] = useState<any[]>([])
  const [staffList, setStaffList] = useState<User[]>([])

  useEffect(() => {
    loadEvents()
    api.get('/courses/').then(r => setCourses(r.data || [])).catch(() => {})
    api.get('/users/staff').then(r => setStaffList(r.data || [])).catch(() => {})
  }, [currentMonth])

  const loadEvents = async () => {
    setLoading(true)
    try {
      const start = startOfMonth(currentMonth).toISOString()
      const end = endOfMonth(currentMonth).toISOString()
      const { data } = await api.get('/scheduler/events', { params: { start_date: start, end_date: end } })
      setEvents(data || [])
    } catch { /* ignore */ }
    setLoading(false)
  }

  const createEvent = async () => {
    if (!formTitle) { toast.error('Title is required'); return }

    let startAt: string
    let endAt: string

    if (formType === 'holiday') {
      if (!formDate) { toast.error('Date is required'); return }
      startAt = new Date(formDate + 'T00:00:00').toISOString()
      endAt = new Date(formDate + 'T23:59:59').toISOString()
    } else {
      if (!formStart || !formEnd) { toast.error('Start and end time required'); return }
      startAt = new Date(formStart).toISOString()
      endAt = new Date(formEnd).toISOString()
    }

    try {
      const payload: any = {
        title: formTitle, event_type: formType,
        start_at: startAt,
        end_at: endAt,
        description: formDesc || null,
      }

      if (formType === 'holiday') {
        payload.semester = formSemester
        payload.description = formSemester === 'everyone'
          ? `Holiday for entire department${formDesc ? ' - ' + formDesc : ''}`
          : `Holiday for Semester ${formSemester}${formDesc ? ' - ' + formDesc : ''}`
        payload.course_id = null
      } else if (formType === 'meeting' && formPersonId) {
        const person = staffList.find(s => s.id === formPersonId)
        if (person) {
          payload.description = `Meeting with ${person.full_name}${formDesc ? ' - ' + formDesc : ''}`
        }
        payload.course_id = null
      } else if (formType === 'lecture' && formPersonId) {
        const person = staffList.find(s => s.id === formPersonId)
        if (person) {
          payload.description = `Lecture by ${person.full_name}${formDesc ? ' - ' + formDesc : ''}`
        }
        payload.course_id = formCourseId || null
      } else {
        payload.course_id = formCourseId || null
      }

      await api.post('/scheduler/events', payload)
      toast.success('Event created')
      setShowCreate(false)
      resetForm()
      loadEvents()
    } catch (err: any) {
      const msg = err?.response?.data?.detail || 'Failed to create event'
      toast.error(msg)
    }
  }

  const deleteEvent = async (eventId: string) => {
    try {
      await api.delete(`/scheduler/events/${eventId}`)
      toast.success('Event deleted')
      setSelectedEvent(null)
      loadEvents()
    } catch {
      toast.error('Failed to delete event')
    }
  }

  const resetForm = () => {
    setFormTitle('')
    setFormType(user?.role === 'student' ? 'meeting' : 'lecture')
    setFormStart('')
    setFormEnd('')
    setFormDate('')
    setFormDesc('')
    setFormCourseId('')
    setFormPersonId('')
    setFormSemester('everyone')
  }

  // Calendar grid
  const monthStart = startOfMonth(currentMonth)
  const monthEnd = endOfMonth(currentMonth)
  const calStart = startOfWeek(monthStart, { weekStartsOn: 0 })
  const calEnd = endOfWeek(monthEnd, { weekStartsOn: 0 })
  const days = eachDayOfInterval({ start: calStart, end: calEnd })

  const getEventsForDay = (day: Date) =>
    events.filter(e => isSameDay(new Date(e.start_at), day))

  const getEventColor = (eventType: string) => EVENT_COLORS[eventType] || '#9E9E9E'

  // Event type options based on role
  const getEventTypeOptions = () => {
    if (user?.role === 'student') {
      return [
        { value: 'meeting', label: 'Meeting' },
        { value: 'other', label: 'Other' },
      ]
    }
    return [
      { value: 'lecture', label: 'Lecture' },
      { value: 'meeting', label: 'Meeting' },
      { value: 'exam', label: 'Exam' },
      { value: 'holiday', label: 'Holiday' },
      { value: 'other', label: 'Other' },
    ]
  }

  const canDelete = user?.role === 'admin' || user?.role === 'teacher'

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Scheduler</h1>
        <button className="btn btn-primary" onClick={() => { resetForm(); setShowCreate(true) }}>
          <Plus size={16} /> New Event
        </button>
      </div>

      {/* Color Legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
        {Object.entries(EVENT_COLORS).filter(([k]) => k !== 'assignment_due').map(([type, color]) => (
          <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
            <div style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
            <span style={{ textTransform: 'capitalize' }}>{type}</span>
          </div>
        ))}
      </div>

      {/* Month Navigation */}
      <div className="flex-between" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className="btn btn-ghost btn-icon" onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}>
            <ChevronLeft size={20} />
          </button>
          <h2 style={{ fontSize: 20, minWidth: 200, textAlign: 'center' }}>
            {format(currentMonth, 'MMMM yyyy')}
          </h2>
          <button className="btn btn-ghost btn-icon" onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}>
            <ChevronRight size={20} />
          </button>
        </div>
        <button className="btn btn-secondary" onClick={() => setCurrentMonth(new Date())}>Today</button>
      </div>

      {/* Calendar Grid */}
      <div className="calendar-grid">
        {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => (
          <div key={d} className="calendar-day-header">{d}</div>
        ))}
        {days.map(day => {
          const dayEvents = getEventsForDay(day)
          return (
            <div key={day.toISOString()}
              className={`calendar-day ${!isSameMonth(day, currentMonth) ? 'other-month' : ''} ${isToday(day) ? 'today' : ''}`}>
              <div className={isToday(day) ? 'day-number' : ''} style={{ fontSize: 13, marginBottom: 4, fontWeight: isToday(day) ? 600 : 400 }}>
                {format(day, 'd')}
              </div>
              {dayEvents.slice(0, 3).map(ev => {
                const color = getEventColor(ev.event_type)
                return (
                  <div key={ev.id} className="event-chip"
                    style={{ background: color + '22', color: color, borderLeft: `3px solid ${color}` }}
                    onClick={() => setSelectedEvent(ev)} title={ev.title}>
                    {ev.title}
                  </div>
                )
              })}
              {dayEvents.length > 3 && (
                <div className="text-muted" style={{ fontSize: 10, padding: '0 4px' }}>
                  +{dayEvents.length - 3} more
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Event Detail Slide-over */}
      {selectedEvent && (
        <>
          <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.2)', zIndex: 499 }}
            onClick={() => setSelectedEvent(null)} />
          <div className="slideover" style={{ padding: 24 }}>
            <div className="flex-between" style={{ marginBottom: 20 }}>
              <h3>{selectedEvent.title}</h3>
              <div style={{ display: 'flex', gap: 8 }}>
                {canDelete && (
                  <button className="btn btn-ghost btn-icon" onClick={() => deleteEvent(selectedEvent.id)}
                    title="Delete event" style={{ color: '#DB4437' }}>
                    <Trash2 size={18} />
                  </button>
                )}
                <button className="btn btn-ghost btn-icon" onClick={() => setSelectedEvent(null)}>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <span className="text-muted text-small">Type</span>
                <p className="font-medium" style={{ textTransform: 'capitalize', color: getEventColor(selectedEvent.event_type) }}>
                  {selectedEvent.event_type.replace('_', ' ')}
                </p>
              </div>
              <div>
                <span className="text-muted text-small">When</span>
                <p className="font-medium">
                  {selectedEvent.event_type === 'holiday'
                    ? format(new Date(selectedEvent.start_at), 'PPP') + ' (Full Day)'
                    : `${format(new Date(selectedEvent.start_at), 'PPp')} — ${format(new Date(selectedEvent.end_at), 'p')}`
                  }
                </p>
              </div>
              {selectedEvent.course_name && (
                <div>
                  <span className="text-muted text-small">Course</span>
                  <p className="font-medium">{selectedEvent.course_name}</p>
                </div>
              )}
              {selectedEvent.location && (
                <div>
                  <span className="text-muted text-small">Location</span>
                  <p className="font-medium">{selectedEvent.location}</p>
                </div>
              )}
              {selectedEvent.description && (
                <div>
                  <span className="text-muted text-small">Description</span>
                  <p>{selectedEvent.description}</p>
                </div>
              )}
              <div>
                <span className="text-muted text-small">Created by</span>
                <p className="font-medium">{selectedEvent.creator_name || 'Unknown'}</p>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Create Event Modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>New Event</h3>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowCreate(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className="input-group">
                <label className="input-label">Title *</label>
                <input className="input" value={formTitle} onChange={e => setFormTitle(e.target.value)} placeholder="Event title" />
              </div>
              <div className="grid-2">
                <div className="input-group">
                  <label className="input-label">Type</label>
                  <select className="input" value={formType} onChange={e => setFormType(e.target.value)}>
                    {getEventTypeOptions().map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div className="input-group">
                  {formType === 'meeting' || formType === 'lecture' ? (
                    <>
                      <label className="input-label">{formType === 'lecture' ? 'Teacher' : 'Person'}</label>
                      <select className="input" value={formPersonId} onChange={e => setFormPersonId(e.target.value)}>
                        <option value="">Select {formType === 'lecture' ? 'teacher' : 'person'}...</option>
                        {staffList.filter(s => formType === 'meeting' || s.role === 'teacher').map(s => (
                          <option key={s.id} value={s.id}>
                            {s.full_name} ({s.role})
                          </option>
                        ))}
                      </select>
                      {formType === 'lecture' && (
                        <div style={{ marginTop: 12 }}>
                          <label className="input-label">Course</label>
                          <select className="input" value={formCourseId} onChange={e => setFormCourseId(e.target.value)}>
                            <option value="">None (Personal)</option>
                            {courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                          </select>
                        </div>
                      )}
                    </>
                  ) : formType === 'holiday' ? (
                    <>
                      <label className="input-label">Applies To</label>
                      <select className="input" value={formSemester} onChange={e => setFormSemester(e.target.value)}>
                        <option value="everyone">Everyone (Whole Department)</option>
                        {Array.from({ length: 10 }, (_, i) => (
                          <option key={i + 1} value={String(i + 1)}>Semester {i + 1}</option>
                        ))}
                      </select>
                    </>
                  ) : (
                    <>
                      <label className="input-label">Course</label>
                      <select className="input" value={formCourseId} onChange={e => setFormCourseId(e.target.value)}>
                        <option value="">None (Personal)</option>
                        {courses.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </>
                  )}
                </div>
              </div>

              {/* Date/Time inputs — Holiday gets date-only, others get datetime */}
              {formType === 'holiday' ? (
                <div className="input-group">
                  <label className="input-label">Date *</label>
                  <input className="input" type="date" value={formDate} onChange={e => setFormDate(e.target.value)} />
                </div>
              ) : (
                <div className="grid-2">
                  <div className="input-group">
                    <label className="input-label">Start *</label>
                    <input className="input" type="datetime-local" value={formStart} onChange={e => setFormStart(e.target.value)} />
                  </div>
                  <div className="input-group">
                    <label className="input-label">End *</label>
                    <input className="input" type="datetime-local" value={formEnd} onChange={e => setFormEnd(e.target.value)} />
                  </div>
                </div>
              )}

              <div className="input-group">
                <label className="input-label">Description</label>
                <textarea className="input" value={formDesc} onChange={e => setFormDesc(e.target.value)} rows={2} />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={createEvent}>Create Event</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
