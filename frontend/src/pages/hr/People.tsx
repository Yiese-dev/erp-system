import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Briefcase, CalendarDays, Check, CircleAlert, Package, Plus, Star, UserPlus, Users, X } from 'lucide-react'
import { Bars, Donut } from '../../components/charts'
import { Badge, Button, DataTable, Empty, ErrorState, Field, Input, Kpis, Loading, Modal, PageHeader, Pager, Panel, SearchBox, Select, Stars, Textarea } from '../../components/ui'
import { fieldErrors, patch, post, qs } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, label, money, percent, time, todayISO } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { Page, R } from '../../lib/hooks'

const H = '/api/v1/hr'

export function useDepartments() {
  const departments = useGet<R[]>(`${H}/departments`)
  return (departments.data ?? []).map((row) => ({ value: row.id, label: row.name }))
}

/* ---------------- Overview ---------------- */
export function HrOverview() {
  const { can } = useAuth()
  const query = useGet<R>(`${H}/dashboard`)
  const data = query.data
  const decide = useAction(({ id, decision }: { id: string; decision: string }) => post(`${H}/leave/${id}/decision`, { decision, note: decision === 'approved' ? 'Approved from dashboard' : 'Declined from dashboard' }),
    { invalidate: [`${H}/dashboard`, `${H}/leave`, `${H}/notifications`], success: 'Decision recorded and employee notified' })
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return (
    <div className="stack">
      <PageHeader title="People overview" subtitle="Headcount, attendance, leave and performance for the active institution."
        actions={<><Link className="btn btn-secondary" to="/hr/attendance">Attendance kiosk</Link><Link className="btn btn-primary" to="/hr/payroll">Payroll</Link></>} />
      <Kpis items={[
        { label: 'Headcount', value: String(data?.headcount ?? '—'), hint: `${data?.by_department.length ?? 0} departments`, icon: Users },
        { label: 'Present today', value: data ? `${data.present_today}` : '—', hint: `${percent(data?.attendance_rate_today)} of expected`, tone: 'green' },
        { label: 'On leave today', value: String(data?.on_leave_today ?? '—'), tone: 'blue', icon: CalendarDays },
        { label: 'Leave to approve', value: String(data?.pending_leave ?? '—'), tone: data?.pending_leave ? 'amber' : 'gray' },
        { label: 'Reviews completed', value: percent(data?.review_completion), hint: data?.review_period ?? '', tone: 'teal', icon: Star },
      ]} />
      {data && !data.rules_approved && (
        <div className="callout"><CircleAlert size={18} aria-hidden /><span>Payroll is blocked until HR verifies and approves the CNPS/IRPP statutory rule set against the official publications. <Link to="/hr/payroll">Review rules</Link></span></div>
      )}
      <div className="grid cols-main">
        <Panel title="Daily check-ins" subtitle="QR kiosk attendance over the last three weeks">
          {data ? <Bars height={240} data={data.attendance_trend.map((row: R) => ({ ...row, day: new Date(`${row.date}T00:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }) }))} x="day" series={[{ key: 'present', label: 'Present' }]} /> : <Loading />}
        </Panel>
        <Panel title="Leave awaiting approval" flush actions={<Link to="/hr/leave">All requests</Link>}>
          {!data ? <Loading /> : data.pending_requests.length ? (
            <ul className="list">{data.pending_requests.map((row: R) => (
              <li key={row.id}>
                <div className="grow"><div className="title">{row.employee_name}</div><div className="meta">{label(row.kind)} · {row.days} day(s) · {date(row.starts_on)} → {date(row.ends_on)}</div></div>
                {can('hr:write') && <><Button small variant="secondary" icon={Check} aria-label={`Approve ${row.employee_name}`} onClick={() => decide.mutate({ id: row.id, decision: 'approved' })} />
                  <Button small variant="ghost" icon={X} aria-label={`Decline ${row.employee_name}`} onClick={() => decide.mutate({ id: row.id, decision: 'rejected' })} /></>}
              </li>
            ))}</ul>
          ) : <Empty title="No pending leave" />}
        </Panel>
      </div>
      <div className="grid cols-3">
        <Panel title="Average rating by department" subtitle="Completed reviews (1–5)">
          {data ? (data.performance_by_department.length ? <Bars horizontal height={230} data={data.performance_by_department} x="department" series={[{ key: 'average', label: 'Average rating' }]} format={(value) => value.toFixed(2)} /> : <Empty />) : <Loading />}
        </Panel>
        <Panel title="Leave taken this year" subtitle="Approved days by type">
          {data ? (Object.keys(data.leave_days_by_kind).length ? <Donut data={Object.entries(data.leave_days_by_kind).map(([name, value]) => ({ name: label(name), value: value as number }))} format={(value) => `${value} days`} /> : <Empty />) : <Loading />}
        </Panel>
        <Panel title="Headcount by department">
          {data ? <Bars horizontal height={230} data={data.by_department} x="department" series={[{ key: 'headcount', label: 'Employees' }]} /> : <Loading />}
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Latest payroll" flush actions={<Link to="/hr/payroll">Open payroll</Link>}>
          {!data ? <Loading /> : data.latest_payroll ? (
            <dl className="kv" style={{ padding: 18 }}>
              <dt>Period</dt><dd>{data.latest_payroll.period} <Badge status={data.latest_payroll.status} /></dd>
              <dt>Employees paid</dt><dd>{data.latest_payroll.totals.headcount}</dd>
              <dt>Gross pay</dt><dd className="mono">{money(data.latest_payroll.totals.gross)}</dd>
              <dt>Net pay</dt><dd className="mono">{money(data.latest_payroll.totals.net)}</dd>
              <dt>CNPS (all parts)</dt><dd className="mono">{money(data.latest_payroll.totals.cnps)}</dd>
              <dt>IRPP + CAC</dt><dd className="mono">{money(data.latest_payroll.totals.irpp)}</dd>
            </dl>
          ) : <Empty title="No payroll run yet" icon={Briefcase} />}
        </Panel>
        <Panel title="Low stock" flush actions={<Link to="/hr/assets">Inventory</Link>}>
          {!data ? <Loading /> : data.low_stock.length ? (
            <ul className="list">{data.low_stock.map((item: R) => (
              <li key={item.id}><Package size={18} className="muted" aria-hidden /><div className="grow"><div className="title">{item.name}</div><div className="meta">{item.quantity} {item.unit} left · reorder at {item.reorder_level}</div></div><Badge status="issue">Reorder</Badge></li>
            ))}</ul>
          ) : <Empty title="Stock levels are healthy" />}
        </Panel>
      </div>
    </div>
  )
}

/* ---------------- Employees ---------------- */
export function Employees() {
  const { can } = useAuth()
  const departments = useDepartments()
  const [q, setQ] = useState('')
  const [department, setDepartment] = useState('')
  const [status, setStatus] = useState('active')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const employees = useGet<Page>(`${H}/employees${qs({ q, department_id: department, status, page, size: 20 })}`)
  return (
    <div className="stack">
      <PageHeader title="Employees" subtitle="Staff records drive payroll, attendance, leave entitlements and asset assignment."
        actions={can('hr:write') && <Button icon={UserPlus} onClick={() => setCreating(true)}>Add employee</Button>} />
      <Panel title={`${employees.data?.total ?? '…'} employees`}
        actions={<><Select aria-label="Status" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }} options={['active', 'suspended', 'terminated'].map((value) => ({ value, label: label(value) }))} />
          <Select aria-label="Department" value={department} onChange={(event) => { setDepartment(event.target.value); setPage(1) }} options={departments} placeholder="All departments" />
          <SearchBox value={q} onChange={(value) => { setQ(value); setPage(1) }} placeholder="Name, number or position" /></>} flush>
        <DataTable rows={employees.data?.items} loading={employees.isLoading} error={employees.error} rowKey={(row) => row.id} onRowClick={(row) => setSelected(row.id)} columns={[
          { key: 'employee_no', header: 'No.', mono: true },
          { key: 'name', header: 'Name', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.email}</span></> },
          { key: 'position', header: 'Position', render: (row) => <>{row.position}<span className="sub">{row.department}</span></> },
          { key: 'hired_on', header: 'Hired', render: (row) => date(row.hired_on) },
          { key: 'salary', header: 'Monthly gross', align: 'right', mono: true, render: (row) => money(row.base_salary + row.allowances) },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
        {employees.data && <Pager page={page} size={20} total={employees.data.total} onPage={setPage} />}
      </Panel>
      {creating && <EmployeeForm onClose={() => setCreating(false)} />}
      {selected && <EmployeeDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function EmployeeForm({ onClose }: { onClose: () => void }) {
  const departments = useDepartments()
  const form = useForm({ name: '', email: '', phone: '', department_id: '', position: '', base_salary: '', allowances: '0', hired_on: todayISO(), user_id: '' })
  const save = useAction(() => post(`${H}/employees`, { ...form.values, base_salary: Number(form.values.base_salary), allowances: Number(form.values.allowances || 0), user_id: form.values.user_id || null }),
    { invalidate: [`${H}/employees`, `${H}/dashboard`, `${H}/departments`], success: (row: R) => `${row.name} added as ${row.employee_no}`, onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Add employee" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Add employee</Button></>}>
      <div className="form-grid">
        <Field label="Full name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Email" error={errors.email}><Input type="email" {...form.bind('email')} /></Field>
        <Field label="Phone"><Input inputMode="tel" {...form.bind('phone')} /></Field>
        <Field label="Department" error={errors.department_id}><Select {...form.bind('department_id')} options={departments} placeholder="Choose" /></Field>
        <Field label="Position" error={errors.position}><Input {...form.bind('position')} /></Field>
        <Field label="Base salary (FCFA / month)" error={errors.base_salary}><Input type="number" min={1} {...form.bind('base_salary')} /></Field>
        <Field label="Taxable allowances (FCFA)"><Input type="number" min={0} {...form.bind('allowances')} /></Field>
        <Field label="Start date" error={errors.hired_on}><Input type="date" {...form.bind('hired_on')} /></Field>
        <Field label="Login user ID (optional)" hint="Enables self-service: check-in, leave, payslips."><Input {...form.bind('user_id')} placeholder="usr_…" /></Field>
      </div>
    </Modal>
  )
}

function EmployeeDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth()
  const departments = useDepartments()
  const detail = useGet<R>(`${H}/employees/${id}`)
  const data = detail.data
  const employee = data?.employee
  const form = useForm({ position: '', department_id: '', base_salary: '', allowances: '', status: '' })
  const [editing, setEditing] = useState(false)
  const save = useAction(() => patch(`${H}/employees/${id}`, Object.fromEntries(Object.entries({
    ...form.values, base_salary: form.values.base_salary ? Number(form.values.base_salary) : undefined, allowances: form.values.allowances ? Number(form.values.allowances) : undefined,
  }).filter(([, value]) => value !== '' && value !== undefined))), { invalidate: [`${H}/employees`], success: 'Employee updated', onSuccess: () => setEditing(false) })
  const startEdit = () => { form.setValues({ position: employee.position, department_id: employee.department_id, base_salary: String(employee.base_salary), allowances: String(employee.allowances), status: employee.status }); setEditing(true) }
  return (
    <Modal open size="lg" title={employee ? `${employee.name} · ${employee.employee_no}` : 'Employee'} onClose={onClose}
      footer={editing ? <><Button variant="secondary" onClick={() => setEditing(false)}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Save changes</Button></>
        : <><Button variant="secondary" onClick={onClose}>Close</Button>{can('hr:write') && employee && <Button onClick={startEdit}>Edit employment</Button>}</>}>
      {!data ? <Loading /> : editing ? (
        <div className="form-grid">
          <Field label="Position"><Input {...form.bind('position')} /></Field>
          <Field label="Department"><Select {...form.bind('department_id')} options={departments} /></Field>
          <Field label="Base salary"><Input type="number" {...form.bind('base_salary')} /></Field>
          <Field label="Allowances"><Input type="number" {...form.bind('allowances')} /></Field>
          <Field label="Status"><Select {...form.bind('status')} options={['active', 'suspended', 'terminated'].map((value) => ({ value, label: label(value) }))} /></Field>
        </div>
      ) : (
        <>
          <div className="grid cols-2">
            <dl className="kv">
              <dt>Position</dt><dd>{employee.position}</dd><dt>Department</dt><dd>{employee.department}</dd>
              <dt>Email</dt><dd>{employee.email}</dd><dt>Phone</dt><dd>{employee.phone || '—'}</dd>
            </dl>
            <dl className="kv">
              <dt>Hired</dt><dd>{date(employee.hired_on)}</dd><dt>Base salary</dt><dd className="mono">{money(employee.base_salary)}</dd>
              <dt>Allowances</dt><dd className="mono">{money(employee.allowances)}</dd><dt>Status</dt><dd><Badge status={employee.status} /></dd>
            </dl>
          </div>
          <Kpis items={data.balances.map((row: R) => ({ label: `${label(row.kind)} leave`, value: `${row.available} / ${row.entitled}`, hint: row.pending ? `${row.pending} pending` : 'days available', tone: 'blue' }))} />
          <div className="grid cols-2">
            <div><h3 style={{ marginBottom: 6 }}>Recent attendance</h3>
              <DataTable rows={data.attendance.slice(0, 8)} rowKey={(row) => row.id} empty="No check-ins in the last 30 days." columns={[
                { key: 'work_date', header: 'Date', render: (row) => date(row.work_date) }, { key: 'in', header: 'In', mono: true, render: (row) => time(row.check_in_at) },
                { key: 'out', header: 'Out', mono: true, render: (row) => time(row.check_out_at) },
              ]} /></div>
            <div><h3 style={{ marginBottom: 6 }}>Assets & reviews</h3>
              <ul className="list">
                {data.assets.map((asset: R) => <li key={asset.id}><Package size={16} aria-hidden /><div className="grow">{asset.tag} · {asset.name}</div></li>)}
                {data.reviews.map((review: R) => <li key={review.id}><Star size={16} aria-hidden /><div className="grow">{review.period}</div><Stars rating={review.rating} /></li>)}
                {!data.assets.length && !data.reviews.length && <li className="muted">None recorded.</li>}
              </ul></div>
          </div>
        </>
      )}
    </Modal>
  )
}

/* ---------------- Recruitment ---------------- */
const PIPELINE = ['applied', 'screened', 'interview', 'offered', 'hired', 'rejected']
const NEXT: Record<string, string> = { applied: 'screened', screened: 'interview', interview: 'offered', offered: 'hired' }

export function Recruitment() {
  const { can } = useAuth()
  const vacancies = useGet<R[]>(`${H}/recruitment/vacancies`)
  const [chosen, setChosen] = useState('')
  const vacancy = vacancies.data?.find((row) => row.id === chosen) ?? vacancies.data?.[0]
  const applicants = useGet<R[]>(vacancy ? `${H}/recruitment/applicants?vacancy_id=${vacancy.id}` : null)
  const [creating, setCreating] = useState<'vacancy' | 'applicant' | null>(null)
  const [advancing, setAdvancing] = useState<{ applicant: R; stage: string } | null>(null)
  const move = useAction(({ id, stage }: { id: string; stage: string }) => post(`${H}/recruitment/applicants/${id}/stage`, { stage }), { invalidate: [`${H}/recruitment`], success: 'Applicant updated' })
  const writer = can('hr:write')
  const go = (applicant: R, stage: string) => (stage === 'offered' || stage === 'hired' ? setAdvancing({ applicant, stage }) : move.mutate({ id: applicant.id, stage }))
  return (
    <div className="stack">
      <PageHeader title="Recruitment" subtitle="Applied → screened → interview → offered → hired. Hiring creates the employee record and leave entitlements automatically."
        actions={writer && <><Button variant="secondary" icon={Plus} onClick={() => setCreating('vacancy')}>New vacancy</Button><Button icon={UserPlus} disabled={!vacancy || vacancy.status !== 'open'} onClick={() => setCreating('applicant')}>Add applicant</Button></>} />
      <Panel title="Vacancies" flush>
        <DataTable rows={vacancies.data} loading={vacancies.isLoading} rowKey={(row) => row.id} onRowClick={(row) => setChosen(row.id)} empty="No vacancies yet." columns={[
          { key: 'title', header: 'Position', render: (row) => <><strong>{row.title}</strong>{row.id === vacancy?.id && <Badge tone="teal">Selected</Badge>}<span className="sub">{row.department}</span></> },
          { key: 'openings', header: 'Openings', align: 'right', mono: true },
          { key: 'applicants', header: 'Applicants', align: 'right', mono: true },
          { key: 'created_at', header: 'Posted', render: (row) => date(row.created_at) },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
      </Panel>
      {vacancy && (
        <Panel title={`Pipeline · ${vacancy.title}`} flush>
          {!applicants.data ? <Loading /> : (
            <div className="pipeline">
              {PIPELINE.map((stage) => {
                const rows = applicants.data!.filter((row) => row.stage === stage)
                return (
                  <div key={stage} className="pipeline-col">
                    <h3><span>{label(stage)}</span><span className="mono">{rows.length}</span></h3>
                    {rows.map((row) => (
                      <div key={row.id} className="card-item">
                        <strong>{row.name}</strong><span className="small muted">{row.email}</span>
                        {row.offered_salary && <div className="small mono">Offer {money(row.offered_salary)}</div>}
                        {writer && NEXT[stage] && (
                          <div className="row">
                            <Button small variant="secondary" onClick={() => go(row, NEXT[stage])}>{label(NEXT[stage] === 'screened' ? 'screen' : NEXT[stage] === 'hired' ? 'hire' : NEXT[stage] === 'offered' ? 'make offer' : NEXT[stage])}</Button>
                            <Button small variant="ghost" icon={X} aria-label={`Reject ${row.name}`} onClick={() => move.mutate({ id: row.id, stage: 'rejected' })} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          )}
        </Panel>
      )}
      {creating === 'vacancy' && <VacancyForm onClose={() => setCreating(null)} />}
      {creating === 'applicant' && vacancy && <ApplicantForm vacancyId={vacancy.id} onClose={() => setCreating(null)} />}
      {advancing && <OfferForm {...advancing} onClose={() => setAdvancing(null)} />}
    </div>
  )
}

function VacancyForm({ onClose }: { onClose: () => void }) {
  const departments = useDepartments()
  const form = useForm({ title: '', department_id: '', openings: '1', description: '' })
  const save = useAction(() => post(`${H}/recruitment/vacancies`, { ...form.values, openings: Number(form.values.openings) }), { invalidate: [`${H}/recruitment`], success: 'Vacancy posted', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="New vacancy" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Post vacancy</Button></>}>
      <div className="form-grid">
        <Field label="Position title" wide error={errors.title}><Input {...form.bind('title')} /></Field>
        <Field label="Department" error={errors.department_id}><Select {...form.bind('department_id')} options={departments} placeholder="Choose" /></Field>
        <Field label="Openings"><Input type="number" min={1} {...form.bind('openings')} /></Field>
        <Field label="Description" wide><Textarea {...form.bind('description')} /></Field>
      </div>
    </Modal>
  )
}

function ApplicantForm({ vacancyId, onClose }: { vacancyId: string; onClose: () => void }) {
  const form = useForm({ name: '', email: '', phone: '' })
  const save = useAction(() => post(`${H}/recruitment/applicants`, { ...form.values, vacancy_id: vacancyId }), { invalidate: [`${H}/recruitment`], success: 'Applicant added', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Add applicant" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Add</Button></>}>
      <div className="form-grid">
        <Field label="Full name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Email" error={errors.email}><Input type="email" {...form.bind('email')} /></Field>
        <Field label="Phone"><Input inputMode="tel" {...form.bind('phone')} /></Field>
      </div>
    </Modal>
  )
}

function OfferForm({ applicant, stage, onClose }: { applicant: R; stage: string; onClose: () => void }) {
  const [salary, setSalary] = useState(String(applicant.offered_salary ?? ''))
  const [start, setStart] = useState(todayISO())
  const save = useAction(() => post(`${H}/recruitment/applicants/${applicant.id}/stage`, stage === 'offered' ? { stage, offered_salary: Number(salary) } : { stage, start_date: start }),
    { invalidate: [`${H}/recruitment`, `${H}/employees`, `${H}/dashboard`], success: stage === 'hired' ? `${applicant.name} hired · employee record created` : 'Offer recorded', onSuccess: onClose })
  return (
    <Modal open title={stage === 'hired' ? `Hire ${applicant.name}` : `Make an offer to ${applicant.name}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={stage === 'offered' ? !salary : !start} onClick={() => save.mutate()}>{stage === 'hired' ? 'Confirm hire' : 'Record offer'}</Button></>}>
      {stage === 'offered'
        ? <Field label="Monthly base salary (FCFA)"><Input type="number" min={1} value={salary} onChange={(event) => setSalary(event.target.value)} /></Field>
        : <><p>An employee record will be created at the offered salary of <strong>{money(applicant.offered_salary)}</strong>.</p><Field label="Start date"><Input type="date" value={start} onChange={(event) => setStart(event.target.value)} /></Field></>}
    </Modal>
  )
}
