import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CircleAlert, CircleCheck, Plus, RotateCcw, Scale, TrendingUp, Wallet } from 'lucide-react'
import { Bars, Donut, PALETTE } from '../../components/charts'
import { Badge, Button, DataTable, DownloadButton, Empty, ErrorState, Field, Input, Kpis, Loading, Modal, PageHeader, Pager, Panel, SearchBox, Select, Tabs } from '../../components/ui'
import { fieldErrors, post, qs } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, dateTime, METHOD_LABELS, money, monthLabel, percent } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { Page, R } from '../../lib/hooks'

const F = '/api/v1/finance'

/* ---------------- Overview ---------------- */
export function FinanceOverview() {
  const query = useGet<R>(`${F}/dashboard`)
  const data = query.data as R
  if (query.error) return <ErrorState error={query.error} retry={() => query.refetch()} />
  return (
    <div className="stack">
      <PageHeader title="Finance & marketing overview" subtitle="Tuition billing, mobile-money collections, operating expenses and campaign return, all in FCFA."
        actions={<><Link className="btn btn-secondary" to="/finance/reports">Monthly reports</Link><Link className="btn btn-primary" to="/finance/invoices">Invoices</Link></>} />
      <Kpis items={[
        { label: 'Billed', value: money(data?.totals.billed), hint: 'All tuition invoices', icon: TrendingUp },
        { label: 'Collected', value: money(data?.totals.collected), hint: `${percent(data?.totals.collection_rate)} collection rate`, tone: 'green', icon: Wallet },
        { label: 'Outstanding', value: money(data?.totals.outstanding), hint: `${money(data?.totals.overdue)} overdue`, tone: 'amber' },
        { label: 'Net cash (YTD)', value: money(data?.totals.net_cash_ytd), hint: `${money(data?.totals.expenses_ytd)} expenses paid`, tone: data && data.totals.net_cash_ytd < 0 ? 'coral' : 'blue' },
        { label: 'Ledger', value: data ? (data.ledger_balanced ? 'Balanced' : 'Unbalanced') : '—', hint: 'Debits = credits', tone: data?.ledger_balanced ? 'green' : 'coral', icon: Scale },
      ]} />
      {data?.billing_issues > 0 && (
        <div className="callout"><CircleAlert size={18} aria-hidden /><span>{data.billing_issues} registration(s) are waiting for a fee plan before they can be invoiced. <Link to="/finance/fee-plans">Resolve now</Link></span></div>
      )}
      <div className="grid cols-main">
        <Panel title="Monthly cash flow" subtitle="Billed vs collected vs expenses paid">
          {data ? <Bars money data={data.monthly.map((row: R) => ({ ...row, month: monthLabel(row.period) }))} x="month"
            series={[{ key: 'billed', label: 'Billed', color: PALETTE[2] }, { key: 'collected', label: 'Collected' }, { key: 'expenses', label: 'Expenses', color: PALETTE[1] }]} height={280} /> : <Loading />}
        </Panel>
        <Panel title="Collections by channel">
          {data ? (data.collections_by_method.length ? <Donut data={data.collections_by_method.map((row: R) => ({ name: row.label, value: row.amount }))} format={money} /> : <Empty />) : <Loading />}
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Campaign performance" subtitle="ROI = (collected tuition from converted students − paid campaign spend) ÷ spend" flush actions={<Link to="/finance/campaigns">Campaigns</Link>}>
          <DataTable rows={data?.campaigns} loading={!data} rowKey={(row) => row.campaign_id} columns={[
            { key: 'name', header: 'Campaign', render: (row) => <><strong>{row.name}</strong><span className="sub">{row.channel}</span></> },
            { key: 'leads', header: 'Leads', align: 'right', mono: true },
            { key: 'conversion_rate', header: 'Conv.', align: 'right', mono: true, render: (row) => percent(row.conversion_rate) },
            { key: 'spend', header: 'Spend', align: 'right', mono: true, render: (row) => money(row.spend) },
            { key: 'roi_percent', header: 'ROI', align: 'right', render: (row) => row.roi_percent == null ? '—' : <Badge tone={row.roi_percent >= 0 ? 'green' : 'coral'}>{`${row.roi_percent.toFixed(0)}%`}</Badge> },
          ]} />
        </Panel>
        <Panel title="Overdue invoices" flush actions={<Link to="/finance/invoices?overdue=true">All overdue</Link>}>
          <DataTable rows={data?.overdue} loading={!data} rowKey={(row) => row.id} empty="No overdue invoices." columns={[
            { key: 'number', header: 'Invoice', mono: true },
            { key: 'student_name', header: 'Student' },
            { key: 'due_on', header: 'Due', render: (row) => date(row.due_on) },
            { key: 'balance', header: 'Balance', align: 'right', mono: true, render: (row) => money(row.balance) },
          ]} />
        </Panel>
      </div>
    </div>
  )
}

/* ---------------- Invoices ---------------- */
export function Invoices() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [overdue, setOverdue] = useState(() => new URLSearchParams(location.search).get('overdue') === 'true')
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const invoices = useGet<Page>(`${F}/invoices${qs({ q, status, overdue, page, size: 20 })}`)
  return (
    <div className="stack">
      <PageHeader title="Tuition invoices" subtitle="Invoices are created automatically from Academic enrolment events, priced from a snapshot of the applicable fee plan." />
      <Panel title={<Tabs value={overdue ? 'overdue' : status} onChange={(value) => { setOverdue(value === 'overdue'); setStatus(value === 'overdue' ? '' : value); setPage(1) }}
        items={[{ value: '', label: 'All' }, { value: 'issued', label: 'Unpaid' }, { value: 'partially_paid', label: 'Part paid' }, { value: 'paid', label: 'Paid' }, { value: 'overdue', label: 'Overdue' }]} />}
        actions={<SearchBox value={q} onChange={(value) => { setQ(value); setPage(1) }} placeholder="Invoice, student or number" />} flush>
        <DataTable rows={invoices.data?.items} loading={invoices.isLoading} error={invoices.error} rowKey={(row) => row.id} onRowClick={(row) => setSelected(row.id)} columns={[
          { key: 'number', header: 'Invoice', mono: true },
          { key: 'student', header: 'Student', render: (row) => <><strong>{row.student_name}</strong><span className="sub">{row.student_no}</span></> },
          { key: 'term_name', header: 'Term', render: (row) => <>{row.term_name}<span className="sub">{row.program_name}</span></> },
          { key: 'total', header: 'Total', align: 'right', mono: true, render: (row) => money(row.total) },
          { key: 'balance', header: 'Balance', align: 'right', mono: true, render: (row) => money(row.balance) },
          { key: 'due_on', header: 'Due', render: (row) => date(row.due_on) },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.overdue ? 'overdue' : row.status} /> },
        ]} />
        {invoices.data && <Pager page={page} size={20} total={invoices.data.total} onPage={setPage} />}
      </Panel>
      {selected && <InvoiceDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

export function InvoiceDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth()
  const detail = useGet<R>(`${F}/invoices/${id}`)
  const form = useForm({ method: 'bank_transfer', amount: '', reference: '' })
  const record = useAction(() => post(`${F}/invoices/${id}/payments`, { ...form.values, amount: Number(form.values.amount) }),
    { invalidate: [`${F}/invoices`, `${F}/dashboard`, `${F}/receipts`, `${F}/ledger`], success: (result: R) => `Payment recorded · receipt ${result.receipt.number}`, onSuccess: () => form.reset() })
  const data = detail.data
  const invoice = data?.invoice
  const errors = fieldErrors(record.error)
  return (
    <Modal open size="lg" title={invoice ? `Invoice ${invoice.number}` : 'Invoice'} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {!data ? <Loading /> : (
        <>
          <div className="grid cols-2">
            <dl className="kv">
              <dt>Student</dt><dd>{invoice.student_name} · {invoice.student_no}</dd>
              <dt>Programme</dt><dd>{invoice.program_name}</dd>
              <dt>Term</dt><dd>{invoice.term_name}</dd>
              <dt>Issued</dt><dd>{dateTime(invoice.issued_at)} · {invoice.source === 'event' ? 'enrolment event' : 'import'}</dd>
            </dl>
            <dl className="kv">
              <dt>Total</dt><dd className="mono">{money(invoice.total)}</dd>
              <dt>Paid</dt><dd className="mono">{money(invoice.paid)}</dd>
              <dt>Balance</dt><dd className="mono">{money(invoice.balance)}</dd>
              <dt>Status</dt><dd><Badge status={invoice.overdue ? 'overdue' : invoice.status} /> · due {date(invoice.due_on)}</dd>
            </dl>
          </div>
          <DataTable rows={data.lines} rowKey={(row) => row.id} columns={[{ key: 'description', header: 'Line' }, { key: 'amount', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.amount) }]} />
          <div><h3 style={{ marginBottom: 6 }}>Receipts</h3>
            <DataTable rows={data.receipts} rowKey={(row) => row.id} empty="No payments yet." columns={[
              { key: 'number', header: 'Receipt', mono: true }, { key: 'issued_at', header: 'Date', render: (row) => dateTime(row.issued_at) },
              { key: 'method', header: 'Channel', render: (row) => METHOD_LABELS[row.method] ?? row.method },
              { key: 'amount', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.amount) },
              { key: 'pdf', header: '', align: 'right', render: (row) => <DownloadButton path={`${F}/receipts/${row.id}.pdf`} filename={`${row.number}.pdf`} /> },
            ]} />
          </div>
          {data.attempts.length > 0 && <div><h3 style={{ marginBottom: 6 }}>Mobile-money attempts</h3>
            <DataTable rows={data.attempts} rowKey={(row) => row.id} columns={[
              { key: 'created_at', header: 'Started', render: (row) => dateTime(row.created_at) }, { key: 'provider', header: 'Provider', render: (row) => METHOD_LABELS[row.provider] },
              { key: 'msisdn_masked', header: 'Phone', mono: true }, { key: 'amount', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.amount) },
              { key: 'status', header: 'Status', render: (row) => <><Badge status={row.status} />{row.failure_reason && <span className="sub">{row.failure_reason}</span>}</> },
            ]} /></div>}
          {can('finance:write') && invoice.balance > 0 && (
            <form className="panel" style={{ padding: 14 }} onSubmit={(event) => { event.preventDefault(); record.mutate() }}>
              <h3 style={{ marginBottom: 10 }}>Record a bank or cash payment</h3>
              <div className="form-grid">
                <Field label="Channel"><Select {...form.bind('method')} options={[{ value: 'bank_transfer', label: 'Bank transfer' }, { value: 'cash', label: 'Cash at bursary' }]} /></Field>
                <Field label="Amount (FCFA)" hint={`Available: ${money(data.available)}`} error={errors.amount}><Input type="number" min={1} max={data.available} {...form.bind('amount')} /></Field>
                <Field label="Reference" wide error={errors.reference}><Input {...form.bind('reference')} placeholder="Bank slip or cash book reference" /></Field>
              </div>
              <div className="row" style={{ marginTop: 12, justifyContent: 'flex-end' }}><Button type="submit" busy={record.isPending} disabled={!form.values.amount || !form.values.reference}>Record payment</Button></div>
            </form>
          )}
        </>
      )}
    </Modal>
  )
}

/* ---------------- Fee plans & billing issues ---------------- */
export function FeePlans() {
  const { can } = useAuth()
  const plans = useGet<R[]>(`${F}/fee-plans`)
  const issues = useGet<R[]>(`${F}/billing-issues`, 10_000)
  const [creating, setCreating] = useState(false)
  const retry = useAction((id: string) => post(`${F}/billing-issues/${id}/retry`), { invalidate: [`${F}/billing-issues`, `${F}/invoices`, `${F}/dashboard`], success: (row: R) => `Invoice ${row.number} issued` })
  return (
    <div className="stack">
      <PageHeader title="Fee plans & billing" subtitle="Tuition per programme and term. Changing a plan never alters invoices already issued: each invoice keeps a snapshot of the price it was billed at."
        actions={can('finance:write') && <Button icon={Plus} onClick={() => setCreating(true)}>New fee plan</Button>} />
      {issues.data && issues.data.length > 0 ? (
        <Panel title="Registrations waiting for a fee plan" subtitle="The enrolment event was received but no active plan matched. Create the plan to bill them automatically, or retry." flush>
          <DataTable rows={issues.data} rowKey={(row) => row.id} columns={[
            { key: 'student', header: 'Student', render: (row) => <><strong>{row.payload.student_name}</strong><span className="sub">{row.payload.student_no}</span></> },
            { key: 'program', header: 'Programme / term', render: (row) => `${row.payload.program_name} · ${row.payload.term_name}` },
            { key: 'reason', header: 'Reason' },
            { key: 'attempts', header: 'Attempts', align: 'right', mono: true },
            { key: 'retry', header: '', align: 'right', render: (row) => can('finance:write') && <Button small variant="secondary" icon={RotateCcw} onClick={() => retry.mutate(row.id)}>Retry</Button> },
          ]} />
        </Panel>
      ) : issues.data && <div className="callout teal"><CircleCheck size={18} aria-hidden /><span>No billing issues. Every enrolment event has produced an invoice.</span></div>}
      <Panel title="Fee plans" flush>
        <DataTable rows={plans.data} loading={plans.isLoading} error={plans.error} rowKey={(row) => row.id} columns={[
          { key: 'term_name', header: 'Term' }, { key: 'program_name', header: 'Programme' },
          { key: 'amount', header: 'Tuition', align: 'right', mono: true, render: (row) => money(row.amount) },
          { key: 'due_days', header: 'Payment terms', render: (row) => `${row.due_days} days` },
          { key: 'active', header: 'Status', render: (row) => <Badge status={row.active ? 'active' : 'inactive'} /> },
        ]} />
      </Panel>
      {creating && <FeePlanForm onClose={() => setCreating(false)} />}
    </div>
  )
}

function FeePlanForm({ onClose }: { onClose: () => void }) {
  const programs = useGet<Page>('/api/v1/academic/programs?size=100')
  const terms = useGet<R[]>('/api/v1/academic/terms')
  const form = useForm({ program_id: '', term_id: '', amount: '', due_days: '30' })
  const program = programs.data?.items.find((row) => row.id === form.values.program_id)
  const term = terms.data?.find((row) => row.id === form.values.term_id)
  const save = useAction(() => post<R>(`${F}/fee-plans`, { ...form.values, amount: Number(form.values.amount), due_days: Number(form.values.due_days), program_name: program?.name, term_name: term?.name }),
    { invalidate: [`${F}/fee-plans`, `${F}/billing-issues`, `${F}/invoices`], success: (result: R) => result.resolved_issues ? `Fee plan created · ${result.resolved_issues} waiting registration(s) invoiced` : 'Fee plan created', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="New fee plan" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={!program || !term || !form.values.amount} onClick={() => save.mutate()}>Create plan</Button></>}>
      <div className="form-grid">
        <Field label="Programme" wide><Select {...form.bind('program_id')} placeholder="Choose" options={(programs.data?.items ?? []).map((row) => ({ value: row.id, label: `${row.code} · ${row.name}` }))} /></Field>
        <Field label="Term" wide><Select {...form.bind('term_id')} placeholder="Choose" options={(terms.data ?? []).map((row) => ({ value: row.id, label: row.name }))} /></Field>
        <Field label="Tuition (FCFA)" error={errors.amount}><Input type="number" min={1} {...form.bind('amount')} /></Field>
        <Field label="Payment terms (days)" error={errors.due_days}><Input type="number" min={0} max={180} {...form.bind('due_days')} /></Field>
      </div>
    </Modal>
  )
}

/* ---------------- Ledger ---------------- */
export function Ledger() {
  const balance = useGet<R>(`${F}/ledger/trial-balance`)
  const [page, setPage] = useState(1)
  const entries = useGet<R>(`${F}/ledger/entries?page=${page}&size=15`)
  const data = balance.data
  return (
    <div className="stack">
      <PageHeader title="General ledger" subtitle="Double-entry journal generated by invoices, payments and expenses. Each posting is written in the same database transaction as the business event." />
      <div className="grid cols-main">
        <Panel title="Recent journal entries" flush>
          {entries.error ? <ErrorState error={entries.error} /> : !entries.data ? <Loading /> : (
            <>
              <div className="table-wrap"><table className="data"><thead><tr><th>Date</th><th>Memo</th><th>Account</th><th style={{ textAlign: 'right' }}>Debit</th><th style={{ textAlign: 'right' }}>Credit</th></tr></thead>
                <tbody>{entries.data.items.flatMap((entry: R) => entry.lines.map((line: R, index: number) => (
                  <tr key={line.id}>
                    <td>{index === 0 ? date(entry.entry_date) : ''}</td><td>{index === 0 ? entry.memo : ''}</td>
                    <td><span className="mono">{line.account_code}</span> {line.account_name}</td>
                    <td className="mono" style={{ textAlign: 'right' }}>{line.debit ? money(line.debit) : ''}</td>
                    <td className="mono" style={{ textAlign: 'right' }}>{line.credit ? money(line.credit) : ''}</td>
                  </tr>
                )))}</tbody></table></div>
              <Pager page={page} size={15} total={entries.data.total} onPage={setPage} />
            </>
          )}
        </Panel>
        <Panel title="Trial balance" actions={data && <Badge status={data.balanced ? 'ok' : 'issue'}>{data.balanced ? 'Balanced' : 'Out of balance'}</Badge>} flush>
          <DataTable rows={data?.accounts} loading={balance.isLoading} error={balance.error} rowKey={(row) => row.code}
            footer={data && <tfoot><tr><td>Total</td><td className="mono" style={{ textAlign: 'right' }}>{money(data.total_debit)}</td><td className="mono" style={{ textAlign: 'right' }}>{money(data.total_credit)}</td></tr></tfoot>}
            columns={[
              { key: 'name', header: 'Account', render: (row) => <><span className="mono">{row.code}</span> {row.name}</> },
              { key: 'debit', header: 'Debit', align: 'right', mono: true, render: (row) => money(row.debit) },
              { key: 'credit', header: 'Credit', align: 'right', mono: true, render: (row) => money(row.credit) },
            ]} />
        </Panel>
      </div>
    </div>
  )
}
