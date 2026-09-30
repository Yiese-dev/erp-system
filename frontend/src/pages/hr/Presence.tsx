import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import jsQR from 'jsqr'
import { Camera, CameraOff, CircleCheck, Clock3, KeyRound, LogIn, LogOut, MonitorSmartphone, Package, Plus, QrCode, Square, Star } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, ErrorState, Field, Input, Kpis, Loading, Modal, PageHeader, Panel, Select, Stars, Textarea } from '../../components/ui'
import { ApiError, fieldErrors, post } from '../../lib/api'
import { date, label, money, monthLabel, time, todayISO } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'

const H = '/api/v1/hr'

/* ---------------- Kiosk (HR) ---------------- */
export function Kiosk() {
  const [kiosk, setKiosk] = useState('Main entrance')
  const [active, setActive] = useState(false)
  const [challenge, setChallenge] = useState<R | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [day, setDay] = useState(todayISO())
  const issue = useAction(() => post<R>(`${H}/attendance/challenges`, { kiosk }), { onSuccess: setChallenge })
  const board = useGet<R>(`${H}/attendance?day=${day}`, active ? 10_000 : false)
  const remaining = challenge ? Math.max(0, Math.round((new Date(challenge.expires_at).getTime() - now) / 1000)) : 0
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [active])
  useEffect(() => {
    if (active && !issue.isPending && (!challenge || remaining <= 5)) issue.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, remaining])
  const data = board.data
  return (
    <div className="stack">
      <PageHeader title="Attendance kiosk" subtitle="Display this screen on a tablet at the entrance. Staff scan the rotating QR code with their phone (Check in / out) to record arrival and departure." />
      <Panel title="Kiosk display" actions={active
        ? <Button variant="secondary" icon={Square} onClick={() => { setActive(false); setChallenge(null) }}>Stop kiosk</Button>
        : <><Input aria-label="Kiosk location" value={kiosk} onChange={(event) => setKiosk(event.target.value)} style={{ width: 200 }} /><Button icon={MonitorSmartphone} onClick={() => { setNow(Date.now()); setActive(true) }}>Start kiosk</Button></>}>
        {!active ? <Empty icon={QrCode} title="Kiosk is stopped" text="Start the kiosk to display a signed QR code that changes every 60 seconds." /> : !challenge ? <Loading /> : (
          <div className="kiosk">
            <div className="stack" style={{ alignItems: 'center', gap: 8 }}>
              <img src={challenge.qr} alt="Attendance QR code — scan with the Campus ERP check-in page" />
              <div className="countdown" aria-hidden><span style={{ width: `${(remaining / challenge.seconds) * 100}%` }} /></div>
            </div>
            <div className="stack" style={{ gap: 10 }}>
              <h2 style={{ fontSize: 22 }}>{challenge.kiosk}</h2>
              <p>Open <strong>Check in / out</strong> on your phone and scan this code.</p>
              <div><span className="small muted">No camera? Type this code:</span><div className="kiosk-code" aria-live="polite">{challenge.code}</div></div>
              <p className="small muted"><Clock3 size={13} aria-hidden /> Refreshes in {remaining}s. Codes are signed, expire after one minute and only work for this institution.</p>
            </div>
          </div>
        )}
      </Panel>
      <Panel title="Attendance board" actions={<Input type="date" aria-label="Day" max={todayISO()} value={day} onChange={(event) => setDay(event.target.value)} style={{ width: 170 }} />} flush>
        {data && <div style={{ padding: 14 }}><Kpis items={[
          { label: 'Present', value: String(data.present), tone: 'green' }, { label: 'On leave', value: String(data.on_leave), tone: 'blue' },
          { label: 'Absent', value: String(data.headcount - data.present - data.on_leave), tone: 'coral' }, { label: 'Headcount', value: String(data.headcount), tone: 'gray' },
        ]} /></div>}
        <DataTable rows={data?.rows} loading={board.isLoading} error={board.error} rowKey={(row) => row.employee_id} columns={[
          { key: 'name', header: 'Employee', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.department}</span></> },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
          { key: 'in', header: 'In', mono: true, render: (row) => time(row.check_in_at) },
          { key: 'out', header: 'Out', mono: true, render: (row) => time(row.check_out_at) },
          { key: 'method', header: 'Method', render: (row) => (row.method ? (row.method === 'qr' ? 'QR scan' : 'Typed code') : '—') },
        ]} />
      </Panel>
    </div>
  )
}

/* ---------------- Check-in (employee) ---------------- */
function Scanner({ onToken, disabled }: { onToken: (token: string) => void; disabled?: boolean }) {
  const video = useRef<HTMLVideoElement>(null)
  const stream = useRef<MediaStream | null>(null)
  const frame = useRef(0)
  const [state, setState] = useState<'idle' | 'starting' | 'scanning' | 'denied' | 'unsupported'>('idle')
  const stop = () => {
    cancelAnimationFrame(frame.current)
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
  }
  useEffect(() => stop, [])
  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia) { setState('unsupported'); return }
    setState('starting')
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      const element = video.current!
      element.srcObject = stream.current
      await element.play()
      setState('scanning')
      const canvas = document.createElement('canvas')
      const context = canvas.getContext('2d', { willReadFrequently: true })!
      const tick = () => {
        if (element.readyState === element.HAVE_ENOUGH_DATA && element.videoWidth) {
          canvas.width = element.videoWidth
          canvas.height = element.videoHeight
          context.drawImage(element, 0, 0, canvas.width, canvas.height)
          const image = context.getImageData(0, 0, canvas.width, canvas.height)
          const code = jsQR(image.data, image.width, image.height, { inversionAttempts: 'dontInvert' })
          if (code?.data.startsWith('CERP1.')) {
            stop()
            setState('idle')
            onToken(code.data)
            return
          }
        }
        frame.current = requestAnimationFrame(tick)
      }
      frame.current = requestAnimationFrame(tick)
    } catch (error) {
      stop()
      setState(error instanceof DOMException && error.name === 'NotAllowedError' ? 'denied' : 'unsupported')
    }
  }
  return (
    <div className="stack" style={{ alignItems: 'flex-start' }}>
      <div className="scanner" style={{ display: state === 'scanning' || state === 'starting' ? 'block' : 'none' }}>
        <video ref={video} muted playsInline aria-label="Camera preview" />
        <div className="frame" aria-hidden />
      </div>
      {state === 'scanning' || state === 'starting'
        ? <Button variant="secondary" icon={CameraOff} onClick={() => { stop(); setState('idle') }}>Stop camera</Button>
        : <Button icon={Camera} onClick={start} disabled={disabled}>Scan kiosk QR code</Button>}
      {state === 'denied' && <p className="callout small">Camera access was blocked. Allow the camera in your browser settings, or type the 6-character code shown under the QR instead.</p>}
      {state === 'unsupported' && <p className="callout small">This device or browser cannot open the camera here. Type the 6-character code shown on the kiosk instead.</p>}
    </div>
  )
}

export function CheckIn() {
  const profile = useGet<R>(`${H}/me`)
  const [code, setCode] = useState('')
  const [result, setResult] = useState<R | null>(null)
  const submit = useAction((body: R) => post<R>(`${H}/attendance/check-in`, body), { invalidate: [`${H}/me`], onSuccess: (value) => { setResult(value); setCode('') }, silent: true })
  const today = profile.data?.today
  const failure = submit.error instanceof ApiError ? submit.error : null
  if (profile.error) return <><PageHeader title="Check in / out" /><ErrorState error={profile.error} /></>
  return (
    <div className="stack">
      <PageHeader title="Check in / out" subtitle="Scan the QR code on the attendance kiosk. Your first scan of the day checks you in; the next one checks you out." />
      <div className="grid cols-2">
        <Panel title="Today">
          {!profile.data ? <Loading /> : (
            <div className={`status-hero ${today ? '' : 'warn'}`} style={{ padding: 0 }}>
              <span className="ring">{today ? <CircleCheck size={24} /> : <Clock3 size={24} />}</span>
              <div>
                <strong style={{ fontSize: 17 }}>{today ? (today.check_out_at ? 'Checked out' : 'Checked in') : 'Not checked in yet'}</strong>
                <div className="muted">{today ? `In ${time(today.check_in_at)}${today.check_out_at ? ` · Out ${time(today.check_out_at)}` : ''} · ${today.kiosk}` : 'Scan the kiosk when you arrive.'}</div>
              </div>
            </div>
          )}
          {result && <div className="callout teal" style={{ marginTop: 14 }}><CircleCheck size={18} aria-hidden /><span>{result.action === 'check_in' ? `Checked in at ${time(result.log.check_in_at)}` : `Checked out at ${time(result.log.check_out_at)}`}. Have a good {result.action === 'check_in' ? 'day' : 'evening'}!</span></div>}
          {failure && <div className="error-box" style={{ marginTop: 14 }} role="alert"><KeyRound size={18} aria-hidden /><span>{failure.message}</span></div>}
        </Panel>
        <Panel title="Scan or type the code">
          <div className="stack">
            <Scanner onToken={(token) => submit.mutate({ token })} disabled={submit.isPending || Boolean(today?.check_out_at)} />
            <form className="row" onSubmit={(event) => { event.preventDefault(); submit.mutate({ code }) }}>
              <Field label="Kiosk code"><Input value={code} onChange={(event) => setCode(event.target.value.toUpperCase().slice(0, 6))} placeholder="ABC123" autoComplete="off" style={{ fontFamily: 'var(--mono)', width: 140 }} /></Field>
              <Button type="submit" variant="secondary" icon={today && !today.check_out_at ? LogOut : LogIn} busy={submit.isPending} disabled={code.length !== 6} style={{ alignSelf: 'flex-end' }}>
                {today && !today.check_out_at ? 'Check out' : 'Check in'}
              </Button>
            </form>
          </div>
        </Panel>
      </div>
    </div>
  )
}

/* ---------------- My HR (self-service) ---------------- */
export function MyHr() {
  const profile = useGet<R>(`${H}/me`)
  const [requesting, setRequesting] = useState(false)
  const cancel = useAction((id: string) => post(`${H}/leave/${id}/cancel`), { invalidate: [`${H}/me`, `${H}/leave`], success: 'Leave request cancelled' })
  const data = profile.data
  if (profile.error) return <><PageHeader title="My HR" /><ErrorState error={profile.error} retry={() => profile.refetch()} /></>
  if (!data) return <Panel><Loading rows={6} /></Panel>
  const employee = data.employee
  return (
    <div className="stack">
      <PageHeader title="My HR" subtitle={`${employee.name} · ${employee.position} · ${employee.department} · ${employee.employee_no}`}
        actions={<><Link className="btn btn-secondary" to="/hr/check-in"><QrCode size={16} aria-hidden /><span>Check in / out</span></Link><Button icon={Plus} onClick={() => setRequesting(true)}>Request leave</Button></>} />
      <Kpis items={[
        { label: 'Today', value: data.today ? (data.today.check_out_at ? 'Checked out' : `In ${time(data.today.check_in_at)}`) : 'Not in', tone: data.today ? 'green' : 'amber' },
        ...data.balances.map((row: R) => ({ label: `${label(row.kind)} leave`, value: `${row.available} days`, hint: `${row.used} used of ${row.entitled}${row.pending ? ` · ${row.pending} pending` : ''}`, tone: 'blue' as const })),
      ]} />
      <div className="grid cols-2">
        <Panel title="My leave requests" flush>
          <DataTable rows={data.leave} rowKey={(row) => row.id} empty="No leave requests yet." columns={[
            { key: 'kind', header: 'Type', render: (row) => label(row.kind) },
            { key: 'dates', header: 'Dates', render: (row) => <>{date(row.starts_on)} → {date(row.ends_on)}<span className="sub">{row.days} working day(s)</span></> },
            { key: 'status', header: 'Status', render: (row) => <><Badge status={row.status} />{row.decision_note && <span className="sub">{row.decision_note}</span>}</> },
            { key: 'cancel', header: '', align: 'right', render: (row) => (row.status === 'pending' || (row.status === 'approved' && row.starts_on > todayISO())) && <Button small variant="ghost" onClick={() => cancel.mutate(row.id)}>Cancel</Button> },
          ]} />
        </Panel>
        <Panel title="My payslips" flush>
          <DataTable rows={data.payslips} rowKey={(row) => row.id} empty="No finalized payslips yet." columns={[
            { key: 'period', header: 'Month', render: (row) => monthLabel(row.period) },
            { key: 'gross', header: 'Gross', align: 'right', mono: true, render: (row) => money(row.gross) },
            { key: 'net', header: 'Net pay', align: 'right', mono: true, render: (row) => <strong>{money(row.net)}</strong> },
            { key: 'pdf', header: '', align: 'right', render: (row) => <DownloadButton path={`${H}/payslips/${row.id}.pdf`} filename={`payslip-${row.period}.pdf`} /> },
          ]} />
        </Panel>
      </div>
      <div className="grid cols-3">
        <Panel title="Attendance (30 days)" flush>
          <DataTable rows={data.attendance.slice(0, 10)} rowKey={(row) => row.id} empty="No check-ins recorded." columns={[
            { key: 'work_date', header: 'Date', render: (row) => date(row.work_date) }, { key: 'in', header: 'In', mono: true, render: (row) => time(row.check_in_at) },
            { key: 'out', header: 'Out', mono: true, render: (row) => time(row.check_out_at) },
          ]} />
        </Panel>
        <Panel title="Assigned equipment" flush>
          {data.assets.length ? <ul className="list">{data.assets.map((asset: R) => <li key={asset.id}><Package size={16} aria-hidden /><div className="grow"><div className="title">{asset.name}</div><div className="meta mono">{asset.tag}</div></div></li>)}</ul> : <Empty title="No equipment assigned" />}
        </Panel>
        <Panel title="Performance reviews" flush>
          {data.reviews.length ? <ul className="list">{data.reviews.map((review: R) => <li key={review.id}><Star size={16} aria-hidden /><div className="grow"><div className="title">{review.period}</div><div className="meta">{review.comments}</div></div><Stars rating={review.rating} /></li>)}</ul> : <Empty title="No completed reviews" />}
        </Panel>
      </div>
      {requesting && <LeaveForm balances={data.balances} onClose={() => setRequesting(false)} />}
    </div>
  )
}

function LeaveForm({ balances, onClose }: { balances: R[]; onClose: () => void }) {
  const form = useForm({ kind: 'annual', starts_on: '', ends_on: '', reason: '' })
  const save = useAction(() => post(`${H}/leave`, form.values), { invalidate: [`${H}/me`, `${H}/leave`], success: 'Leave requested · HR has been notified', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  const balance = balances.find((row) => row.kind === form.values.kind)
  return (
    <Modal open title="Request leave" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={!form.values.starts_on || !form.values.ends_on} onClick={() => save.mutate()}>Submit request</Button></>}>
      <div className="form-grid">
        <Field label="Leave type" wide hint={balance ? `${balance.available - balance.pending} day(s) available after pending requests` : undefined}>
          <Select {...form.bind('kind')} options={['annual', 'sick', 'compassionate'].map((value) => ({ value, label: label(value) }))} />
        </Field>
        <Field label="First day" error={errors.starts_on}><Input type="date" {...form.bind('starts_on')} /></Field>
        <Field label="Last day" error={errors.ends_on}><Input type="date" min={form.values.starts_on} {...form.bind('ends_on')} /></Field>
        <Field label="Reason (optional)" wide><Textarea {...form.bind('reason')} /></Field>
      </div>
      <p className="small muted">Weekends and fixed public holidays are not counted. Approval notifications are sent in-app and by email.</p>
    </Modal>
  )
}
