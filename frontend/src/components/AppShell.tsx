import { Suspense, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity, Banknote, Bell, BookOpen, Briefcase, Building2, CalendarClock, CalendarDays, ClipboardCheck, FileChartColumn, FileText,
  GraduationCap, KeyRound, Landmark, LayoutDashboard, Library, ListChecks, LogOut, Megaphone, Menu, MonitorSmartphone, Package, QrCode,
  Receipt, Scale, Server, Shield, Smartphone, Star, TrendingUp, TriangleAlert, UserPlus, UserRound, Users, Wallet,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { post } from '../lib/api'
import { useAction, useGet } from '../lib/hooks'
import type { R } from '../lib/hooks'
import { dateTime, initials, ROLE_LABELS } from '../lib/format'
import { BrandMark } from './Brand'
import { Button, IconButton, Loading } from './ui'

type Item = { to: string; label: string; icon: LucideIcon; perms: string[]; end?: boolean }
const TEACH = ['academic:write', 'academic:teach']
const ACADEMIC = [...TEACH, 'academic:self']

export const NAV: { title: string; items: Item[] }[] = [
  { title: 'Overview', items: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard, perms: [], end: true }] },
  {
    title: 'Academic', items: [
      { to: '/academic/me', label: 'My courses & results', icon: GraduationCap, perms: ['academic:self'] },
      { to: '/academic/catalogue', label: 'Programmes & courses', icon: Library, perms: ['academic:write'] },
      { to: '/academic/offerings', label: 'Course offerings', icon: BookOpen, perms: TEACH },
      { to: '/academic/students', label: 'Students & registration', icon: Users, perms: ['academic:write'] },
      { to: '/academic/gradebook', label: 'Gradebook', icon: ClipboardCheck, perms: TEACH },
      { to: '/academic/attendance', label: 'Class attendance', icon: ListChecks, perms: TEACH },
      { to: '/academic/exams', label: 'Exam timetable', icon: CalendarClock, perms: ACADEMIC },
      { to: '/academic/appeals', label: 'Grade appeals', icon: Scale, perms: ACADEMIC },
      { to: '/academic/risk', label: 'At-risk students', icon: TriangleAlert, perms: TEACH },
    ],
  },
  {
    title: 'Finance & marketing', items: [
      { to: '/finance/pay', label: 'Fees & payments', icon: Smartphone, perms: ['finance:self'] },
      { to: '/finance', label: 'Finance overview', icon: TrendingUp, perms: ['finance:read'], end: true },
      { to: '/finance/invoices', label: 'Invoices', icon: FileText, perms: ['finance:read'] },
      { to: '/finance/fee-plans', label: 'Fee plans & billing', icon: Receipt, perms: ['finance:read'] },
      { to: '/finance/expenses', label: 'Expenses', icon: Wallet, perms: ['finance:read'] },
      { to: '/finance/campaigns', label: 'Campaigns & leads', icon: Megaphone, perms: ['finance:read'] },
      { to: '/finance/reports', label: 'Monthly reports', icon: FileChartColumn, perms: ['finance:read'] },
      { to: '/finance/ledger', label: 'General ledger', icon: Landmark, perms: ['finance:read'] },
    ],
  },
  {
    title: 'People & administration', items: [
      { to: '/hr/me', label: 'My HR', icon: UserRound, perms: ['hr:self'] },
      { to: '/hr/check-in', label: 'Check in / out', icon: QrCode, perms: ['hr:self'] },
      { to: '/hr', label: 'HR overview', icon: Activity, perms: ['hr:read'], end: true },
      { to: '/hr/employees', label: 'Employees', icon: Briefcase, perms: ['hr:read'] },
      { to: '/hr/recruitment', label: 'Recruitment', icon: UserPlus, perms: ['hr:read'] },
      { to: '/hr/payroll', label: 'Payroll', icon: Banknote, perms: ['hr:read'] },
      { to: '/hr/attendance', label: 'Attendance kiosk', icon: MonitorSmartphone, perms: ['hr:write'] },
      { to: '/hr/leave', label: 'Leave requests', icon: CalendarDays, perms: ['hr:read'] },
      { to: '/hr/reviews', label: 'Performance', icon: Star, perms: ['hr:read'] },
      { to: '/hr/assets', label: 'Assets & inventory', icon: Package, perms: ['hr:read'] },
    ],
  },
  {
    title: 'Administration', items: [
      { to: '/admin/users', label: 'Users & roles', icon: Shield, perms: ['users:manage'] },
      { to: '/admin/tenants', label: 'Institutions', icon: Building2, perms: ['platform:manage'] },
      { to: '/admin/system', label: 'System status', icon: Server, perms: ['users:manage', 'platform:manage'] },
    ],
  },
]

function useOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const handler = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as Node)) close() }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close() }
    document.addEventListener('mousedown', handler)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('mousedown', handler); document.removeEventListener('keydown', escape) }
  }, [open, close])
  return ref
}

function Notifications() {
  const [open, setOpen] = useState(false)
  const ref = useOutside(open, () => setOpen(false))
  const { data } = useGet<R[]>('/api/v1/hr/notifications', 60_000)
  const markRead = useAction(() => post('/api/v1/hr/notifications/read'), { invalidate: ['/api/v1/hr/notifications'], silent: true })
  const unread = data?.filter((item) => !item.read_at).length ?? 0
  return (
    <div className="anchor" ref={ref}>
      <IconButton label={`Notifications${unread ? ` (${unread} unread)` : ''}`} icon={Bell} badge={unread} onClick={() => setOpen(!open)} aria-expanded={open} />
      {open && (
        <div className="popover" role="dialog" aria-label="Notifications">
          <div className="popover-header">
            <strong>Notifications</strong>
            <span className="spacer" />
            {unread > 0 && <Button variant="ghost" small busy={markRead.isPending} onClick={() => markRead.mutate()}>Mark all read</Button>}
          </div>
          <div className="popover-list">
            {!data?.length && <p className="muted" style={{ padding: 16 }}>No notifications yet.</p>}
            {data?.map((item) => (
              <div key={item.id} className={`popover-item ${item.read_at ? '' : 'unread'}`}>
                <strong>{item.title}</strong>
                <span>{item.body}</span>
                <div className="row small muted" style={{ marginTop: 4 }}>
                  <span>{dateTime(item.created_at)}</span>
                  {item.link && <Link to={item.link} onClick={() => setOpen(false)}>Open</Link>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function UserMenu() {
  const { session, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useOutside(open, () => setOpen(false))
  const user = session!.user
  return (
    <div className="anchor" ref={ref}>
      <button type="button" className="user-chip" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" style={{ cursor: 'pointer' }}>
        <span className="avatar" aria-hidden>{initials(user.name)}</span>
        <span className="who"><strong>{user.name}</strong><span>{ROLE_LABELS[user.role] ?? user.role}</span></span>
      </button>
      {open && (
        <div className="popover menu" role="menu">
          <Link to="/account" role="menuitem" onClick={() => setOpen(false)}><KeyRound size={16} aria-hidden />Account & security</Link>
          <button type="button" role="menuitem" onClick={() => logout()}><LogOut size={16} aria-hidden />Sign out</button>
        </div>
      )}
    </div>
  )
}

function TenantSwitcher() {
  const { session, switchTenant } = useAuth()
  const [busy, setBusy] = useState(false)
  const tenants = session!.tenants
  if (tenants.length < 2) return <span className="badge badge-teal"><Building2 size={13} aria-hidden />{session!.tenant.name}</span>
  return (
    <label className="row" style={{ gap: 6 }}>
      <Building2 size={16} aria-hidden className="muted" />
      <span className="sr-only">Active institution</span>
      <select className="select" style={{ minHeight: 34, width: 'auto' }} value={session!.tenant.id} disabled={busy}
        onChange={async (event) => { setBusy(true); try { await switchTenant(event.target.value) } finally { setBusy(false) } }}>
        {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
      </select>
    </label>
  )
}

export function Guard({ perms, children }: { perms: string[]; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(...perms)) {
    return (
      <div className="page">
        <div className="panel"><div className="empty"><Shield size={28} aria-hidden /><strong>You do not have access to this page</strong>
          <span>Your role in this institution does not include the required permission. Ask an administrator if you need access.</span>
          <Link to="/">Back to dashboard</Link></div></div>
      </div>
    )
  }
  return <>{children}</>
}

export default function AppShell() {
  const { session, can } = useAuth()
  const [open, setOpen] = useState(false)
  const location = useLocation()
  const groups = NAV.map((group) => ({ ...group, items: group.items.filter((item) => can(...item.perms)) })).filter((group) => group.items.length)
  const current = NAV.flatMap((group) => group.items)
    .filter((item) => (item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)))
    .sort((a, b) => b.to.length - a.to.length)[0]
  return (
    <div className="app">
      <a href="#main" className="sr-only">Skip to content</a>
      <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Main navigation">
        <Link to="/" className="brand" onClick={() => setOpen(false)}>
          <BrandMark />
          <span><strong>Campus ERP</strong><span>{session!.tenant.name}</span></span>
        </Link>
        <nav>
          {groups.map((group) => (
            <div key={group.title} className="nav-group">
              <h3>{group.title}</h3>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} className="nav-link" onClick={() => setOpen(false)}>
                  <item.icon size={17} aria-hidden />{item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="sidebar-foot">API v1 · Africa/Douala time · FCFA</div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden />}
      <div className="main">
        <header className="topbar">
          <span className="menu-toggle"><IconButton label="Open navigation" icon={Menu} onClick={() => setOpen(true)} /></span>
          <div className="topbar-title">
            <strong>{current?.label ?? 'Campus ERP'}</strong>
            <span>{session!.tenant.name}</span>
          </div>
          <div className="topbar-actions">
            <TenantSwitcher />
            {can('hr:self', 'hr:read') && <Notifications />}
            <UserMenu />
          </div>
        </header>
        <main id="main" className="page">
          <Suspense fallback={<div className="panel"><Loading rows={6} /></div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
