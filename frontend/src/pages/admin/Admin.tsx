import { useState } from 'react'
import { Activity, Building2, ExternalLink, KeyRound, LockOpen, Plus, ShieldCheck, Trash2, UserPlus } from 'lucide-react'
import { useQueries } from '@tanstack/react-query'
import { Badge, Button, DataTable, Field, Input, Modal, PageHeader, Panel, SearchBox, Select } from '../../components/ui'
import { del, fieldErrors, get, patch, post } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { dateTime, ROLE_LABELS } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'

const AUTH = '/api/v1/auth'
const ROLES = ['admin', 'instructor', 'finance', 'hr', 'employee', 'student'].map((value) => ({ value, label: ROLE_LABELS[value] }))

/* ---------------- Users ---------------- */
export function Users() {
  const { session } = useAuth()
  const [q, setQ] = useState('')
  const users = useGet<R[]>(`${AUTH}/users${q ? `?q=${encodeURIComponent(q)}` : ''}`)
  const [creating, setCreating] = useState(false)
  const [removing, setRemoving] = useState<R | null>(null)
  const change = useAction(({ id, body }: { id: string; body: R }) => patch(`${AUTH}/users/${id}`, body), { invalidate: [`${AUTH}/users`], success: 'Account updated · existing sessions for this institution were revoked' })
  const remove = useAction((id: string) => del(`${AUTH}/users/${id}`), { invalidate: [`${AUTH}/users`], success: 'Access removed', onSuccess: () => setRemoving(null) })
  return (
    <div className="stack">
      <PageHeader title="Users & roles" subtitle={`Accounts with access to ${session!.tenant.name}. Roles are enforced by every API; changing a role signs the person out of this institution immediately.`}
        actions={<Button icon={UserPlus} onClick={() => setCreating(true)}>Add user</Button>} />
      <Panel title={`${users.data?.length ?? '…'} members`} actions={<SearchBox value={q} onChange={setQ} placeholder="Name or email" />} flush>
        <DataTable rows={users.data} loading={users.isLoading} error={users.error} rowKey={(row) => row.id} columns={[
          { key: 'name', header: 'Name', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.email}</span></> },
          { key: 'role', header: 'Role', render: (row) => row.id === session!.user.id || row.role === 'super_admin' ? <Badge tone="teal">{ROLE_LABELS[row.role]}</Badge> : (
            <select className="select" style={{ minHeight: 32, width: 'auto' }} aria-label={`Role for ${row.name}`} value={row.role}
              onChange={(event) => change.mutate({ id: row.id, body: { role: event.target.value } })}>
              {ROLES.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
            </select>) },
          { key: 'locked', header: 'Sign-in', render: (row) => row.locked ? <Badge status="suspended">Locked</Badge> : row.failed_attempts ? <Badge status="pending">{`${row.failed_attempts} failed`}</Badge> : <Badge status="ok">OK</Badge> },
          { key: 'actions', header: '', align: 'right', render: (row) => row.id !== session!.user.id && (
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              {(row.locked || row.failed_attempts > 0) && <Button small variant="secondary" icon={LockOpen} onClick={() => change.mutate({ id: row.id, body: { unlock: true } })}>Unlock</Button>}
              <Button small variant="ghost" icon={Trash2} aria-label={`Remove ${row.name}`} onClick={() => setRemoving(row)} />
            </div>) },
        ]} />
      </Panel>
      {creating && <UserForm onClose={() => setCreating(false)} />}
      <Modal open={!!removing} title="Remove access?" onClose={() => setRemoving(null)}
        footer={<><Button variant="secondary" onClick={() => setRemoving(null)}>Cancel</Button><Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate(removing!.id)}>Remove access</Button></>}>
        <p>{removing?.name} will lose access to {session!.tenant.name} and be signed out. Their records (grades, payslips, invoices) are kept.</p>
      </Modal>
    </div>
  )
}

function UserForm({ onClose }: { onClose: () => void }) {
  const form = useForm({ name: '', email: '', role: 'student', password: '' })
  const save = useAction(() => post(`${AUTH}/users`, form.values), { invalidate: [`${AUTH}/users`], success: 'User added', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Add user" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Add user</Button></>}>
      <div className="form-grid">
        <Field label="Full name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Email" error={errors.email}><Input type="email" {...form.bind('email')} /></Field>
        <Field label="Role"><Select {...form.bind('role')} options={ROLES} /></Field>
        <Field label="Temporary password" wide hint="At least 12 characters. Ignored if the person already has an account in another institution." error={errors.password}>
          <Input type="password" autoComplete="new-password" {...form.bind('password')} />
        </Field>
      </div>
    </Modal>
  )
}

/* ---------------- Tenants ---------------- */
export function Tenants() {
  const { session } = useAuth()
  const tenants = useGet<R[]>('/api/v1/platform/tenants')
  const [creating, setCreating] = useState(false)
  const toggle = useAction((row: R) => patch(`/api/v1/platform/tenants/${row.id}`, { active: !row.active }), { invalidate: ['/api/v1/platform'], success: 'Institution updated' })
  return (
    <div className="stack">
      <PageHeader title="Institutions" subtitle="Each institution is an isolated tenant: every business row carries its tenant ID and PostgreSQL row-level security enforces the boundary."
        actions={<Button icon={Plus} onClick={() => setCreating(true)}>New institution</Button>} />
      <Panel title="Tenants" flush>
        <DataTable rows={tenants.data} loading={tenants.isLoading} error={tenants.error} rowKey={(row) => row.id} columns={[
          { key: 'name', header: 'Institution', render: (row) => <><strong>{row.name}</strong><span className="sub mono">{row.id}</span></> },
          { key: 'slug', header: 'Sign-in code', mono: true },
          { key: 'members', header: 'Members', align: 'right', mono: true },
          { key: 'active', header: 'Status', render: (row) => <Badge status={row.active ? 'active' : 'suspended'} /> },
          { key: 'actions', header: '', align: 'right', render: (row) => row.id !== session!.tenant.id && <Button small variant="secondary" onClick={() => toggle.mutate(row)}>{row.active ? 'Suspend' : 'Reactivate'}</Button> },
        ]} />
      </Panel>
      {creating && <TenantForm onClose={() => setCreating(false)} />}
    </div>
  )
}

function TenantForm({ onClose }: { onClose: () => void }) {
  const form = useForm({ slug: '', name: '', admin_name: '', admin_email: '', admin_password: '' })
  const save = useAction(() => post('/api/v1/platform/tenants', form.values), { invalidate: ['/api/v1/platform'], success: 'Institution provisioned', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Provision an institution" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={Building2} busy={save.isPending} onClick={() => save.mutate()}>Create institution</Button></>}>
      <div className="form-grid">
        <Field label="Institution name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Sign-in code" hint="Lowercase letters, numbers and dashes" error={errors.slug}><Input {...form.bind('slug')} /></Field>
        <Field label="First administrator" error={errors.admin_name}><Input {...form.bind('admin_name')} /></Field>
        <Field label="Administrator email" error={errors.admin_email}><Input type="email" {...form.bind('admin_email')} /></Field>
        <Field label="Temporary password" error={errors.admin_password}><Input type="password" autoComplete="new-password" {...form.bind('admin_password')} /></Field>
      </div>
    </Modal>
  )
}

/* ---------------- System status ---------------- */
const SERVICES = [
  { name: 'Identity & gateway auth', prefix: '/api/v1/auth' },
  { name: 'Academic', prefix: '/api/v1/academic' },
  { name: 'Marketing & finance', prefix: '/api/v1/finance' },
  { name: 'Administration & HR', prefix: '/api/v1/hr' },
]

export function System() {
  const checks = useQueries({ queries: SERVICES.map((service) => ({
    queryKey: [`${service.prefix}/health/ready`], queryFn: () => get<R>(`${service.prefix}/health/ready`), refetchInterval: 15_000, retry: false,
  })) })
  const host = window.location.hostname
  const tools = [
    ['Grafana dashboards & logs', `http://${host}:3000`], ['Prometheus metrics', `http://${host}:9090`],
    ['RabbitMQ management', `http://${host}:15672`], ['Mailpit (notification emails)', `http://${host}:8025`],
  ]
  return (
    <div className="stack">
      <PageHeader title="System status" subtitle="Live readiness of each independently deployed service, checked through the API gateway every 15 seconds." />
      <Panel title="Services" flush>
        <div className="status-grid">
          {SERVICES.map((service, index) => {
            const check = checks[index]
            const state = check.isLoading ? 'pending' : check.data?.status === 'ready' ? 'ready' : 'down'
            return (
              <div key={service.prefix} className="status-tile">
                <div className="row between"><strong>{service.name}</strong><Badge status={state}>{state === 'ready' ? 'Ready' : state === 'pending' ? 'Checking' : 'Unavailable'}</Badge></div>
                <span className="small mono muted">{service.prefix}</span>
                <a className="small" href={`${service.prefix}/docs`} target="_blank" rel="noreferrer">OpenAPI / Swagger <ExternalLink size={12} aria-hidden /></a>
                <span className="small muted">{check.dataUpdatedAt ? `Checked ${new Date(check.dataUpdatedAt).toLocaleTimeString('en-GB')}` : ''}</span>
              </div>
            )
          })}
        </div>
      </Panel>
      <Panel title="Operations tools" subtitle="Bound to localhost in the Docker Compose deployment." flush>
        <ul className="list">{tools.map(([name, url]) => <li key={url}><Activity size={16} aria-hidden /><div className="grow">{name}</div><a href={url} target="_blank" rel="noreferrer" className="mono small">{url.replace('http://', '')}</a></li>)}</ul>
      </Panel>
    </div>
  )
}

/* ---------------- Account ---------------- */
export function Account() {
  const { session, logout } = useAuth()
  const sessions = useGet<R[]>(`${AUTH}/sessions`)
  const revoke = useAction((id: string) => del(`${AUTH}/sessions/${id}`), { invalidate: [`${AUTH}/sessions`], success: 'Session signed out' })
  const form = useForm({ current_password: '', new_password: '', confirm: '' })
  const change = useAction(() => post(`${AUTH}/password`, { current_password: form.values.current_password, new_password: form.values.new_password }),
    { onSuccess: () => logout('Password changed. Please sign in again with your new password.') })
  const mismatch = form.values.confirm && form.values.confirm !== form.values.new_password
  const user = session!.user
  return (
    <div className="stack">
      <PageHeader title="Account & security" subtitle={`${user.name} · ${user.email} · ${ROLE_LABELS[user.role]} at ${session!.tenant.name}`} />
      <div className="grid cols-2">
        <Panel title="Active sessions" subtitle="Sessions end after 30 minutes of inactivity or 8 hours at most." flush>
          <DataTable rows={sessions.data} loading={sessions.isLoading} rowKey={(row) => row.id} columns={[
            { key: 'created_at', header: 'Signed in', render: (row) => dateTime(new Date(row.created_at * 1000).toISOString()) },
            { key: 'last_seen', header: 'Last active', render: (row) => dateTime(new Date(row.last_seen * 1000).toISOString()) },
            { key: 'current', header: '', align: 'right', render: (row) => row.current ? <Badge tone="teal">This device</Badge> : <Button small variant="secondary" onClick={() => revoke.mutate(row.id)}>Sign out</Button> },
          ]} />
        </Panel>
        <Panel title="Change password" subtitle="Changing your password signs out every session, including this one.">
          <form className="stack" onSubmit={(event) => { event.preventDefault(); change.mutate() }}>
            <Field label="Current password" error={fieldErrors(change.error).current_password}><Input type="password" autoComplete="current-password" {...form.bind('current_password')} /></Field>
            <Field label="New password" hint="At least 12 characters." error={fieldErrors(change.error).new_password}><Input type="password" autoComplete="new-password" {...form.bind('new_password')} /></Field>
            <Field label="Confirm new password" error={mismatch ? 'Passwords do not match.' : undefined}><Input type="password" autoComplete="new-password" {...form.bind('confirm')} /></Field>
            <Button type="submit" icon={KeyRound} busy={change.isPending} disabled={!form.values.current_password || form.values.new_password.length < 12 || Boolean(mismatch)}>Update password</Button>
          </form>
        </Panel>
      </div>
      <div className="callout teal"><ShieldCheck size={18} aria-hidden /><span>Passwords are stored with Argon2id. Access tokens live in memory for 10 minutes; refresh tokens are HttpOnly cookies rotated on every use, and reuse of an old token revokes the session.</span></div>
    </div>
  )
}
