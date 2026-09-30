import { useState } from 'react'
import type { FormEvent } from 'react'
import { GraduationCap, Info, TriangleAlert, Users, Wallet } from 'lucide-react'
import { BrandMark } from '../components/Brand'
import { Button, Field, Input } from '../components/ui'
import { messageOf } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ROLE_LABELS } from '../lib/format'

const DEMO = [
  ['admin@campus.test', 'admin'], ['instructor@campus.test', 'instructor'], ['student@campus.test', 'student'],
  ['finance@campus.test', 'finance'], ['hr@campus.test', 'hr'], ['employee@campus.test', 'employee'], ['superadmin@campus.test', 'super_admin'],
]
const DEMO_PASSWORD = 'CampusDemo!2026'

export default function Login() {
  const { login, notice } = useAuth()
  const [tenant, setTenant] = useState('ictu')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(tenant.trim(), email.trim(), password)
    } catch (failure) {
      setError(messageOf(failure))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <section className="login-brand">
        <div className="row" style={{ gap: 12 }}>
          <BrandMark className="brand-mark" />
          <strong style={{ color: '#fff', fontSize: 18 }}>Campus ERP</strong>
        </div>
        <h1>Run the whole institution from one place.</h1>
        <p className="lead">Academic records, tuition and marketing, payroll and people — each institution fully isolated, every action permission-checked.</p>
        <ul className="login-modules">
          <li><GraduationCap size={20} aria-hidden /><span><strong>Academic</strong><br />Programmes, prerequisites, gradebooks, exam timetabling, appeals and transcripts.</span></li>
          <li><Wallet size={20} aria-hidden /><span><strong>Marketing & finance</strong><br />Invoicing on enrolment, MTN MoMo and Orange Money payments, receipts and campaign ROI.</span></li>
          <li><Users size={20} aria-hidden /><span><strong>Administration & HR</strong><br />CNPS and IRPP payroll, QR attendance, leave approvals, reviews and assets.</span></li>
        </ul>
        <p className="login-foot">Amounts in FCFA · Times shown in Africa/Douala (WAT)</p>
      </section>
      <section className="login-panel">
        <form className="login-form" onSubmit={submit} noValidate>
          <div>
            <h2>Sign in</h2>
            <p className="muted">Enter your institution code and work email.</p>
          </div>
          {notice && <div className="notice"><Info size={18} aria-hidden /><span>{notice}</span></div>}
          {error && <div className="error-box" role="alert"><TriangleAlert size={18} aria-hidden /><span>{error}</span></div>}
          <Field label="Institution code">
            <Input value={tenant} onChange={(event) => setTenant(event.target.value)} autoComplete="organization" required />
          </Field>
          <Field label="Email">
            <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required autoFocus />
          </Field>
          <Field label="Password">
            <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
          </Field>
          <Button type="submit" busy={busy} className="btn-block" disabled={!tenant || !email || !password}>Sign in</Button>
          <p className="small muted">Accounts lock for 15 minutes after five failed attempts.</p>
        </form>
        {import.meta.env.DEV && <div className="demo-accounts">
          <h3>Demonstration accounts · institutions <code>ictu</code> and <code>atlantic</code></h3>
          <div className="demo-grid">
            {DEMO.map(([address, role]) => (
              <button key={address} type="button" onClick={() => { setEmail(address); setPassword(DEMO_PASSWORD); if (role === 'super_admin') setTenant('ictu') }}>
                <strong>{ROLE_LABELS[role]}</strong>
                <span>{address}</span>
              </button>
            ))}
          </div>
          <p className="small muted" style={{ marginTop: 6 }}>Synthetic data only. Password for every demo account: <code>{DEMO_PASSWORD}</code></p>
        </div>}
      </section>
    </div>
  )
}
