import { Fragment, useState } from 'react'
import { BadgeCheck, Calculator, CircleAlert, ExternalLink, Lock, Play, ShieldCheck, Trash2 } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, Field, Input, Kpis, Loading, Modal, PageHeader, Panel, Textarea } from '../../components/ui'
import { del, post } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, dateTime, money, monthLabel, previousMonth } from '../../lib/format'
import { useAction, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'

const H = '/api/v1/hr'
const pct = (value: string | number) => `${(Number(value) * 100).toFixed(Number(value) * 100 % 1 ? 2 : 0)}%`

export function Payroll() {
  const { can } = useAuth()
  const rules = useGet<R[]>(`${H}/payroll/rule-sets`)
  const runs = useGet<R[]>(`${H}/payroll/runs`)
  const [period, setPeriod] = useState(previousMonth())
  const [approving, setApproving] = useState<R | null>(null)
  const [openRun, setOpenRun] = useState<string | null>(null)
  const approved = rules.data?.find((row) => row.status === 'approved')
  const create = useAction(() => post<R>(`${H}/payroll/runs`, { period }), { invalidate: [`${H}/payroll`, `${H}/dashboard`], success: 'Draft payroll calculated', onSuccess: (row) => setOpenRun(row.id) })
  const writer = can('hr:write')
  return (
    <div className="stack">
      <PageHeader title="Payroll" subtitle="Monthly payroll with Cameroonian statutory deductions: CNPS pension (employee and employer), IRPP/PAYE progressive scale and CAC, with employer contributions shown separately." />
      {rules.data && !approved && (
        <div className="callout"><CircleAlert size={18} aria-hidden /><span><strong>Payroll is blocked.</strong> The statutory rule set is a draft. An HR officer must check each rate against the official DGI and CNPS publications listed below, then approve it. Approvals are recorded with the verifier's note.</span></div>
      )}
      <Panel title="Statutory rule sets" subtitle="Rates are data, not code: effective-dated, source-referenced and immutable once approved." flush>
        {!rules.data ? <Loading /> : rules.data.map((set) => <RuleSetView key={set.id} set={set} onApprove={writer && set.status === 'draft' ? () => setApproving(set) : undefined} />)}
      </Panel>
      <div className="grid cols-main">
        <Panel title="Payroll runs" flush actions={writer && (
          <form className="row" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
            <Input type="month" aria-label="Payroll month" max={previousMonth().slice(0, 4) + '-12'} value={period} onChange={(event) => setPeriod(event.target.value)} style={{ width: 170 }} />
            <Button type="submit" icon={Play} busy={create.isPending} disabled={!approved}>Run payroll</Button>
          </form>)}>
          <DataTable rows={runs.data} loading={runs.isLoading} rowKey={(row) => row.id} onRowClick={(row) => setOpenRun(row.id)} empty="No payroll has been run yet." columns={[
            { key: 'period', header: 'Month', render: (row) => <strong>{monthLabel(row.period)}</strong> },
            { key: 'headcount', header: 'Staff', align: 'right', mono: true, render: (row) => row.totals.headcount },
            { key: 'gross', header: 'Gross', align: 'right', mono: true, render: (row) => money(row.totals.gross) },
            { key: 'net', header: 'Net', align: 'right', mono: true, render: (row) => money(row.totals.net) },
            { key: 'employer_cost', header: 'Employer cost', align: 'right', mono: true, render: (row) => money(row.totals.employer_cost) },
            { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
          ]} />
        </Panel>
        <PayCalculator />
      </div>
      {approving && <ApproveRules set={approving} onClose={() => setApproving(null)} />}
      {openRun && <RunDetail id={openRun} onClose={() => setOpenRun(null)} />}
    </div>
  )
}

function RuleSetView({ set, onApprove }: { set: R; onApprove?: () => void }) {
  const { cnps, irpp } = set.rules
  return (
    <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line-soft)' }}>
      <div className="row between">
        <div><strong>{set.name}</strong> <Badge status={set.status} /><div className="small muted">Effective {date(set.effective_from)}{set.approved_at && ` · approved ${dateTime(set.approved_at)}`}</div></div>
        {onApprove && <Button icon={ShieldCheck} onClick={onApprove}>Verify & approve</Button>}
      </div>
      <div className="grid cols-3" style={{ marginTop: 12 }}>
        <dl className="kv small">
          <dt>CNPS pension (employee)</dt><dd>{pct(cnps.employee_rate)}</dd>
          <dt>CNPS pension (employer)</dt><dd>{pct(cnps.employer_pension_rate)}</dd>
          <dt>Family allowances</dt><dd>{pct(cnps.family_allowance_rate)}</dd>
          <dt>Work injury</dt><dd>{pct(cnps.work_injury_rate)}</dd>
          <dt>Contribution ceiling</dt><dd>{money(cnps.ceiling)} / month</dd>
        </dl>
        <dl className="kv small">
          <dt>Professional allowance</dt><dd>{pct(irpp.professional_expense_rate)} of gross</dd>
          <dt>Annual abatement</dt><dd>{money(irpp.annual_abatement)}</dd>
          <dt>Exempt below</dt><dd>{money(irpp.exempt_monthly_gross)} gross / month</dd>
          <dt>CAC</dt><dd>{pct(irpp.cac_rate)} of IRPP</dd>
          {(set.rules.employee_other ?? []).map((item: R) => <Fragment key={item.code}><dt>{item.label}</dt><dd>{pct(item.rate)}</dd></Fragment>)}
        </dl>
        <div>
          <table className="data"><thead><tr><th>Annual taxable income</th><th style={{ textAlign: 'right' }}>IRPP rate</th></tr></thead><tbody>
            {irpp.brackets.map(([upper, rate]: [number | null, string], index: number) => {
              const lower = index ? irpp.brackets[index - 1][0] : 0
              return <tr key={String(upper)}><td className="mono">{upper == null ? `above ${money(lower)}` : `${money(lower)} – ${money(upper)}`}</td><td className="mono" style={{ textAlign: 'right' }}>{pct(rate)}</td></tr>
            })}
          </tbody></table>
        </div>
      </div>
      <div className="small" style={{ marginTop: 10 }}>
        <strong>Sources to verify:</strong>
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{set.sources.map((source: R) => <li key={source.title}>{source.title} <a href={source.url} target="_blank" rel="noreferrer noopener"><ExternalLink size={12} aria-label="open source" /></a></li>)}</ul>
        {set.approval_note && <p style={{ marginTop: 6 }}><BadgeCheck size={14} aria-hidden /> Verification note: {set.approval_note}</p>}
      </div>
    </div>
  )
}

function ApproveRules({ set, onClose }: { set: R; onClose: () => void }) {
  const [note, setNote] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const approve = useAction(() => post(`${H}/payroll/rule-sets/${set.id}/approve`, { note }), { invalidate: [`${H}/payroll`, `${H}/dashboard`], success: 'Rule set approved · payroll unlocked', onSuccess: onClose })
  return (
    <Modal open title="Verify and approve statutory rates" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button icon={ShieldCheck} busy={approve.isPending} disabled={!confirmed || note.trim().length < 15} onClick={() => approve.mutate()}>Approve rule set</Button></>}>
      <p>Approval makes <strong>{set.name}</strong> the basis for every payroll from {date(set.effective_from)}. Rule sets cannot be edited after approval; publish a new effective-dated set when the law changes.</p>
      <Field label="Verification note" hint="Which official document, article and table did you check the rates against? (at least 15 characters)">
        <Textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Checked against CGI 2026 Art. 69 IRPP scale and the CNPS 2026 contribution notice." />
      </Field>
      <label className="checkbox"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I confirm these rates match the official published sources for this period.</label>
    </Modal>
  )
}

function PayCalculator() {
  const [base, setBase] = useState('500000')
  const [allowances, setAllowances] = useState('0')
  const [result, setResult] = useState<R | null>(null)
  const preview = useAction(() => post<R>(`${H}/payroll/preview`, { base_salary: Number(base), allowances: Number(allowances || 0) }), { onSuccess: setResult })
  return (
    <Panel title="Payslip calculator" subtitle="Preview deductions for any salary with the current rule set.">
      <form className="form-grid" onSubmit={(event) => { event.preventDefault(); preview.mutate() }}>
        <Field label="Base salary"><Input type="number" min={1} value={base} onChange={(event) => setBase(event.target.value)} /></Field>
        <Field label="Allowances"><Input type="number" min={0} value={allowances} onChange={(event) => setAllowances(event.target.value)} /></Field>
        <div className="field-wide"><Button type="submit" variant="secondary" icon={Calculator} busy={preview.isPending} disabled={!base}>Calculate</Button></div>
      </form>
      {result && (
        <div style={{ marginTop: 12 }}>
          {result.rule_set.status !== 'approved' && <p className="small callout" style={{ marginBottom: 8 }}>Using the unapproved draft rule set.</p>}
          <table className="data"><tbody>
            <tr><td>Gross pay</td><td className="mono" style={{ textAlign: 'right' }}>{money(result.gross)}</td></tr>
            {result.employee.map((line: R) => <tr key={line.code}><td>− {line.label}</td><td className="mono" style={{ textAlign: 'right' }}>{money(line.amount)}</td></tr>)}
            <tr><td><strong>Net pay</strong></td><td className="mono" style={{ textAlign: 'right' }}><strong>{money(result.net)}</strong></td></tr>
            <tr><td className="muted">Employer contributions</td><td className="mono muted" style={{ textAlign: 'right' }}>{money(result.employer_total)}</td></tr>
          </tbody></table>
        </div>
      )}
    </Panel>
  )
}

function RunDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth()
  const detail = useGet<R>(`${H}/payroll/runs/${id}`)
  const [confirm, setConfirm] = useState(false)
  const finalize = useAction(() => post(`${H}/payroll/runs/${id}/finalize`), { invalidate: [`${H}/payroll`, `${H}/dashboard`], success: 'Payroll finalized · employees notified', onSuccess: () => setConfirm(false) })
  const discard = useAction(() => del(`${H}/payroll/runs/${id}`), { invalidate: [`${H}/payroll`], success: 'Draft discarded', onSuccess: onClose })
  const data = detail.data
  const draft = data?.run.status === 'draft'
  return (
    <Modal open size="lg" title={data ? `Payroll · ${monthLabel(data.run.period)}` : 'Payroll run'} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Close</Button>
        {draft && can('hr:write') && <><Button variant="ghost" icon={Trash2} busy={discard.isPending} onClick={() => discard.mutate()}>Discard draft</Button>
          <Button icon={Lock} onClick={() => setConfirm(true)}>Finalize payroll</Button></>}</>}>
      {!data ? <Loading /> : (
        <>
          <Kpis items={[
            { label: 'Gross pay', value: money(data.run.totals.gross) },
            { label: 'Net pay', value: money(data.run.totals.net), tone: 'green' },
            { label: 'CNPS total', value: money(data.run.totals.cnps), tone: 'blue', hint: 'Employee + employer' },
            { label: 'IRPP + CAC', value: money(data.run.totals.irpp), tone: 'amber' },
            { label: 'Employer cost', value: money(data.run.totals.employer_cost), tone: 'gray' },
          ]} />
          <p className="small muted">Rule set: {data.rule_set.name} · {draft ? 'Draft — review before finalizing.' : `Finalized ${dateTime(data.run.finalized_at)}; payslips are immutable and visible to employees.`}</p>
          <DataTable rows={data.payslips} rowKey={(row) => row.id} empty={<Empty />} columns={[
            { key: 'employee_name', header: 'Employee' },
            { key: 'gross', header: 'Gross', align: 'right', mono: true, render: (row) => money(row.gross) },
            { key: 'cnps', header: 'CNPS', align: 'right', mono: true, render: (row) => money(row.lines.employee.find((line: R) => line.code === 'CNPS_PVID')?.amount) },
            { key: 'irpp', header: 'IRPP', align: 'right', mono: true, render: (row) => money(row.lines.employee.find((line: R) => line.code === 'IRPP')?.amount) },
            { key: 'deductions', header: 'All deductions', align: 'right', mono: true, render: (row) => money(row.employee_deductions) },
            { key: 'net', header: 'Net', align: 'right', mono: true, render: (row) => <strong>{money(row.net)}</strong> },
            { key: 'pdf', header: '', align: 'right', render: (row) => <DownloadButton path={`${H}/payslips/${row.id}.pdf`} filename={`payslip-${row.period}.pdf`} /> },
          ]} />
        </>
      )}
      {confirm && (
        <div className="callout"><CircleAlert size={18} aria-hidden /><div><strong>Finalize {data && monthLabel(data.run.period)}?</strong> Payslips become immutable and every employee with a login is notified in-app and by email.
          <div className="row" style={{ marginTop: 8 }}><Button small variant="secondary" onClick={() => setConfirm(false)}>Not yet</Button><Button small busy={finalize.isPending} onClick={() => finalize.mutate()}>Yes, finalize</Button></div></div></div>
      )}
    </Modal>
  )
}
