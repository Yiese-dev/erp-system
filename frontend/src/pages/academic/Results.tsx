import { useState } from 'react'
import { Gavel, Info, Scale, Settings2 } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, Field, Input, Meter, Modal, PageHeader, Panel, Select, Tabs, Textarea } from '../../components/ui'
import { fieldErrors, post, put } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, dateTime, label, percent } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'

const A = '/api/v1/academic'

/* ---------------- Appeals ---------------- */
export function Appeals() {
  const { can } = useAuth()
  return can('academic:write', 'academic:teach') ? <StaffAppeals /> : <StudentAppeals />
}

function StaffAppeals() {
  const [status, setStatus] = useState('open')
  const appeals = useGet<R[]>(`${A}/appeals${status ? `?status=${status}` : ''}`)
  const [selected, setSelected] = useState<R | null>(null)
  return (
    <div className="stack">
      <PageHeader title="Grade appeals" subtitle="Students may appeal a published result within the appeal window. Approving an appeal creates a new result revision; the original mark is preserved." />
      <Panel title={<Tabs value={status} onChange={setStatus} items={[{ value: 'open', label: 'Open' }, { value: 'under_review', label: 'Under review' }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }, { value: '', label: 'All' }]} />} flush>
        <DataTable rows={appeals.data} loading={appeals.isLoading} error={appeals.error} rowKey={(row) => row.id} onRowClick={setSelected} empty="No appeals in this state." columns={[
          { key: 'student_name', header: 'Student', render: (row) => <strong>{row.student_name}</strong> },
          { key: 'course', header: 'Course', render: (row) => <>{row.course_code}<span className="sub">{row.course_title}</span></> },
          { key: 'original_score', header: 'Original', align: 'right', mono: true, render: (row) => row.original_score.toFixed(2) },
          { key: 'revised_score', header: 'Revised', align: 'right', mono: true, render: (row) => row.revised_score?.toFixed(2) ?? '—' },
          { key: 'created_at', header: 'Submitted', render: (row) => date(row.created_at) },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
      </Panel>
      {selected && <AppealDetail appeal={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function AppealDetail({ appeal, onClose }: { appeal: R; onClose: () => void }) {
  const form = useForm({ note: '', decision: 'approved', revised_score: String(appeal.original_score) })
  const review = useAction(() => post(`${A}/appeals/${appeal.id}/review`, { note: form.values.note }), { invalidate: [`${A}/appeals`], success: 'Appeal moved to review', onSuccess: onClose })
  const decide = useAction(() => post(`${A}/appeals/${appeal.id}/decision`, {
    decision: form.values.decision, note: form.values.note, revised_score: form.values.decision === 'approved' ? Number(form.values.revised_score) : null,
  }), { invalidate: [`${A}/appeals`, `${A}/offerings`, `${A}/dashboard`], success: 'Decision recorded', onSuccess: onClose })
  const open = appeal.status === 'open' || appeal.status === 'under_review'
  const errors = fieldErrors(decide.error ?? review.error)
  return (
    <Modal open size="lg" title={`Appeal · ${appeal.student_name} · ${appeal.course_code}`} onClose={onClose}
      footer={open ? <>
        <Button variant="secondary" onClick={onClose}>Close</Button>
        {appeal.status === 'open' && <Button variant="secondary" busy={review.isPending} disabled={form.values.note.length < 3} onClick={() => review.mutate()}>Start review</Button>}
        <Button icon={Gavel} busy={decide.isPending} disabled={form.values.note.length < 3} onClick={() => decide.mutate()}>Record decision</Button>
      </> : <Button variant="secondary" onClick={onClose}>Close</Button>}>
      <dl className="kv">
        <dt>Status</dt><dd><Badge status={appeal.status} /></dd>
        <dt>Original score</dt><dd className="mono">{appeal.original_score.toFixed(2)}</dd>
        {appeal.revised_score != null && <><dt>Revised score</dt><dd className="mono">{appeal.revised_score.toFixed(2)}</dd></>}
        <dt>Student's reason</dt><dd style={{ fontWeight: 400 }}>{appeal.reason}</dd>
        {appeal.decision_note && <><dt>Decision note</dt><dd style={{ fontWeight: 400 }}>{appeal.decision_note}</dd></>}
      </dl>
      <div><h3 style={{ marginBottom: 8 }}>History</h3>
        <ul className="timeline">{(appeal.history ?? []).map((item: R, index: number) => <li key={index}><strong>{label(item.status)}</strong> · {dateTime(item.at)}{item.note && <div className="muted">{item.note}</div>}</li>)}</ul>
      </div>
      {open && (
        <div className="form-grid">
          <Field label="Decision"><Select {...form.bind('decision')} options={[{ value: 'approved', label: 'Approve (revise mark)' }, { value: 'rejected', label: 'Reject (keep mark)' }]} /></Field>
          {form.values.decision === 'approved' && <Field label="Revised final score" error={errors.revised_score}><Input type="number" min={0} max={100} step="0.5" {...form.bind('revised_score')} /></Field>}
          <Field label="Reviewer note" wide error={errors.note} hint="Recorded on the appeal history and visible to the student."><Textarea {...form.bind('note')} /></Field>
        </div>
      )}
    </Modal>
  )
}

function StudentAppeals() {
  const appeals = useGet<R[]>(`${A}/appeals`)
  const results = useGet<R[]>(`${A}/me/results`)
  const policy = useGet<R>(`${A}/policy`)
  const [target, setTarget] = useState<R | null>(null)
  const windowDays = policy.data?.appeal_window_days ?? 14
  const pending = new Set((appeals.data ?? []).filter((row) => ['open', 'under_review'].includes(row.status)).map((row) => row.result_id))
  const eligible = (row: R) => row.current && !pending.has(row.id) && Date.now() - new Date(row.published_at).getTime() < windowDays * 86_400_000
  return (
    <div className="stack">
      <PageHeader title="Results & appeals" subtitle={`You can appeal a published result within ${windowDays} days of publication. Reviewers record their decision and any revised mark.`} />
      <Panel title="My appeals" flush>
        <DataTable rows={appeals.data} loading={appeals.isLoading} rowKey={(row) => row.id} empty="You have not submitted any appeals." columns={[
          { key: 'course', header: 'Course', render: (row) => <>{row.course_code}<span className="sub">{row.course_title}</span></> },
          { key: 'original_score', header: 'Original', align: 'right', mono: true, render: (row) => row.original_score.toFixed(2) },
          { key: 'revised_score', header: 'Revised', align: 'right', mono: true, render: (row) => row.revised_score?.toFixed(2) ?? '—' },
          { key: 'decision_note', header: 'Reviewer note', render: (row) => row.decision_note ?? <span className="muted">Awaiting review</span> },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
      </Panel>
      <Panel title="Published results" flush>
        <DataTable rows={results.data?.filter((row) => row.current)} loading={results.isLoading} rowKey={(row) => row.id} columns={[
          { key: 'course', header: 'Course', render: (row) => <>{row.course_code}<span className="sub">{row.term_name}</span></> },
          { key: 'score', header: 'Score', align: 'right', mono: true, render: (row) => row.score.toFixed(2) },
          { key: 'letter', header: 'Grade', align: 'center', render: (row) => <strong>{row.letter}</strong> },
          { key: 'published_at', header: 'Published', render: (row) => date(row.published_at) },
          { key: 'action', header: '', align: 'right', render: (row) => eligible(row) ? <Button small variant="secondary" icon={Scale} onClick={() => setTarget(row)}>Appeal</Button>
            : <span className="small muted">{pending.has(row.id) ? 'Appeal in progress' : 'Window closed'}</span> },
        ]} />
      </Panel>
      {target && <AppealForm result={target} onClose={() => setTarget(null)} />}
    </div>
  )
}

function AppealForm({ result, onClose }: { result: R; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const save = useAction(() => post(`${A}/appeals`, { result_id: result.id, reason }), { invalidate: [`${A}/appeals`, `${A}/dashboard`], success: 'Appeal submitted', onSuccess: onClose })
  return (
    <Modal open title={`Appeal ${result.course_code} (${result.score.toFixed(2)}, ${result.letter})`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={reason.trim().length < 10} onClick={() => save.mutate()}>Submit appeal</Button></>}>
      <Field label="Reason for appeal" hint="Explain which assessment or marking decision you believe is incorrect (at least 10 characters)." error={fieldErrors(save.error).reason}>
        <Textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} />
      </Field>
    </Modal>
  )
}

/* ---------------- At-risk ---------------- */
export function AtRisk() {
  const { can } = useAuth()
  const [flagged, setFlagged] = useState(true)
  const rows = useGet<R[]>(`${A}/risk${flagged ? '?only_flagged=true' : ''}`)
  const policy = useGet<R>(`${A}/policy`)
  const [editing, setEditing] = useState(false)
  const p = policy.data
  return (
    <div className="stack">
      <PageHeader title="At-risk students" subtitle="Early-warning flags for the current term, recalculated from live attendance and assessment records."
        actions={can('academic:write') && <Button variant="secondary" icon={Settings2} onClick={() => setEditing(true)}>Thresholds</Button>} />
      {p && (
        <div className="callout teal"><Info size={18} aria-hidden /><span><strong>Documented rule.</strong> A student is flagged in a course when attendance is below <b>{percent(p.attendance_threshold)}</b> (late counts as present, excused sessions are excluded)
          <b> or</b> their latest <b>{p.consecutive_failures}</b> assessment scores are all below <b>{p.failing_score}</b>. This is a transparent threshold rule, not a predictive model.</span></div>
      )}
      <Panel title={<Tabs value={flagged ? 'flagged' : 'all'} onChange={(value) => setFlagged(value === 'flagged')} items={[{ value: 'flagged', label: 'Flagged only' }, { value: 'all', label: 'All enrolments' }]} />} flush>
        <DataTable rows={rows.data} loading={rows.isLoading} error={rows.error} rowKey={(row) => `${row.student_id}-${row.offering_id}`} empty="No students are flagged for the current term." columns={[
          { key: 'student', header: 'Student', render: (row) => <><strong>{row.student_name}</strong><span className="sub">{row.student_no}</span></> },
          { key: 'course', header: 'Course', render: (row) => <>{row.course_code}<span className="sub">{row.course_title}</span></> },
          { key: 'attendance', header: 'Attendance', render: (row) => <div className="row"><Meter value={row.attendance_rate} warn={row.attendance_rate != null && row.attendance_rate < (p?.attendance_threshold ?? 0.75)} /><span className="mono">{percent(row.attendance_rate)}</span></div> },
          { key: 'scores', header: 'Latest scores', render: (row) => row.latest_scores.length ? row.latest_scores.map((score: number, index: number) => <span key={index} className={`score-cell ${score < (p?.failing_score ?? 50) ? 'score-fail' : ''}`}>{score}{index < row.latest_scores.length - 1 ? ' · ' : ''}</span>) : '—' },
          { key: 'reasons', header: 'Why flagged', render: (row) => row.reasons.length ? row.reasons.map((reason: R) => <div key={reason.code} className="small">{reason.message}</div>) : <span className="muted">—</span> },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
      </Panel>
      {editing && p && <PolicyForm policy={p} onClose={() => setEditing(false)} />}
    </div>
  )
}

function PolicyForm({ policy, onClose }: { policy: R; onClose: () => void }) {
  const form = useForm({ attendance_threshold: String(Math.round(policy.attendance_threshold * 100)), failing_score: String(policy.failing_score),
    consecutive_failures: String(policy.consecutive_failures), appeal_window_days: String(policy.appeal_window_days) })
  const save = useAction(() => put(`${A}/policy`, { attendance_threshold: Number(form.values.attendance_threshold) / 100, failing_score: Number(form.values.failing_score),
    consecutive_failures: Number(form.values.consecutive_failures), appeal_window_days: Number(form.values.appeal_window_days) }),
  { invalidate: [`${A}/policy`, `${A}/risk`, `${A}/dashboard`], success: 'Academic policy updated', onSuccess: onClose })
  return (
    <Modal open title="Academic policy thresholds" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Save policy</Button></>}>
      <div className="form-grid">
        <Field label="Minimum attendance (%)"><Input type="number" min={50} max={100} {...form.bind('attendance_threshold')} /></Field>
        <Field label="Failing score (below)"><Input type="number" min={1} max={100} {...form.bind('failing_score')} /></Field>
        <Field label="Consecutive failing assessments"><Input type="number" min={1} max={5} {...form.bind('consecutive_failures')} /></Field>
        <Field label="Appeal window (days)"><Input type="number" min={1} max={60} {...form.bind('appeal_window_days')} /></Field>
      </div>
    </Modal>
  )
}

/* ---------------- Student: my courses ---------------- */
export function MyCourses() {
  const courses = useGet<R>(`${A}/me/courses`)
  const results = useGet<R[]>(`${A}/me/results`)
  const data = courses.data
  const current = (data?.courses ?? []).filter((row: R) => row.results_status !== 'published')
  return (
    <div className="stack">
      <PageHeader title="My courses & results" subtitle={data ? `${data.student.name} · ${data.student.student_no} · ${data.student.program_name}` : undefined}
        actions={<DownloadButton path={`${A}/me/transcript.pdf`} filename="transcript.pdf" variant="primary" small={false}>Download transcript</DownloadButton>} />
      {courses.isLoading ? <Panel><Empty title="Loading…" /></Panel> : !current.length ? <Panel><Empty title="No current courses" /></Panel> : (
        <div className="grid cols-2">
          {current.map((course: R) => (
            <Panel key={course.id} title={`${course.course_code} · ${course.course_title}`} subtitle={`${course.term_name} · ${course.instructor_name} · ${course.room}`}
              actions={course.risk && <Badge status={course.risk.status} />} flush
              note={course.risk?.reasons.length ? course.risk.reasons.map((reason: R) => reason.message).join(' · ') : `Attendance ${percent(course.risk?.attendance_rate)}`}>
              <DataTable rows={course.assessments} rowKey={(row) => row.name} empty="No assessments yet." columns={[
                { key: 'name', header: 'Assessment' },
                { key: 'weight', header: 'Weight', align: 'right', render: (row) => `${row.weight}%` },
                { key: 'held_on', header: 'Date', render: (row) => date(row.held_on) },
                { key: 'score', header: 'Score', align: 'right', render: (row) => row.score == null ? <span className="muted">Pending</span> : <span className={`score-cell ${row.score < 50 ? 'score-fail' : ''}`}>{row.score.toFixed(1)}</span> },
              ]} />
            </Panel>
          ))}
        </div>
      )}
      <Panel title="Published results" subtitle="Superseded results remain listed for transparency." flush>
        <DataTable rows={results.data} loading={results.isLoading} rowKey={(row) => row.id} empty="No results published yet." columns={[
          { key: 'course', header: 'Course', render: (row) => <>{row.course_code}<span className="sub">{row.course_title}</span></> },
          { key: 'term_name', header: 'Term' },
          { key: 'credits', header: 'Credits', align: 'right', mono: true },
          { key: 'score', header: 'Score', align: 'right', render: (row) => <span className={`score-cell ${row.passed ? '' : 'score-fail'}`}>{row.score.toFixed(2)}</span> },
          { key: 'letter', header: 'Grade', align: 'center', render: (row) => <strong>{row.letter}</strong> },
          { key: 'revision', header: 'Record', render: (row) => row.current ? (row.revision > 1 ? <Badge status="approved">{`Revised (rev. ${row.revision})`}</Badge> : <Badge status="published">Current</Badge>) : <Badge status="closed">Superseded</Badge> },
        ]} />
      </Panel>
    </div>
  )
}
