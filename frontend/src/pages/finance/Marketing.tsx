import { useState } from 'react'
import { Banknote, CalendarClock, Check, Megaphone, Plus, RefreshCw, UserCheck, X } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, Field, Input, Kpis, Loading, Modal, PageHeader, Pager, Panel, SearchBox, Select, Tabs, Textarea } from '../../components/ui'
import { fieldErrors, patch, post, qs } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, dateTime, label, METHOD_LABELS, money, monthLabel, percent, previousMonth } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { Page, R } from '../../lib/hooks'

const F = '/api/v1/finance'
const CATEGORIES = ['marketing', 'supplies', 'maintenance', 'utilities', 'it_services', 'travel', 'other'].map((value) => ({ value, label: label(value) }))
const CHANNELS = ['social', 'radio', 'events', 'print', 'referral', 'search', 'email'].map((value) => ({ value, label: label(value) }))
const STAGES = ['new', 'contacted', 'qualified', 'applied', 'converted', 'lost']

/* ---------------- Expenses ---------------- */
export function Expenses() {
  const { can, session } = useAuth()
  const [status, setStatus] = useState('')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [action, setAction] = useState<{ kind: 'reject' | 'pay'; row: R } | null>(null)
  const expenses = useGet<Page>(`${F}/expenses${qs({ status, category, q, page, size: 20 })}`)
  const approve = useAction((id: string) => post(`${F}/expenses/${id}/approve`, { note: '' }), { invalidate: [`${F}/expenses`, `${F}/dashboard`], success: 'Expense approved' })
  const writer = can('finance:write')
  return (
    <div className="stack">
      <PageHeader title="Expenses" subtitle="Submitted → approved → paid. The approver must be a different person from the submitter; paying an expense posts it to the ledger."
        actions={writer && <Button icon={Plus} onClick={() => setCreating(true)}>Submit expense</Button>} />
      <Panel title={<Tabs value={status} onChange={(value) => { setStatus(value); setPage(1) }} items={[{ value: '', label: 'All' }, { value: 'submitted', label: 'To approve' }, { value: 'approved', label: 'To pay' }, { value: 'paid', label: 'Paid' }, { value: 'rejected', label: 'Rejected' }]} />}
        actions={<><Select aria-label="Category" value={category} onChange={(event) => { setCategory(event.target.value); setPage(1) }} options={CATEGORIES} placeholder="All categories" />
          <SearchBox value={q} onChange={(value) => { setQ(value); setPage(1) }} placeholder="Vendor or description" /></>} flush>
        <DataTable rows={expenses.data?.items} loading={expenses.isLoading} error={expenses.error} rowKey={(row) => row.id} columns={[
          { key: 'expense_date', header: 'Date', render: (row) => date(row.expense_date) },
          { key: 'vendor', header: 'Vendor', render: (row) => <><strong>{row.vendor}</strong><span className="sub">{row.description}</span></> },
          { key: 'category', header: 'Category', render: (row) => label(row.category) },
          { key: 'amount', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.amount) },
          { key: 'status', header: 'Status', render: (row) => <><Badge status={row.status} />{row.decision_note && <span className="sub">{row.decision_note}</span>}</> },
          { key: 'actions', header: '', align: 'right', render: (row) => writer && (
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              {row.status === 'submitted' && <Button small variant="secondary" icon={Check} disabled={row.submitted_by === session!.user.id}
                title={row.submitted_by === session!.user.id ? 'Another officer must approve your own submission' : undefined} onClick={() => approve.mutate(row.id)}>Approve</Button>}
              {row.status === 'approved' && <Button small icon={Banknote} onClick={() => setAction({ kind: 'pay', row })}>Pay</Button>}
              {(row.status === 'submitted' || row.status === 'approved') && <Button small variant="ghost" icon={X} onClick={() => setAction({ kind: 'reject', row })}>Reject</Button>}
            </div>) },
        ]} />
        {expenses.data && <Pager page={page} size={20} total={expenses.data.total} onPage={setPage} />}
      </Panel>
      {creating && <ExpenseForm onClose={() => setCreating(false)} />}
      {action && <ExpenseAction action={action} onClose={() => setAction(null)} />}
    </div>
  )
}

function ExpenseForm({ onClose }: { onClose: () => void }) {
  const campaigns = useGet<R[]>(`${F}/campaigns`)
  const form = useForm({ category: 'supplies', description: '', vendor: '', amount: '', expense_date: new Date().toISOString().slice(0, 10), campaign_id: '' })
  const save = useAction(() => post(`${F}/expenses`, { ...form.values, amount: Number(form.values.amount), campaign_id: form.values.campaign_id || null }),
    { invalidate: [`${F}/expenses`], success: 'Expense submitted for approval', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Submit an expense" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Submit</Button></>}>
      <div className="form-grid">
        <Field label="Category"><Select {...form.bind('category')} options={CATEGORIES} /></Field>
        <Field label="Date" error={errors.expense_date}><Input type="date" {...form.bind('expense_date')} /></Field>
        <Field label="Vendor" error={errors.vendor}><Input {...form.bind('vendor')} /></Field>
        <Field label="Amount (FCFA)" error={errors.amount}><Input type="number" min={1} {...form.bind('amount')} /></Field>
        <Field label="Description" wide error={errors.description}><Input {...form.bind('description')} /></Field>
        {form.values.category === 'marketing' && <Field label="Marketing campaign" wide hint="Linking spend lets the system compute campaign ROI.">
          <Select {...form.bind('campaign_id')} placeholder="Not campaign-specific" options={(campaigns.data ?? []).map((row) => ({ value: row.id, label: row.name }))} /></Field>}
      </div>
    </Modal>
  )
}

function ExpenseAction({ action, onClose }: { action: { kind: 'reject' | 'pay'; row: R }; onClose: () => void }) {
  const [text, setText] = useState('')
  const run = useAction(() => post(`${F}/expenses/${action.row.id}/${action.kind}`, action.kind === 'pay' ? { reference: text } : { note: text }),
    { invalidate: [`${F}/expenses`, `${F}/dashboard`, `${F}/ledger`, `${F}/campaigns`], success: action.kind === 'pay' ? 'Expense paid and posted to the ledger' : 'Expense rejected', onSuccess: onClose })
  return (
    <Modal open title={action.kind === 'pay' ? `Pay ${action.row.vendor}` : `Reject expense from ${action.row.vendor}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={action.kind === 'pay' ? 'primary' : 'danger'} busy={run.isPending} disabled={text.trim().length < 3} onClick={() => run.mutate()}>{action.kind === 'pay' ? `Pay ${money(action.row.amount)}` : 'Reject'}</Button></>}>
      <Field label={action.kind === 'pay' ? 'Payment reference' : 'Reason'} hint={action.kind === 'pay' ? 'Cheque number or bank transfer reference' : 'Visible to the submitter'}>
        {action.kind === 'pay' ? <Input value={text} onChange={(event) => setText(event.target.value)} /> : <Textarea value={text} onChange={(event) => setText(event.target.value)} />}
      </Field>
    </Modal>
  )
}

/* ---------------- Campaigns ---------------- */
export function Campaigns() {
  const { can } = useAuth()
  const campaigns = useGet<R[]>(`${F}/campaigns`)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const selected = campaigns.data?.find((row) => row.id === selectedId) ?? campaigns.data?.[0]
  const totals = (campaigns.data ?? []).reduce((sum, row) => ({ leads: sum.leads + row.leads, won: sum.won + row.conversions, spend: sum.spend + row.spend, revenue: sum.revenue + row.revenue }), { leads: 0, won: 0, spend: 0, revenue: 0 })
  return (
    <div className="stack">
      <PageHeader title="Campaigns & leads" subtitle="Track prospects from first contact to enrolment. Revenue is attributed only from tuition actually collected after a lead converts."
        actions={can('finance:write') && <Button icon={Plus} onClick={() => setCreating(true)}>New campaign</Button>} />
      <Kpis items={[
        { label: 'Leads', value: String(totals.leads), icon: Megaphone },
        { label: 'Conversions', value: String(totals.won), hint: percent(totals.leads ? totals.won / totals.leads : null, 1) + ' conversion', tone: 'green' },
        { label: 'Campaign spend', value: money(totals.spend), tone: 'coral' },
        { label: 'Attributed collections', value: money(totals.revenue), hint: totals.spend ? `Portfolio ROI ${(((totals.revenue - totals.spend) / totals.spend) * 100).toFixed(0)}%` : undefined, tone: 'blue' },
      ]} />
      <Panel title="Campaigns" flush>
        <DataTable rows={campaigns.data} loading={campaigns.isLoading} error={campaigns.error} rowKey={(row) => row.id} onRowClick={(row) => setSelectedId(row.id)} columns={[
          { key: 'name', header: 'Campaign', render: (row) => <><strong>{row.name}</strong>{row.id === selected?.id && <Badge tone="teal">Selected</Badge>}<span className="sub">{label(row.channel)} · {date(row.starts_on)} – {date(row.ends_on)}</span></> },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
          { key: 'leads', header: 'Leads', align: 'right', mono: true },
          { key: 'conversions', header: 'Won', align: 'right', mono: true },
          { key: 'conversion_rate', header: 'Conv.', align: 'right', mono: true, render: (row) => percent(row.conversion_rate, 1) },
          { key: 'spend', header: 'Spend / budget', align: 'right', render: (row) => <span className="mono">{money(row.spend)}<span className="sub">of {money(row.budget)}</span></span> },
          { key: 'revenue', header: 'Collected', align: 'right', mono: true, render: (row) => money(row.revenue) },
          { key: 'roi_percent', header: 'ROI', align: 'right', render: (row) => row.roi_percent == null ? <span className="muted">n/a</span> : <Badge tone={row.roi_percent >= 0 ? 'green' : 'coral'}>{`${row.roi_percent.toFixed(1)}%`}</Badge> },
        ]} />
      </Panel>
      {selected && <LeadBoard campaign={selected} />}
      {creating && <CampaignForm onClose={() => setCreating(false)} />}
    </div>
  )
}

function LeadBoard({ campaign }: { campaign: R }) {
  const { can } = useAuth()
  const leads = useGet<R[]>(`${F}/campaigns/${campaign.id}/leads`)
  const [adding, setAdding] = useState(false)
  const [converting, setConverting] = useState<R | null>(null)
  const move = useAction(({ id, stage }: { id: string; stage: string }) => patch(`${F}/leads/${id}`, { stage }), { invalidate: [`${F}/campaigns`], success: 'Lead updated' })
  const writer = can('finance:write')
  return (
    <Panel title={`Lead pipeline · ${campaign.name}`} subtitle="Move leads through the funnel; converting links the lead to an invoiced student for ROI attribution."
      actions={writer && <Button small icon={Plus} onClick={() => setAdding(true)}>Add lead</Button>} flush>
      {!leads.data ? <Loading /> : (
        <div className="pipeline">
          {STAGES.map((stage) => {
            const rows = leads.data!.filter((row) => row.stage === stage)
            return (
              <div key={stage} className="pipeline-col">
                <h3><span>{label(stage)}</span><span className="mono">{rows.length}</span></h3>
                {rows.map((lead) => (
                  <div key={lead.id} className="card-item">
                    <strong>{lead.name}</strong>
                    <span className="small muted">{lead.program_interest || 'Programme undecided'}</span>
                    {writer && !['converted', 'lost'].includes(stage) && (
                      <div className="row">
                        <select className="select" style={{ minHeight: 28, fontSize: 12.5, padding: '2px 6px', flex: 1 }} aria-label={`Move ${lead.name}`} value={stage}
                          onChange={(event) => move.mutate({ id: lead.id, stage: event.target.value })}>
                          {STAGES.filter((value) => value !== 'converted').map((value) => <option key={value} value={value}>{label(value)}</option>)}
                        </select>
                        <Button small variant="ghost" icon={UserCheck} onClick={() => setConverting(lead)} aria-label={`Convert ${lead.name}`} />
                      </div>
                    )}
                    {stage === 'converted' && <span className="small muted">Enrolled {date(lead.converted_at)}</span>}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
      {adding && <LeadForm campaignId={campaign.id} onClose={() => setAdding(false)} />}
      {converting && <ConvertForm lead={converting} onClose={() => setConverting(null)} />}
    </Panel>
  )
}

function CampaignForm({ onClose }: { onClose: () => void }) {
  const form = useForm({ name: '', channel: 'social', starts_on: '', ends_on: '', budget: '' })
  const save = useAction(() => post(`${F}/campaigns`, { ...form.values, budget: Number(form.values.budget || 0) }), { invalidate: [`${F}/campaigns`], success: 'Campaign created', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="New marketing campaign" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Create</Button></>}>
      <div className="form-grid">
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Channel"><Select {...form.bind('channel')} options={CHANNELS} /></Field>
        <Field label="Budget (FCFA)" error={errors.budget}><Input type="number" min={0} {...form.bind('budget')} /></Field>
        <Field label="Starts" error={errors.starts_on}><Input type="date" {...form.bind('starts_on')} /></Field>
        <Field label="Ends" error={errors.ends_on}><Input type="date" {...form.bind('ends_on')} /></Field>
      </div>
    </Modal>
  )
}

function LeadForm({ campaignId, onClose }: { campaignId: string; onClose: () => void }) {
  const form = useForm({ name: '', phone: '', email: '', program_interest: '', notes: '' })
  const save = useAction(() => post(`${F}/campaigns/${campaignId}/leads`, { ...form.values, email: form.values.email || null }), { invalidate: [`${F}/campaigns`], success: 'Lead added', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Add lead" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Add lead</Button></>}>
      <div className="form-grid">
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Phone" error={errors.phone}><Input inputMode="tel" {...form.bind('phone')} placeholder="6XX XXX XXX" /></Field>
        <Field label="Email" error={errors.email}><Input type="email" {...form.bind('email')} /></Field>
        <Field label="Programme of interest" wide><Input {...form.bind('program_interest')} /></Field>
        <Field label="Notes" wide><Textarea {...form.bind('notes')} /></Field>
      </div>
    </Modal>
  )
}

function ConvertForm({ lead, onClose }: { lead: R; onClose: () => void }) {
  const [q, setQ] = useState(lead.name.split(' ')[0])
  const [student, setStudent] = useState('')
  const students = useGet<R[]>(`${F}/students${qs({ q })}`)
  const save = useAction(() => post(`${F}/leads/${lead.id}/convert`, { student_id: student }), { invalidate: [`${F}/campaigns`], success: 'Lead converted and attributed', onSuccess: onClose })
  return (
    <Modal open title={`Convert ${lead.name}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={!student} onClick={() => save.mutate()}>Mark as enrolled</Button></>}>
      <p className="muted">Choose the registered, invoiced student record this lead became. Their future tuition collections count toward this campaign's ROI.</p>
      <SearchBox value={q} onChange={setQ} placeholder="Search invoiced students" />
      <div className="check-list">
        {(students.data ?? []).map((row) => (
          <label key={row.student_id} className="checkbox"><input type="radio" name="student" checked={student === row.student_id} onChange={() => setStudent(row.student_id)} />
            <span>{row.name} <span className="muted mono">{row.student_no}</span></span></label>
        ))}
        {students.data && !students.data.length && <span className="muted">No invoiced students match.</span>}
      </div>
    </Modal>
  )
}

/* ---------------- Monthly reports ---------------- */
export function Reports() {
  const { can } = useAuth()
  const reports = useGet<R[]>(`${F}/reports/monthly`, 30_000)
  const [period, setPeriod] = useState(previousMonth())
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState<R | null>(null)
  const regenerate = useAction(() => post(`${F}/reports/monthly`, { period }), { invalidate: [`${F}/reports`], success: 'Report regenerated as a new version', onSuccess: () => setOpen(false) })
  const latest = (reports.data ?? []).filter((row, index, rows) => rows.findIndex((other) => other.period === row.period) === index)
  return (
    <div className="stack">
      <PageHeader title="Monthly financial summaries" subtitle={<><CalendarClock size={14} aria-hidden /> Generated automatically by the finance worker for every closed month (Africa/Douala time), in FCFA. Regenerating keeps earlier versions for audit.</>}
        actions={can('finance:write') && <Button variant="secondary" icon={RefreshCw} onClick={() => setOpen(true)}>Regenerate a month</Button>} />
      <Panel title="Reports" flush>
        <DataTable rows={latest} loading={reports.isLoading} error={reports.error} rowKey={(row) => row.id} onRowClick={setSelected} empty="The first report appears after the scheduler runs." columns={[
          { key: 'period', header: 'Month', render: (row) => <strong>{monthLabel(row.period)}</strong> },
          { key: 'billed', header: 'Billed', align: 'right', mono: true, render: (row) => money(row.summary.billed) },
          { key: 'collected', header: 'Collected', align: 'right', mono: true, render: (row) => money(row.summary.collected) },
          { key: 'expenses', header: 'Expenses', align: 'right', mono: true, render: (row) => money(row.summary.expenses_paid) },
          { key: 'net', header: 'Net cash', align: 'right', render: (row) => <span className={`mono ${row.summary.net_cash_flow < 0 ? 'score-fail' : ''}`}>{money(row.summary.net_cash_flow)}</span> },
          { key: 'version', header: 'Version', render: (row) => <><Badge status={row.trigger === 'scheduled' ? 'completed' : 'submitted'}>{`v${row.version} · ${row.trigger}`}</Badge><span className="sub">{dateTime(row.generated_at)}</span></> },
          { key: 'pdf', header: '', align: 'right', render: (row) => <DownloadButton path={`${F}/reports/monthly/${row.id}.pdf`} filename={`financial-summary-${row.period}.pdf`} /> },
        ]} />
      </Panel>
      {selected && (
        <Modal open size="lg" title={`Financial summary · ${monthLabel(selected.period)}`} onClose={() => setSelected(null)}
          footer={<><Button variant="secondary" onClick={() => setSelected(null)}>Close</Button><DownloadButton path={`${F}/reports/monthly/${selected.id}.pdf`} filename={`financial-summary-${selected.period}.pdf`} variant="primary" small={false}>Download PDF</DownloadButton></>}>
          <Kpis items={[
            { label: 'Billed', value: money(selected.summary.billed), hint: `${selected.summary.invoices_issued} invoice(s)` },
            { label: 'Collected', value: money(selected.summary.collected), hint: `${selected.summary.payments_received} payment(s)`, tone: 'green' },
            { label: 'Expenses', value: money(selected.summary.expenses_paid), tone: 'coral' },
            { label: 'Receivables at month end', value: money(selected.summary.receivables_at_month_end), tone: 'amber' },
          ]} />
          <div className="grid cols-2">
            <DataTable rows={Object.entries(selected.summary.collections_by_method).map(([key, value]) => ({ key, value }))} rowKey={(row) => row.key} empty="No collections."
              columns={[{ key: 'key', header: 'Channel', render: (row) => METHOD_LABELS[row.key] ?? row.key }, { key: 'value', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.value as number) }]} />
            <DataTable rows={Object.entries(selected.summary.expenses_by_category).map(([key, value]) => ({ key, value }))} rowKey={(row) => row.key} empty="No expenses."
              columns={[{ key: 'key', header: 'Category', render: (row) => label(row.key) }, { key: 'value', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.value as number) }]} />
          </div>
          {selected.summary.campaigns.length ? <DataTable rows={selected.summary.campaigns} rowKey={(row) => row.name} columns={[
            { key: 'name', header: 'Campaign' }, { key: 'new_leads', header: 'New leads', align: 'right', mono: true }, { key: 'conversions', header: 'Conversions', align: 'right', mono: true },
            { key: 'roi_percent', header: 'ROI to date', align: 'right', render: (row) => row.roi_percent == null ? 'n/a' : `${row.roi_percent.toFixed(1)}%` },
          ]} /> : <Empty title="No campaigns active this month" />}
        </Modal>
      )}
      <Modal open={open} title="Regenerate a monthly report" onClose={() => setOpen(false)} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button busy={regenerate.isPending} onClick={() => regenerate.mutate()}>Generate new version</Button></>}>
        <Field label="Month" hint="Only closed months can be reported."><Input type="month" max={previousMonth()} value={period} onChange={(event) => setPeriod(event.target.value)} /></Field>
      </Modal>
    </div>
  )
}
