import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { BookPlus, CalendarPlus, CircleAlert, Link2, Plus, RefreshCw, UserPlus, Users, X } from 'lucide-react'
import { Badge, Button, DataTable, Empty, Field, Input, Modal, PageHeader, Pager, Panel, SearchBox, Select, Tabs } from '../../components/ui'
import { ApiError, fieldErrors, patch, post, qs, del } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, label } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { Page, R } from '../../lib/hooks'

const A = '/api/v1/academic'

export function useTerms() {
  const terms = useGet<R[]>(`${A}/terms`)
  const active = terms.data?.find((term) => term.status === 'active') ?? terms.data?.[0]
  return { terms, active }
}

export function useInstructors() {
  const { can } = useAuth()
  const users = useGet<R[]>(can('users:manage') ? '/api/v1/auth/users' : null)
  return (users.data ?? []).filter((user) => user.role === 'instructor' || user.role === 'admin')
}

/* ---------------- Programmes & courses ---------------- */
export function Catalogue() {
  const [tab, setTab] = useState<'courses' | 'programs'>('courses')
  const [program, setProgram] = useState('')
  const [editing, setEditing] = useState<R | null>(null)
  const [creating, setCreating] = useState<'course' | 'program' | null>(null)
  const programs = useGet<Page>(`${A}/programs?include_archived=true&size=100`)
  const courses = useGet<Page>(`${A}/courses${qs({ include_archived: true, size: 200, program_id: program })}`)
  const byId = useMemo(() => Object.fromEntries((courses.data?.items ?? []).map((course) => [course.id, course])), [courses.data])
  const toggleProgram = useAction((row: R) => patch(`${A}/programs/${row.id}`, { active: !row.active }), { invalidate: [`${A}/programs`], success: 'Programme updated' })
  const toggleCourse = useAction((row: R) => patch(`${A}/courses/${row.id}`, { active: !row.active }), { invalidate: [`${A}/courses`], success: 'Course updated' })
  const programOptions = (programs.data?.items ?? []).map((row) => ({ value: row.id, label: `${row.code} · ${row.name}` }))
  return (
    <div className="stack">
      <PageHeader title="Programmes & courses" subtitle="Maintain the academic catalogue. Referenced records are archived rather than deleted so transcripts stay intact."
        actions={<><Button variant="secondary" icon={Plus} onClick={() => setCreating('program')}>New programme</Button><Button icon={BookPlus} onClick={() => setCreating('course')}>New course</Button></>} />
      <Panel title={<Tabs value={tab} onChange={setTab} items={[{ value: 'courses', label: 'Courses', count: courses.data?.total }, { value: 'programs', label: 'Programmes', count: programs.data?.total }]} />}
        actions={tab === 'courses' && <Select aria-label="Filter by programme" value={program} onChange={(event) => setProgram(event.target.value)} options={programOptions} placeholder="All programmes" />} flush>
        {tab === 'courses' ? (
          <DataTable rows={courses.data?.items} loading={courses.isLoading} error={courses.error} rowKey={(row) => row.id} columns={[
            { key: 'code', header: 'Code', mono: true },
            { key: 'title', header: 'Title', render: (row) => <><strong>{row.title}</strong><span className="sub">{row.program_code}</span></> },
            { key: 'credits', header: 'Credits', align: 'right', mono: true },
            { key: 'prerequisites', header: 'Prerequisites', render: (row) => row.prerequisites.length ? <div className="chips">{row.prerequisites.map((id: string) => <span key={id} className="chip">{byId[id]?.code ?? '…'}</span>)}</div> : <span className="muted">None</span> },
            { key: 'active', header: 'Status', render: (row) => <Badge status={row.active ? 'active' : 'archived'} /> },
            { key: 'actions', header: '', align: 'right', render: (row) => <div className="row" style={{ justifyContent: 'flex-end' }}>
              <Button small variant="ghost" icon={Link2} onClick={() => setEditing(row)}>Prerequisites</Button>
              <Button small variant="secondary" onClick={() => toggleCourse.mutate(row)}>{row.active ? 'Archive' : 'Restore'}</Button></div> },
          ]} />
        ) : (
          <DataTable rows={programs.data?.items} loading={programs.isLoading} error={programs.error} rowKey={(row) => row.id} columns={[
            { key: 'code', header: 'Code', mono: true },
            { key: 'name', header: 'Programme', render: (row) => <strong>{row.name}</strong> },
            { key: 'level', header: 'Level' },
            { key: 'duration_terms', header: 'Terms', align: 'right', mono: true },
            { key: 'active', header: 'Status', render: (row) => <Badge status={row.active ? 'active' : 'archived'} /> },
            { key: 'actions', header: '', align: 'right', render: (row) => <Button small variant="secondary" onClick={() => toggleProgram.mutate(row)}>{row.active ? 'Archive' : 'Restore'}</Button> },
          ]} />
        )}
      </Panel>
      <ProgramForm open={creating === 'program'} onClose={() => setCreating(null)} />
      <CourseForm open={creating === 'course'} onClose={() => setCreating(null)} programs={programOptions} />
      <PrerequisiteEditor course={editing} courses={courses.data?.items ?? []} onClose={() => setEditing(null)} />
    </div>
  )
}

function ProgramForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const form = useForm({ code: '', name: '', level: 'Bachelor', duration_terms: '6' })
  const save = useAction(() => post(`${A}/programs`, { ...form.values, duration_terms: Number(form.values.duration_terms) }),
    { invalidate: [`${A}/programs`], success: 'Programme created', onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="New programme" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="program-form" busy={save.isPending}>Create programme</Button></>}>
      <form id="program-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Code" error={errors.code}><Input {...form.bind('code')} required placeholder="BSE" /></Field>
        <Field label="Level"><Select {...form.bind('level')} options={['Certificate', 'Diploma', 'Bachelor', 'Master'].map((value) => ({ value, label: value }))} /></Field>
        <Field label="Programme name" wide error={errors.name}><Input {...form.bind('name')} required /></Field>
        <Field label="Duration (terms)" error={errors.duration_terms}><Input type="number" min={1} max={16} {...form.bind('duration_terms')} /></Field>
      </form>
    </Modal>
  )
}

function CourseForm({ open, onClose, programs }: { open: boolean; onClose: () => void; programs: { value: string; label: string }[] }) {
  const form = useForm({ program_id: '', code: '', title: '', credits: '3' })
  const save = useAction(() => post(`${A}/courses`, { ...form.values, credits: Number(form.values.credits) }),
    { invalidate: [`${A}/courses`], success: 'Course created', onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="New course" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="course-form" busy={save.isPending}>Create course</Button></>}>
      <form id="course-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Programme" wide error={errors.program_id}><Select {...form.bind('program_id')} options={programs} placeholder="Choose a programme" required /></Field>
        <Field label="Course code" error={errors.code}><Input {...form.bind('code')} placeholder="SEN305" required /></Field>
        <Field label="Credits" error={errors.credits}><Input type="number" min={1} max={12} {...form.bind('credits')} /></Field>
        <Field label="Title" wide error={errors.title}><Input {...form.bind('title')} required /></Field>
      </form>
    </Modal>
  )
}

function PrerequisiteEditor({ course, courses, onClose }: { course: R | null; courses: R[]; onClose: () => void }) {
  const [choice, setChoice] = useState('')
  const current = courses.find((row) => row.id === course?.id) ?? course
  const add = useAction(() => post(`${A}/courses/${current!.id}/prerequisites`, { prerequisite_id: choice }), { invalidate: [`${A}/courses`], success: 'Prerequisite added', onSuccess: () => setChoice('') })
  const remove = useAction((id: string) => del(`${A}/courses/${current!.id}/prerequisites/${id}`), { invalidate: [`${A}/courses`], success: 'Prerequisite removed' })
  if (!current) return null
  const options = courses.filter((row) => row.id !== current.id && !current.prerequisites.includes(row.id)).map((row) => ({ value: row.id, label: `${row.code} · ${row.title}` }))
  return (
    <Modal open title={`Prerequisites for ${current.code}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Done</Button>}>
      <p className="muted">Students must have a published pass in every prerequisite before they can enrol. Circular chains are rejected.</p>
      <div className="chips">
        {current.prerequisites.length ? current.prerequisites.map((id: string) => {
          const prerequisite = courses.find((row) => row.id === id)
          return <span key={id} className="chip">{prerequisite?.code ?? id}<button type="button" aria-label={`Remove ${prerequisite?.code}`} onClick={() => remove.mutate(id)}><X size={13} /></button></span>
        }) : <span className="muted">No prerequisites.</span>}
      </div>
      <form className="row" onSubmit={(event) => { event.preventDefault(); if (choice) add.mutate() }}>
        <div style={{ flex: 1, minWidth: 220 }}><Select aria-label="Add prerequisite" value={choice} onChange={(event) => setChoice(event.target.value)} options={options} placeholder="Choose a course" /></div>
        <Button type="submit" icon={Plus} busy={add.isPending} disabled={!choice}>Add</Button>
      </form>
    </Modal>
  )
}

/* ---------------- Offerings ---------------- */
export function Offerings() {
  const { can } = useAuth()
  const { terms, active } = useTerms()
  const [termId, setTermId] = useState('')
  const term = termId || active?.id || ''
  const offerings = useGet<R[]>(term ? `${A}/offerings${qs({ term_id: term })}` : null)
  const [roster, setRoster] = useState<R | null>(null)
  const [creating, setCreating] = useState<'offering' | 'term' | null>(null)
  const current = terms.data?.find((row) => row.id === term)
  const setStatus = useAction((status: string) => patch(`${A}/terms/${term}`, { status }), { invalidate: [`${A}/terms`], success: 'Term updated' })
  const admin = can('academic:write')
  return (
    <div className="stack">
      <PageHeader title="Course offerings" subtitle={admin ? 'Schedule courses into terms, assign instructors and rooms.' : 'Courses you teach in each term.'}
        actions={admin && <><Button variant="secondary" icon={CalendarPlus} onClick={() => setCreating('term')}>New term</Button><Button icon={Plus} onClick={() => setCreating('offering')} disabled={!term}>New offering</Button></>} />
      <Panel title={<Tabs value={term} onChange={setTermId} items={(terms.data ?? []).map((row) => ({ value: row.id, label: row.name }))} label="Term" />}
        actions={current && <><Badge status={current.status} /><span className="small muted">{date(current.starts_on)} – {date(current.ends_on)}</span>
          {admin && current.status !== 'closed' && <Button small variant="secondary" onClick={() => setStatus.mutate('closed')}>Close registration</Button>}
          {admin && current.status === 'closed' && <Button small variant="secondary" onClick={() => setStatus.mutate('active')}>Reopen</Button>}</>} flush>
        <DataTable rows={offerings.data} loading={offerings.isLoading || terms.isLoading} error={offerings.error} rowKey={(row) => row.id} onRowClick={setRoster}
          empty="No courses have been scheduled in this term." columns={[
            { key: 'course', header: 'Course', render: (row) => <><strong>{row.course_code}</strong><span className="sub">{row.course_title}</span></> },
            { key: 'instructor_name', header: 'Instructor' },
            { key: 'room', header: 'Room' },
            { key: 'seats', header: 'Seats', align: 'right', render: (row) => <span className="mono">{row.enrolled} / {row.capacity}</span> },
            { key: 'results_status', header: 'Results', render: (row) => <Badge status={row.results_status} /> },
            { key: 'roster', header: '', align: 'right', render: () => <Button small variant="ghost" icon={Users}>Roster</Button> },
          ]} />
      </Panel>
      {roster && <RosterModal offering={roster} onClose={() => setRoster(null)} />}
      <OfferingForm open={creating === 'offering'} termId={term} onClose={() => setCreating(null)} />
      <TermForm open={creating === 'term'} onClose={() => setCreating(null)} />
    </div>
  )
}

function RosterModal({ offering, onClose }: { offering: R; onClose: () => void }) {
  const roster = useGet<R[]>(`${A}/offerings/${offering.id}/roster`)
  return (
    <Modal open size="lg" title={`${offering.course_code} roster · ${offering.term_name}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <DataTable rows={roster.data} loading={roster.isLoading} error={roster.error} rowKey={(row) => row.student_id} empty="No students enrolled yet." columns={[
        { key: 'student_no', header: 'Student no.', mono: true }, { key: 'name', header: 'Name' }, { key: 'email', header: 'Email' },
      ]} />
    </Modal>
  )
}

function OfferingForm({ open, termId, onClose }: { open: boolean; termId: string; onClose: () => void }) {
  const courses = useGet<Page>(`${A}/courses?size=200`)
  const instructors = useInstructors()
  const form = useForm({ course_id: '', instructor_user_id: '', room: '', capacity: '40' })
  const instructor = instructors.find((row) => row.id === form.values.instructor_user_id)
  const save = useAction(() => post(`${A}/offerings`, { ...form.values, term_id: termId, capacity: Number(form.values.capacity), instructor_name: instructor?.name ?? '' }),
    { invalidate: [`${A}/offerings`], success: 'Offering scheduled', onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="Schedule a course offering" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="offering-form" busy={save.isPending}>Schedule</Button></>}>
      <form id="offering-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Course" wide error={errors.course_id}><Select {...form.bind('course_id')} placeholder="Choose a course" options={(courses.data?.items ?? []).map((row) => ({ value: row.id, label: `${row.code} · ${row.title}` }))} /></Field>
        <Field label="Instructor" wide error={errors.instructor_user_id || errors.instructor_name}><Select {...form.bind('instructor_user_id')} placeholder="Choose an instructor" options={instructors.map((row) => ({ value: row.id, label: row.name }))} /></Field>
        <Field label="Room" error={errors.room}><Input {...form.bind('room')} placeholder="Hall A" /></Field>
        <Field label="Capacity" error={errors.capacity}><Input type="number" min={1} max={500} {...form.bind('capacity')} /></Field>
      </form>
    </Modal>
  )
}

function TermForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const form = useForm({ name: '', starts_on: '', ends_on: '', status: 'planned' })
  const save = useAction(() => post(`${A}/terms`, form.values), { invalidate: [`${A}/terms`], success: 'Term created', onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="New academic term" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="term-form" busy={save.isPending}>Create term</Button></>}>
      <form id="term-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} placeholder="2027 Spring" /></Field>
        <Field label="Starts" error={errors.starts_on}><Input type="date" {...form.bind('starts_on')} /></Field>
        <Field label="Ends" error={errors.ends_on}><Input type="date" {...form.bind('ends_on')} /></Field>
        <Field label="Status"><Select {...form.bind('status')} options={['planned', 'active'].map((value) => ({ value, label: label(value) }))} /></Field>
      </form>
    </Modal>
  )
}

/* ---------------- Students & registration ---------------- */
export function Students() {
  const [tab, setTab] = useState<'students' | 'registrations'>('students')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [registering, setRegistering] = useState<R | null>(null)
  const [creating, setCreating] = useState(false)
  const { terms, active } = useTerms()
  const [termId, setTermId] = useState('')
  const term = termId || active?.id || ''
  const students = useGet<Page>(`${A}/students${qs({ q, page, size: 20 })}`)
  const registrations = useGet<Page>(tab === 'registrations' && term ? `${A}/registrations${qs({ term_id: term, size: 50 })}` : null, 5000)
  return (
    <div className="stack">
      <PageHeader title="Students & registration" subtitle="Registering a student for a term confirms their courses and publishes an enrolment event; Finance issues the tuition invoice asynchronously."
        actions={<Button icon={UserPlus} onClick={() => setCreating(true)}>New student</Button>} />
      <Panel title={<Tabs value={tab} onChange={setTab} items={[{ value: 'students', label: 'Students', count: students.data?.total }, { value: 'registrations', label: 'Term registrations' }]} />}
        actions={tab === 'students' ? <SearchBox value={q} onChange={(value) => { setQ(value); setPage(1) }} placeholder="Search name, number or email" />
          : <Select aria-label="Term" value={term} onChange={(event) => setTermId(event.target.value)} options={(terms.data ?? []).map((row) => ({ value: row.id, label: row.name }))} />} flush
        note={tab === 'registrations' && <span><RefreshCw size={13} aria-hidden /> Billing status refreshes every 5 seconds: <b>pending</b> → <b>invoiced</b> once Finance consumes the RabbitMQ event → <b>paid</b> after settlement.</span>}>
        {tab === 'students' ? (
          <>
            <DataTable rows={students.data?.items} loading={students.isLoading} error={students.error} rowKey={(row) => row.id} columns={[
              { key: 'student_no', header: 'Student no.', mono: true },
              { key: 'name', header: 'Name', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.email}</span></> },
              { key: 'program_code', header: 'Programme', render: (row) => <span title={row.program_name}>{row.program_code}</span> },
              { key: 'user_id', header: 'Portal login', render: (row) => row.user_id ? <Badge status="active">Linked</Badge> : <span className="muted">None</span> },
              { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
              { key: 'actions', header: '', align: 'right', render: (row) => <Button small variant="secondary" onClick={() => setRegistering(row)}>Register for term</Button> },
            ]} />
            {students.data && <Pager page={page} size={20} total={students.data.total} onPage={setPage} />}
          </>
        ) : (
          <DataTable rows={registrations.data?.items} loading={registrations.isLoading} error={registrations.error} rowKey={(row) => row.id} empty="No registrations for this term." columns={[
            { key: 'student', header: 'Student', render: (row) => <><strong>{row.student_name}</strong><span className="sub">{row.student_no}</span></> },
            { key: 'courses', header: 'Courses', render: (row) => <div className="chips">{row.courses.map((code: string) => <span className="chip" key={code}>{code}</span>)}</div> },
            { key: 'created_at', header: 'Registered', render: (row) => date(row.created_at) },
            { key: 'billing_status', header: 'Billing', render: (row) => <Badge status={row.billing_status} /> },
            { key: 'invoice_number', header: 'Invoice', mono: true, render: (row) => row.invoice_number ?? '—' },
          ]} />
        )}
      </Panel>
      <StudentForm open={creating} onClose={() => setCreating(false)} />
      {registering && <RegisterModal student={registering} onClose={() => setRegistering(null)} onDone={() => { setRegistering(null); setTab('registrations') }} />}
    </div>
  )
}

function StudentForm({ open, onClose }: { open: boolean; onClose: () => void }) {
  const programs = useGet<Page>(`${A}/programs?size=100`)
  const accounts = useGet<R[]>(open ? '/api/v1/auth/users' : null)
  const form = useForm({ name: '', email: '', program_id: '', user_id: '' })
  const save = useAction(() => post(`${A}/students`, { ...form.values, user_id: form.values.user_id || null }),
    { invalidate: [`${A}/students`], success: (row: R) => `Student ${row.student_no} created`, onSuccess: () => { form.reset(); onClose() } })
  const errors = fieldErrors(save.error)
  return (
    <Modal open={open} title="New student" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="student-form" busy={save.isPending}>Create student</Button></>}>
      <form id="student-form" className="form-grid" onSubmit={(event) => { event.preventDefault(); save.mutate() }}>
        <Field label="Full name" wide error={errors.name}><Input {...form.bind('name')} required /></Field>
        <Field label="Email" error={errors.email}><Input type="email" {...form.bind('email')} required /></Field>
        <Field label="Programme" error={errors.program_id}><Select {...form.bind('program_id')} placeholder="Choose" options={(programs.data?.items ?? []).map((row) => ({ value: row.id, label: row.code }))} /></Field>
        <Field label="Portal login (optional)" wide hint="Link an existing student account from Users & roles so they can see results and pay fees.">
          <Select {...form.bind('user_id')} placeholder="No portal access" options={(accounts.data ?? []).filter((row) => row.role === 'student').map((row) => ({ value: row.id, label: `${row.name} · ${row.email}` }))} />
        </Field>
      </form>
    </Modal>
  )
}

function RegisterModal({ student, onClose, onDone }: { student: R; onClose: () => void; onDone: () => void }) {
  const { terms, active } = useTerms()
  const [termId, setTermId] = useState('')
  const term = termId || active?.id || ''
  const offerings = useGet<R[]>(term ? `${A}/offerings${qs({ term_id: term })}` : null)
  const [picked, setPicked] = useState<string[]>([])
  const save = useAction(() => post(`${A}/registrations`, { student_id: student.id, term_id: term, offering_ids: picked }),
    { invalidate: [`${A}/registrations`, `${A}/offerings`, `${A}/dashboard`], success: 'Registration confirmed · billing event published', onSuccess: onDone, silent: true })
  const problem = save.error instanceof ApiError ? save.error : null
  const submit = (event: FormEvent) => { event.preventDefault(); save.mutate() }
  return (
    <Modal open title={`Register ${student.name}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="register-form" busy={save.isPending} disabled={!picked.length}>Confirm registration</Button></>}>
      <form id="register-form" className="stack" onSubmit={submit}>
        <Field label="Term"><Select value={term} onChange={(event) => { setTermId(event.target.value); setPicked([]) }} options={(terms.data ?? []).filter((row) => row.status !== 'closed').map((row) => ({ value: row.id, label: row.name }))} /></Field>
        <div className="field">
          <span className="field-label">Courses</span>
          {offerings.data?.length ? (
            <div className="check-list">
              {offerings.data.map((row) => (
                <label key={row.id} className="checkbox">
                  <input type="checkbox" checked={picked.includes(row.id)} disabled={row.enrolled >= row.capacity}
                    onChange={(event) => setPicked(event.target.checked ? [...picked, row.id] : picked.filter((id) => id !== row.id))} />
                  <span><strong>{row.course_code}</strong> {row.course_title}<span className="sub muted small"> · {row.instructor_name} · {row.enrolled}/{row.capacity} seats</span></span>
                </label>
              ))}
            </div>
          ) : <Empty text="No offerings in this term." />}
        </div>
        {problem && (
          <div className="error-box" role="alert"><CircleAlert size={18} aria-hidden /><div>{problem.message}
            {Array.isArray(problem.details) && <ul>{(problem.details as R[]).map((item) => <li key={item.course}>{item.course}: requires {item.missing.join(', ')}</li>)}</ul>}</div></div>
        )}
      </form>
    </Modal>
  )
}
