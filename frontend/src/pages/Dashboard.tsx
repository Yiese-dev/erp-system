import { Link } from 'react-router-dom'
import { ArrowRight, BookOpen, CalendarClock, CircleAlert, ClipboardCheck, GraduationCap, Scale, TriangleAlert, Users, Wallet } from 'lucide-react'
import { Bars, PALETTE } from '../components/charts'
import { Badge, DataTable, Empty, ErrorState, Kpis, Loading, Meter, PageHeader, Panel } from '../components/ui'
import { useAuth } from '../lib/auth'
import { dateTime, money, monthLabel, num, percent } from '../lib/format'
import { useGet } from '../lib/hooks'
import type { R } from '../lib/hooks'
import { FinanceOverview } from './finance/Finance'
import { HrOverview } from './hr/People'
import { MyHr } from './hr/Presence'
import { Tenants } from './admin/Admin'

export function greeting(name: string) {
  const hour = Number(new Date().toLocaleString('en-GB', { hour: '2-digit', hour12: false, timeZone: 'Africa/Douala' }))
  const first = name.replace(/^Dr\.?\s+/i, '').split(' ')[0]
  return `${hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'}, ${first}`
}

const today = () => new Date().toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Africa/Douala' })

function Section({ query, children }: { query: { data?: unknown; error: unknown; refetch: () => unknown }; children: () => React.ReactNode }) {
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />
  if (!query.data) return <Loading />
  return <>{children()}</>
}

export function ExamList({ exams }: { exams: R[] }) {
  if (!exams.length) return <Empty icon={CalendarClock} title="No upcoming exams" text="Scheduled examinations will appear here." />
  return (
    <ul className="list">
      {exams.slice(0, 6).map((exam) => (
        <li key={exam.id}>
          <CalendarClock size={18} className="muted" aria-hidden />
          <div className="grow"><div className="title">{exam.course_code} · {exam.title}</div><div className="meta">{dateTime(exam.starts_at)} · {exam.room}</div></div>
        </li>
      ))}
    </ul>
  )
}

function RiskList({ rows }: { rows: R[] }) {
  if (!rows.length) return <Empty icon={GraduationCap} title="No students flagged" text="Everyone is currently above the attendance and grade thresholds." />
  return (
    <ul className="list">
      {rows.slice(0, 6).map((row) => (
        <li key={`${row.student_id}-${row.offering_id}`}>
          <TriangleAlert size={18} color="#b44c3b" aria-hidden />
          <div className="grow"><div className="title">{row.student_name}</div><div className="meta">{row.course_code} · {row.reasons.map((reason: R) => reason.message).join('; ')}</div></div>
        </li>
      ))}
    </ul>
  )
}

function AdminDashboard() {
  const { session } = useAuth()
  const academic = useGet('/api/v1/academic/dashboard')
  const finance = useGet('/api/v1/finance/dashboard')
  const hr = useGet('/api/v1/hr/dashboard')
  const a = academic.data as R, f = finance.data as R, h = hr.data as R
  const approvals = (h?.pending_leave ?? 0) + (a?.totals.pending_appeals ?? 0) + (f?.totals.pending_expenses ?? 0)
  return (
    <div className="stack">
      <PageHeader title={greeting(session!.user.name)} subtitle={`${session!.tenant.name} · ${a?.term?.name ?? 'Current term'} · ${today()}`}
        actions={<><Link className="btn btn-secondary" to="/finance/reports">Monthly reports</Link><Link className="btn btn-primary" to="/academic/students">Register a student</Link></>} />
      <Kpis items={[
        { label: 'Active students', value: num(a?.totals.students), hint: `${num(a?.totals.registrations)} registered this term`, icon: GraduationCap },
        { label: 'At-risk students', value: num(a?.totals.at_risk), hint: 'Attendance or grade threshold', tone: 'coral', icon: TriangleAlert },
        { label: 'Fees collected', value: money(f?.totals.collected), hint: `${percent(f?.totals.collection_rate)} of billed`, tone: 'green', icon: Wallet },
        { label: 'Outstanding', value: money(f?.totals.outstanding), hint: `${money(f?.totals.overdue)} overdue`, tone: 'amber' },
        { label: 'Staff present', value: h ? `${h.present_today} / ${h.headcount}` : '—', hint: `${h?.on_leave_today ?? 0} on leave today`, tone: 'blue', icon: Users },
        { label: 'Awaiting approval', value: num(approvals), hint: 'Leave, appeals, expenses', tone: 'gray', icon: Scale },
      ]} />
      <div className="grid cols-main">
        <Panel title="Collections, billing and expenses" subtitle="Last nine months · FCFA">
          <Section query={finance}>{() => (
            <Bars data={f.monthly.map((row: R) => ({ ...row, month: monthLabel(row.period) }))} x="month" money
              series={[{ key: 'collected', label: 'Collected' }, { key: 'billed', label: 'Billed', color: PALETTE[2] }, { key: 'expenses', label: 'Expenses', color: PALETTE[1] }]} />
          )}</Section>
        </Panel>
        <Panel title="Registrations by programme" subtitle={a?.term?.name}>
          <Section query={academic}>{() => (
            a.enrollment_by_program.length ? <Bars data={a.enrollment_by_program} x="code" series={[{ key: 'registrations', label: 'Registrations' }]} />
              : <Empty text="No registrations for the current term yet." />
          )}</Section>
        </Panel>
      </div>
      <div className="grid cols-3">
        <Panel title="Students flagged at risk" flush actions={<Link to="/academic/risk">All flags</Link>}>
          <Section query={academic}>{() => <RiskList rows={a.at_risk} />}</Section>
        </Panel>
        <Panel title="Leave awaiting approval" flush actions={<Link to="/hr/leave">Review</Link>}>
          <Section query={hr}>{() => h.pending_requests.length ? (
            <ul className="list">{h.pending_requests.map((row: R) => (
              <li key={row.id}><div className="grow"><div className="title">{row.employee_name}</div><div className="meta">{row.kind} · {row.days} day(s) from {row.starts_on}</div></div><Badge status="pending" /></li>
            ))}</ul>
          ) : <Empty title="Nothing pending" />}</Section>
        </Panel>
        <Panel title="Upcoming examinations" flush actions={<Link to="/academic/exams">Timetable</Link>}>
          <Section query={academic}>{() => <ExamList exams={a.upcoming_exams} />}</Section>
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Staff check-ins" subtitle="Employees present per working day (QR kiosk)">
          <Section query={hr}>{() => <Bars height={210} data={h.attendance_trend.map((row: R) => ({ ...row, day: row.date.slice(5) }))} x="day" series={[{ key: 'present', label: 'Present' }]} />}</Section>
        </Panel>
        <Panel title="Billing pipeline" subtitle="Current-term registrations by invoice status (updated asynchronously)">
          <Section query={academic}>{() => (
            <div className="stack">
              <div className="row">{Object.entries(a.billing as Record<string, number>).map(([status, count]) => <Badge key={status} status={status}>{`${status}: ${count}`}</Badge>)}</div>
              {f?.billing_issues ? <div className="callout"><CircleAlert size={18} aria-hidden /><span>{f.billing_issues} registration(s) could not be invoiced. <Link to="/finance/fee-plans">Resolve billing issues</Link></span></div>
                : <div className="callout teal"><ClipboardCheck size={18} aria-hidden /><span>Every confirmed registration has been billed. Ledger {f?.ledger_balanced ? 'balanced' : 'check pending'}.</span></div>}
            </div>
          )}</Section>
        </Panel>
      </div>
    </div>
  )
}

function InstructorDashboard() {
  const { session } = useAuth()
  const query = useGet('/api/v1/academic/dashboard')
  const data = query.data as R
  const students = data?.offerings.reduce((sum: number, row: R) => sum + row.enrolled, 0)
  return (
    <div className="stack">
      <PageHeader title={greeting(session!.user.name)} subtitle={`${data?.term?.name ?? ''} · ${today()}`}
        actions={<Link className="btn btn-primary" to="/academic/gradebook">Open gradebook</Link>} />
      <Kpis items={[
        { label: 'My course offerings', value: num(data?.offerings.length), icon: BookOpen },
        { label: 'Students taught', value: num(students), tone: 'blue', icon: Users },
        { label: 'At-risk enrolments', value: num(data?.at_risk.length), tone: 'coral', icon: TriangleAlert },
        { label: 'Appeals to review', value: num(data?.pending_appeals), tone: 'amber', icon: Scale },
      ]} />
      <Panel title="My courses this term" flush>
        <DataTable rows={data?.offerings} loading={query.isLoading} error={query.error} retry={() => query.refetch()} rowKey={(row) => row.id} columns={[
          { key: 'course', header: 'Course', render: (row) => <><strong>{row.course_code}</strong><span className="sub">{row.course_title}</span></> },
          { key: 'room', header: 'Room' },
          { key: 'enrolled', header: 'Students', align: 'right', mono: true },
          { key: 'attendance', header: 'Attendance', render: (row) => <div className="row"><Meter value={row.attendance_rate} warn={row.attendance_rate != null && row.attendance_rate < 0.75} /><span className="mono">{percent(row.attendance_rate)}</span></div> },
          { key: 'average', header: 'Avg. recent score', align: 'right', mono: true, render: (row) => row.average_score ?? '—' },
          { key: 'risk', header: 'At risk', render: (row) => row.at_risk ? <Badge status="at_risk">{`${row.at_risk} student(s)`}</Badge> : <Badge status="on_track" /> },
          { key: 'go', header: '', render: (row) => <Link to={`/academic/gradebook?offering=${row.id}`} aria-label={`Open ${row.course_code} gradebook`}><ArrowRight size={16} /></Link> },
        ]} />
      </Panel>
      <div className="grid cols-2">
        <Panel title="Students needing attention" flush actions={<Link to="/academic/risk">Details</Link>}><Section query={query}>{() => <RiskList rows={data.at_risk} />}</Section></Panel>
        <Panel title="My upcoming exams" flush><Section query={query}>{() => <ExamList exams={data.upcoming_exams} />}</Section></Panel>
      </div>
    </div>
  )
}

function StudentDashboard() {
  const { session } = useAuth()
  const academic = useGet('/api/v1/academic/dashboard')
  const finance = useGet('/api/v1/finance/me/summary')
  const a = academic.data as R, f = finance.data as R
  const flagged = a?.courses.filter((row: R) => row.status === 'at_risk') ?? []
  const current = a?.courses.filter((row: R) => row.latest_scores.length || row.attendance_rate != null) ?? []
  return (
    <div className="stack">
      <PageHeader title={greeting(session!.user.name)} subtitle={a ? `${a.student.program_name} · ${a.student.student_no}` : today()}
        actions={<><Link className="btn btn-secondary" to="/academic/me">My results</Link><Link className="btn btn-primary" to="/finance/pay">Pay fees</Link></>} />
      <Kpis items={[
        { label: 'Attendance', value: percent(a?.attendance_rate), hint: 'All courses, excused absences excluded', tone: a?.attendance_rate != null && a.attendance_rate < 0.75 ? 'coral' : 'green' },
        { label: 'Credits earned', value: num(a?.credits_earned), tone: 'blue', icon: GraduationCap },
        { label: 'Weighted average', value: a?.average != null ? `${a.average.toFixed(1)} / 100` : '—' },
        { label: 'Fee balance', value: money(f?.balance), hint: f?.balance ? 'Pay by mobile money' : 'All settled', tone: f?.balance ? 'amber' : 'green', icon: Wallet },
        { label: 'Open appeals', value: num(a?.open_appeals), tone: 'gray', icon: Scale },
      ]} />
      {flagged.length > 0 && (
        <div className="callout"><TriangleAlert size={18} aria-hidden /><div><strong>Academic early warning.</strong> You are flagged in {flagged.map((row: R) => row.course_code).join(', ')}:
          <ul>{flagged.flatMap((row: R) => row.reasons.map((reason: R) => <li key={row.offering_id + reason.code}>{row.course_code}: {reason.message}</li>))}</ul>
          Please speak to your instructor or academic advisor.</div></div>
      )}
      <div className="grid cols-main">
        <Panel title="My courses this term" flush>
          <DataTable rows={current} loading={academic.isLoading} error={academic.error} rowKey={(row) => row.offering_id} columns={[
            { key: 'course', header: 'Course', render: (row) => <><strong>{row.course_code}</strong><span className="sub">{row.course_title}</span></> },
            { key: 'attendance', header: 'Attendance', render: (row) => <div className="row"><Meter value={row.attendance_rate} warn={row.attendance_rate != null && row.attendance_rate < 0.75} /><span className="mono">{percent(row.attendance_rate)}</span></div> },
            { key: 'scores', header: 'Recent scores', render: (row) => row.latest_scores.length ? row.latest_scores.map((score: number, index: number) => <span key={index} className={`score-cell ${score < 50 ? 'score-fail' : ''}`}>{score}{index < row.latest_scores.length - 1 ? ' · ' : ''}</span>) : '—' },
            { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
          ]} empty="You are not enrolled in any courses this term." />
        </Panel>
        <div className="stack">
          <Panel title="Upcoming exams" flush><Section query={academic}>{() => <ExamList exams={a.upcoming_exams} />}</Section></Panel>
          <Panel title="Fees" flush actions={<Link to="/finance/pay">Payments</Link>}>
            <Section query={finance}>{() => f.invoices.length ? (
              <ul className="list">{f.invoices.slice(0, 4).map((row: R) => (
                <li key={row.id}><div className="grow"><div className="title">{row.term_name}</div><div className="meta">{row.number} · balance {money(row.balance)}</div></div><Badge status={row.overdue ? 'overdue' : row.status} /></li>
              ))}</ul>
            ) : <Empty title="No invoices yet" text="Invoices appear automatically after registration." />}</Section>
          </Panel>
        </div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { session } = useAuth()
  switch (session!.user.role) {
    case 'admin': return <AdminDashboard />
    case 'instructor': return <InstructorDashboard />
    case 'student': return <StudentDashboard />
    case 'finance': return <FinanceOverview />
    case 'hr': return <HrOverview />
    case 'employee': return <MyHr />
    default: return <Tenants />
  }
}
