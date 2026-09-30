import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CalendarPlus, CircleAlert, CircleCheck, ClipboardList, Lock, Plus, Send, Trash2 } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, ErrorState, Field, Input, Loading, Meter, Modal, PageHeader, Panel, Select } from '../../components/ui'
import { ApiError, del, fieldErrors, post, put } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, percent, time, todayISO } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'
import { useInstructors } from './Catalogue'

const A = '/api/v1/academic'
const STATUSES = [['present', 'P'], ['late', 'L'], ['absent', 'A'], ['excused', 'E']] as const

function useOfferingPicker() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const offerings = useGet<R[]>(`${A}/offerings${can('academic:write') ? '' : '?mine=true'}`)
  const sorted = useMemo(() => [...(offerings.data ?? [])].sort((a, b) => (b.term_name + a.course_code).localeCompare(a.term_name + b.course_code)), [offerings.data])
  const chosen = params.get('offering') || sorted[0]?.id || ''
  const current = sorted.find((row) => row.id === chosen)
  const picker = (
    <Select aria-label="Course offering" value={chosen} onChange={(event) => setParams({ offering: event.target.value })}
      options={sorted.map((row) => ({ value: row.id, label: `${row.course_code} · ${row.course_title} · ${row.term_name}` }))} />
  )
  return { offerings, chosen, current, picker }
}

/* ---------------- Gradebook ---------------- */
export function Gradebook() {
  const { chosen, current, picker, offerings } = useOfferingPicker()
  const book = useGet<R>(chosen ? `${A}/offerings/${chosen}/gradebook` : null)
  const published = book.data?.offering.results_status === 'published'
  const results = useGet<R[]>(published ? `${A}/offerings/${chosen}/results` : null)
  const [adding, setAdding] = useState(false)
  const [marking, setMarking] = useState<R | null>(null)
  const [confirming, setConfirming] = useState(false)
  const publish = useAction(() => post(`${A}/offerings/${chosen}/results/publish`), {
    invalidate: [`${A}/offerings`, `${A}/dashboard`], success: 'Results published to students', onSuccess: () => setConfirming(false), silent: true,
  })
  const failure = publish.error instanceof ApiError ? publish.error : null
  const assessments: R[] = book.data?.assessments ?? []
  const graded = (row: R) => {
    const done = assessments.filter((item) => row.scores[item.id] != null)
    const weight = done.reduce((sum, item) => sum + item.weight, 0)
    return weight ? done.reduce((sum, item) => sum + row.scores[item.id] * item.weight, 0) / weight : null
  }
  if (offerings.data && !offerings.data.length) return <><PageHeader title="Gradebook" /><Panel><Empty icon={ClipboardList} title="No course offerings assigned" /></Panel></>
  return (
    <div className="stack">
      <PageHeader title="Gradebook" subtitle="Record assessment marks, then publish final results once weights total 100%. Published results can only change through a grade appeal."
        actions={<div style={{ minWidth: 320 }}>{picker}</div>} />
      <Panel title={current ? `${current.course_code} · ${current.course_title}` : 'Gradebook'}
        subtitle={book.data && `${book.data.students.length} students · assessment weights total ${book.data.total_weight}%`}
        actions={book.data && (published ? <Badge status="published">Results published</Badge> : <>
          <Button variant="secondary" icon={Plus} onClick={() => setAdding(true)} disabled={book.data.total_weight >= 100}>Add assessment</Button>
          <Button icon={Send} onClick={() => { publish.reset(); setConfirming(true) }} disabled={book.data.total_weight !== 100}>Publish results</Button></>)} flush>
        {book.error ? <ErrorState error={book.error} retry={() => book.refetch()} /> : !book.data ? <Loading /> : (
          <>
            {!published && assessments.length > 0 && (
              <div className="row" style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-soft)' }}>
                <span className="small muted">Enter marks:</span>
                {assessments.map((item) => <Button key={item.id} small variant="secondary" onClick={() => setMarking(item)}>{item.name}</Button>)}
              </div>
            )}
            <DataTable rows={book.data.students} rowKey={(row) => row.id} empty="No students are enrolled in this offering." columns={[
              { key: 'student', header: 'Student', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.student_no}</span></> },
              ...assessments.map((item) => ({
                key: item.id, header: `${item.name} · ${item.weight}%`, align: 'right' as const,
                render: (row: R) => row.scores[item.id] == null ? <span className="muted">—</span> : <span className={`score-cell ${row.scores[item.id] < 50 ? 'score-fail' : ''}`}>{row.scores[item.id].toFixed(1)}</span>,
              })),
              { key: 'running', header: 'Weighted so far', align: 'right', render: (row) => { const value = graded(row); return value == null ? '—' : <strong className={`score-cell ${value < 50 ? 'score-fail' : ''}`}>{value.toFixed(1)}</strong> } },
            ]} />
          </>
        )}
      </Panel>
      {published && (
        <Panel title="Published results" subtitle={<><Lock size={13} aria-hidden /> Locked. Revisions are created through the grade-appeal workflow.</>} flush>
          <DataTable rows={results.data} loading={results.isLoading} rowKey={(row) => row.id} columns={[
            { key: 'student_name', header: 'Student' },
            { key: 'score', header: 'Final score', align: 'right', render: (row) => <span className={`score-cell ${row.passed ? '' : 'score-fail'}`}>{row.score.toFixed(2)}</span> },
            { key: 'letter', header: 'Grade', align: 'center', render: (row) => <strong>{row.letter}</strong> },
            { key: 'passed', header: 'Outcome', render: (row) => <Badge status={row.passed ? 'passed' : 'failed'} tone={row.passed ? 'green' : 'coral'}>{row.passed ? 'Passed' : 'Failed'}</Badge> },
            { key: 'revision', header: 'Revision', render: (row) => row.revision > 1 ? <Badge status="revised" tone="amber">{`Rev. ${row.revision}`}</Badge> : 'Original' },
          ]} />
        </Panel>
      )}
      <AssessmentForm open={adding} offeringId={chosen} remaining={100 - (book.data?.total_weight ?? 0)} onClose={() => setAdding(false)} />
      {marking && book.data && <MarksModal assessment={marking} students={book.data.students} onClose={() => setMarking(null)} />}
      <Modal open={confirming} title="Publish final results?" onClose={() => setConfirming(false)}
        footer={<><Button variant="secondary" onClick={() => setConfirming(false)}>Cancel</Button><Button icon={Send} busy={publish.isPending} onClick={() => publish.mutate()}>Publish now</Button></>}>
        <p>Final scores are calculated from the weighted assessments and released to every enrolled student. After publication marks are locked and students have 14 days to appeal.</p>
        {failure && <div className="error-box" role="alert"><CircleAlert size={18} aria-hidden /><div>{failure.message}
          {Array.isArray(failure.details) && <ul>{(failure.details as R[]).slice(0, 8).map((item, index) => <li key={index}>{item.student}: {item.assessment}</li>)}</ul>}</div></div>}
      </Modal>
    </div>
  )
}

function AssessmentForm({ open, offeringId, remaining, onClose }: { open: boolean; offeringId: string; remaining: number; onClose: () => void }) {
  const form = useForm({ name: '', weight: String(Math.min(remaining, 20) || ''), held_on: todayISO() })
  const save = useAction(() => post(`${A}/offerings/${offeringId}/assessments`, { ...form.values, weight: Number(form.values.weight) }),
    { invalidate: [`${A}/offerings/${offeringId}`], success: 'Assessment added', onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="Add assessment" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="assessment-form" busy={save.isPending}>Add</Button></>}>
      <form id="assessment-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} placeholder="Midterm exam" required /></Field>
        <Field label="Weight (%)" hint={`${remaining}% still unallocated`} error={errors.weight}><Input type="number" min={1} max={remaining} {...form.bind('weight')} /></Field>
        <Field label="Date" error={errors.held_on}><Input type="date" {...form.bind('held_on')} /></Field>
      </form>
    </Modal>
  )
}

function MarksModal({ assessment, students, onClose }: { assessment: R; students: R[]; onClose: () => void }) {
  const [marks, setMarks] = useState<Record<string, string>>(() => Object.fromEntries(students.map((row) => [row.id, row.scores[assessment.id]?.toString() ?? ''])))
  const invalid = Object.values(marks).some((value) => value !== '' && (Number.isNaN(Number(value)) || Number(value) < 0 || Number(value) > 100))
  const save = useAction(() => put(`${A}/assessments/${assessment.id}/grades`, {
    entries: Object.entries(marks).filter(([, value]) => value !== '').map(([student_id, value]) => ({ student_id, score: Number(value) })),
  }), { invalidate: [`${A}/offerings`, `${A}/risk`, `${A}/dashboard`], success: (result: R) => `${result.saved} mark(s) saved`, onSuccess: onClose })
  return (
    <Modal open size="lg" title={`Marks · ${assessment.name} (${assessment.weight}%)`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="marks-form" busy={save.isPending} disabled={invalid}>Save marks</Button></>}>
      <form id="marks-form" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <div className="table-wrap"><table className="data"><thead><tr><th>Student</th><th style={{ width: 140 }}>Score / 100</th></tr></thead><tbody>
          {students.map((row) => {
            const value = marks[row.id]
            const bad = value !== '' && (Number.isNaN(Number(value)) || Number(value) < 0 || Number(value) > 100)
            return (
              <tr key={row.id}><td><strong>{row.name}</strong><span className="sub">{row.student_no}</span></td>
                <td><Input type="number" step="0.5" min={0} max={100} value={value} aria-label={`Score for ${row.name}`} aria-invalid={bad}
                  onChange={(event) => setMarks({ ...marks, [row.id]: event.target.value })} /></td></tr>
            )
          })}
        </tbody></table></div>
      </form>
    </Modal>
  )
}

/* ---------------- Class attendance ---------------- */
export function ClassAttendance() {
  const { chosen, current, picker } = useOfferingPicker()
  const data = useGet<R>(chosen ? `${A}/offerings/${chosen}/attendance` : null)
  const policy = useGet<R>(`${A}/policy`)
  const [recording, setRecording] = useState(false)
  const threshold = policy.data?.attendance_threshold ?? 0.75
  return (
    <div className="stack">
      <PageHeader title="Class attendance" subtitle="Record each lesson; late arrivals count as attended and excused absences are excluded from the rate."
        actions={<div style={{ minWidth: 320 }}>{picker}</div>} />
      <div className="grid cols-main">
        <Panel title={current ? `${current.course_code} attendance summary` : 'Summary'} subtitle={`Students below ${percent(threshold)} are flagged`}
          actions={chosen && <><DownloadButton path={`${A}/reports/offerings/${chosen}/attendance.pdf`} filename="attendance.pdf">Attendance PDF</DownloadButton>
            <Button icon={CalendarPlus} onClick={() => setRecording(true)}>Record lesson</Button></>} flush>
          <DataTable rows={data.data?.summary} loading={data.isLoading} error={data.error} rowKey={(row) => row.student_no} empty="No students enrolled." columns={[
            { key: 'name', header: 'Student', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.student_no}</span></> },
            { key: 'present', header: 'Present', align: 'right', mono: true },
            { key: 'late', header: 'Late', align: 'right', mono: true },
            { key: 'absent', header: 'Absent', align: 'right', mono: true },
            { key: 'excused', header: 'Excused', align: 'right', mono: true },
            { key: 'rate', header: 'Rate', render: (row) => <div className="row"><Meter value={row.rate} warn={row.rate != null && row.rate < threshold} /><span className="mono">{percent(row.rate)}</span>
              {row.rate != null && row.rate < threshold && <Badge status="at_risk">Below threshold</Badge>}</div> },
          ]} />
        </Panel>
        <Panel title="Recorded lessons" flush>
          {data.data?.sessions.length ? (
            <ul className="list">{data.data.sessions.slice(0, 12).map((lesson: R) => {
              const values = Object.values(lesson.records as Record<string, string>)
              const attended = values.filter((status) => status === 'present' || status === 'late').length
              return <li key={lesson.id}><div className="grow"><div className="title">{date(lesson.held_on)}</div><div className="meta">{lesson.topic || 'Lecture'}</div></div><span className="mono">{attended}/{values.length}</span></li>
            })}</ul>
          ) : data.data ? <Empty title="No lessons recorded" /> : <Loading />}
        </Panel>
      </div>
      {recording && chosen && <AttendanceModal offeringId={chosen} sessions={data.data?.sessions ?? []} onClose={() => setRecording(false)} />}
    </div>
  )
}

function AttendanceModal({ offeringId, sessions, onClose }: { offeringId: string; sessions: R[]; onClose: () => void }) {
  const roster = useGet<R[]>(`${A}/offerings/${offeringId}/roster`)
  const [day, setDay] = useState(todayISO())
  const [topic, setTopic] = useState('')
  const existing = sessions.find((lesson) => lesson.held_on === day)
  const [marks, setMarks] = useState<Record<string, string>>({})
  const statusFor = (id: string) => marks[id] ?? existing?.records[id] ?? 'present'
  const save = useAction(() => post(`${A}/offerings/${offeringId}/attendance`, {
    held_on: day, topic: topic || existing?.topic || '', records: (roster.data ?? []).map((row) => ({ student_id: row.student_id, status: statusFor(row.student_id) })),
  }), { invalidate: [`${A}/offerings/${offeringId}`, `${A}/risk`, `${A}/dashboard`], success: 'Attendance saved', onSuccess: onClose })
  return (
    <Modal open size="lg" title="Record lesson attendance" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="attendance-form" busy={save.isPending} disabled={!roster.data?.length}>Save attendance</Button></>}>
      <form id="attendance-form" className="stack" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <div className="form-grid">
          <Field label="Lesson date" hint={existing ? 'Editing the attendance already recorded for this date.' : undefined}><Input type="date" max={todayISO()} value={day} onChange={(event) => { setDay(event.target.value); setMarks({}) }} /></Field>
          <Field label="Topic"><Input value={topic} placeholder={existing?.topic || 'Lecture topic'} onChange={(event) => setTopic(event.target.value)} /></Field>
        </div>
        {roster.isLoading ? <Loading /> : (
          <div className="table-wrap"><table className="data"><thead><tr><th>Student</th><th>Status</th></tr></thead><tbody>
            {(roster.data ?? []).map((row) => (
              <tr key={row.student_id}><td><strong>{row.name}</strong><span className="sub">{row.student_no}</span></td><td>
                <div className="tabs" role="radiogroup" aria-label={`Attendance for ${row.name}`}>
                  {STATUSES.map(([value, short]) => (
                    <button key={value} type="button" role="radio" aria-checked={statusFor(row.student_id) === value} title={value}
                      className={statusFor(row.student_id) === value ? 'active' : ''} onClick={() => setMarks({ ...marks, [row.student_id]: value })}>{short}<span className="sr-only"> {value}</span></button>
                  ))}
                </div>
              </td></tr>
            ))}
          </tbody></table></div>
        )}
        <p className="small muted">P present · L late · A absent · E excused</p>
      </form>
    </Modal>
  )
}

/* ---------------- Examinations ---------------- */
export function Exams() {
  const { can, session } = useAuth()
  const staff = can('academic:write', 'academic:teach')
  const exams = useGet<R[]>(`${A}/exams`)
  const [scheduling, setScheduling] = useState(false)
  const remove = useAction((id: string) => del(`${A}/exams/${id}`), { invalidate: [`${A}/exams`, `${A}/dashboard`], success: 'Exam removed' })
  const days = useMemo(() => {
    const groups: Record<string, R[]> = {}
    for (const exam of exams.data ?? []) {
      const key = new Date(exam.starts_at).toLocaleDateString('en-CA', { timeZone: 'Africa/Douala' })
      ;(groups[key] ??= []).push(exam)
    }
    return Object.entries(groups)
  }, [exams.data])
  const upcoming = days.filter(([day]) => day >= todayISO())
  const past = days.filter(([day]) => day < todayISO())
  return (
    <div className="stack">
      <PageHeader title="Examination timetable" subtitle={staff ? 'Scheduling checks room bookings, invigilators and every enrolled student for overlapping sittings.' : 'Your upcoming examinations.'}
        actions={staff && <Button icon={CalendarPlus} onClick={() => setScheduling(true)}>Schedule exam</Button>} />
      {exams.error ? <ErrorState error={exams.error} /> : !exams.data ? <Panel><Loading /></Panel> : !upcoming.length ? <Panel><Empty title="No upcoming exams" /></Panel> : upcoming.map(([day, rows]) => (
        <Panel key={day} title={new Date(`${day}T00:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })} flush>
          <ul className="list">{rows.map((exam) => (
            <li key={exam.id}>
              <span className="mono" style={{ minWidth: 112 }}>{time(exam.starts_at)} – {time(exam.ends_at)}</span>
              <div className="grow"><div className="title">{exam.course_code} · {exam.title}</div><div className="meta">{exam.course_title} · {exam.room} · Invigilator {exam.invigilator_name}</div></div>
              {staff && (can('academic:write') || exam.invigilator_user_id === session!.user.id) &&
                <Button small variant="ghost" icon={Trash2} onClick={() => remove.mutate(exam.id)} aria-label={`Remove ${exam.title}`}>Remove</Button>}
            </li>
          ))}</ul>
        </Panel>
      ))}
      {past.length > 0 && <p className="small muted">{past.reduce((sum, [, rows]) => sum + rows.length, 0)} past exam(s) hidden.</p>}
      {scheduling && <ExamForm onClose={() => setScheduling(false)} />}
    </div>
  )
}

function ExamForm({ onClose }: { onClose: () => void }) {
  const { can, session } = useAuth()
  const admin = can('academic:write')
  const offerings = useGet<R[]>(`${A}/offerings${admin ? '' : '?mine=true'}`)
  const instructors = useInstructors()
  const form = useForm({ offering_id: '', title: 'Midterm exam', room: '', invigilator_user_id: admin ? '' : session!.user.id, day: '', start: '09:00', end: '11:00' })
  const invigilator = admin ? instructors.find((row) => row.id === form.values.invigilator_user_id)?.name ?? '' : session!.user.name
  const body = () => ({ offering_id: form.values.offering_id, title: form.values.title, room: form.values.room, invigilator_user_id: form.values.invigilator_user_id,
    invigilator_name: invigilator, starts_at: `${form.values.day}T${form.values.start}:00`, ends_at: `${form.values.day}T${form.values.end}:00` })
  const [check, setCheck] = useState<R | null>(null)
  const preview = useAction(() => post<R>(`${A}/exams/check`, body()), { onSuccess: setCheck })
  const save = useAction(() => post(`${A}/exams`, body()), { invalidate: [`${A}/exams`, `${A}/dashboard`], success: 'Exam scheduled', onSuccess: onClose, silent: true })
  const conflict = save.error instanceof ApiError ? save.error : null
  const conflicts: R[] = (conflict?.details as R[] | null) ?? check?.conflicts ?? []
  const ready = form.values.offering_id && form.values.room && form.values.day && form.values.invigilator_user_id
  const active = (offerings.data ?? []).filter((row) => row.results_status !== 'published')
  return (
    <Modal open size="lg" title="Schedule an examination" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="secondary" busy={preview.isPending} disabled={!ready} onClick={() => preview.mutate()}>Check conflicts</Button>
        <Button type="submit" form="exam-form" busy={save.isPending} disabled={!ready}>Schedule</Button></>}>
      <form id="exam-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); setCheck(null); save.mutate() }}>
        <Field label="Course offering" wide><Select {...form.bind('offering_id')} placeholder="Choose" options={active.map((row) => ({ value: row.id, label: `${row.course_code} · ${row.course_title} · ${row.term_name}` }))} /></Field>
        <Field label="Title"><Input {...form.bind('title')} /></Field>
        <Field label="Room"><Input {...form.bind('room')} placeholder="Hall A" /></Field>
        <Field label="Date"><Input type="date" min={todayISO()} {...form.bind('day')} /></Field>
        <Field label="Invigilator">{admin ? <Select {...form.bind('invigilator_user_id')} placeholder="Choose" options={instructors.map((row) => ({ value: row.id, label: row.name }))} /> : <Input value={session!.user.name} disabled />}</Field>
        <Field label="Starts (WAT)"><Input type="time" {...form.bind('start')} /></Field>
        <Field label="Ends (WAT)"><Input type="time" {...form.bind('end')} /></Field>
      </form>
      {conflicts.length > 0 ? (
        <div className="error-box" role="alert"><CircleAlert size={18} aria-hidden /><div><strong>{conflicts.length} conflict(s) found</strong>
          <ul>{conflicts.map((item) => <li key={item.exam_id}>{item.course} {item.title} ({time(item.starts_at)}–{time(item.ends_at)}, {item.room}): {item.reasons.join('; ')}</li>)}</ul></div></div>
      ) : check?.ok ? <div className="callout teal"><CircleCheck size={18} aria-hidden /><span>No conflicts: room, invigilator and all enrolled students are free.</span></div>
        : conflict ? <div className="error-box" role="alert"><CircleAlert size={18} aria-hidden /><span>{conflict.message}</span></div> : null}
    </Modal>
  )
}
