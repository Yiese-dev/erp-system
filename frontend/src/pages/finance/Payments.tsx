import { useState } from 'react'
import { CircleCheck, CircleX, Clock3, Info, LoaderCircle, Smartphone } from 'lucide-react'
import { Badge, Button, DataTable, DownloadButton, Empty, Field, Input, Kpis, Loading, Modal, PageHeader, Panel } from '../../components/ui'
import { ApiError, fieldErrors, idempotencyKey, post } from '../../lib/api'
import { date, dateTime, METHOD_LABELS, money } from '../../lib/format'
import { useAction, useGet } from '../../lib/hooks'
import type { R } from '../../lib/hooks'

const F = '/api/v1/finance'

export function Pay() {
  const summary = useGet<R>(`${F}/me/summary`)
  const [paying, setPaying] = useState<R | null>(null)
  const data = summary.data
  const open = data?.invoices.filter((row: R) => row.balance > 0) ?? []
  return (
    <div className="stack">
      <PageHeader title="Fees & payments" subtitle="Pay tuition from your MTN Mobile Money or Orange Money wallet. A digital receipt is issued as soon as the operator confirms." />
      <Kpis items={[
        { label: 'Balance due', value: money(data?.balance), tone: data?.balance ? 'amber' : 'green', icon: Smartphone },
        { label: 'Invoices', value: String(data?.invoices.length ?? '—'), tone: 'blue' },
        { label: 'Receipts', value: String(data?.receipts.length ?? '—'), tone: 'gray' },
      ]} />
      <Panel title="Invoices" flush>
        <DataTable rows={data?.invoices} loading={summary.isLoading} error={summary.error} rowKey={(row) => row.id} empty="No invoices yet. Your tuition invoice appears automatically after registration." columns={[
          { key: 'number', header: 'Invoice', mono: true },
          { key: 'term', header: 'Term', render: (row) => <>{row.term_name}<span className="sub">{row.program_name}</span></> },
          { key: 'total', header: 'Total', align: 'right', mono: true, render: (row) => money(row.total) },
          { key: 'balance', header: 'Balance', align: 'right', mono: true, render: (row) => money(row.balance) },
          { key: 'due_on', header: 'Due', render: (row) => date(row.due_on) },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.overdue ? 'overdue' : row.status} /> },
          { key: 'pay', header: '', align: 'right', render: (row) => row.balance > 0 && <Button small icon={Smartphone} onClick={() => setPaying(row)}>Pay</Button> },
        ]} />
      </Panel>
      <Panel title="Receipts" flush>
        <DataTable rows={data?.receipts} loading={summary.isLoading} rowKey={(row) => row.id} empty="No payments recorded yet." columns={[
          { key: 'number', header: 'Receipt', mono: true }, { key: 'issued_at', header: 'Date', render: (row) => dateTime(row.issued_at) },
          { key: 'term_name', header: 'For' }, { key: 'method', header: 'Channel', render: (row) => METHOD_LABELS[row.method] ?? row.method },
          { key: 'amount', header: 'Amount', align: 'right', mono: true, render: (row) => money(row.amount) },
          { key: 'pdf', header: '', align: 'right', render: (row) => <DownloadButton path={`${F}/receipts/${row.id}.pdf`} filename={`${row.number}.pdf`}>Receipt</DownloadButton> },
        ]} />
      </Panel>
      {!open.length && data && data.invoices.length > 0 && <Empty title="All fees are settled" text="Thank you. Download your receipts above at any time." icon={CircleCheck} />}
      {paying && <PayModal invoice={paying} onClose={() => setPaying(null)} />}
    </div>
  )
}

function PayModal({ invoice, onClose }: { invoice: R; onClose: () => void }) {
  const [provider, setProvider] = useState('mtn_momo')
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState(String(invoice.balance))
  const [key] = useState(idempotencyKey)
  const [intent, setIntent] = useState<R | null>(null)
  const start = useAction(() => post<R>(`${F}/invoices/${invoice.id}/payment-intents`, { provider, msisdn: phone, amount: Number(amount), idempotency_key: key }),
    { onSuccess: setIntent, silent: true })
  const status = useGet<R>(intent ? `${F}/payment-intents/${intent.id}` : null, intent && !['succeeded', 'failed', 'expired'].includes(intent.status) ? 2000 : false)
  const current = status.data ?? intent
  const finished = current && current.status !== 'pending'
  const errors = fieldErrors(start.error)
  const failure = start.error instanceof ApiError ? start.error : null
  const close = () => { onClose() }
  if (current) {
    return (
      <Modal open title="Mobile-money payment" onClose={close} footer={<Button variant={finished ? 'primary' : 'secondary'} onClick={close}>{finished ? 'Done' : 'Close and check later'}</Button>}>
        {current.status === 'pending' && (
          <div className="payment-state"><LoaderCircle size={40} className="spin" aria-hidden /><h2>Approve on your phone</h2>
            <p>A payment request for <strong>{money(current.amount)}</strong> was sent to <span className="mono">{current.msisdn_masked}</span> via {METHOD_LABELS[current.provider]}. Enter your PIN on your handset to confirm.</p>
            <p className="small muted"><Clock3 size={13} aria-hidden /> Waiting for operator confirmation… requests expire after 3 minutes.</p></div>
        )}
        {current.status === 'succeeded' && (
          <div className="payment-state"><CircleCheck size={44} aria-hidden /><h2>Payment confirmed</h2>
            <p>{money(current.amount)} received. Receipt <strong className="mono">{current.receipt_number}</strong> has been issued.</p>
            {current.receipt_id && <DownloadButton path={`${F}/receipts/${current.receipt_id}.pdf`} filename={`${current.receipt_number}.pdf`} variant="primary" small={false}>Download receipt</DownloadButton>}</div>
        )}
        {(current.status === 'failed' || current.status === 'expired') && (
          <div className="payment-state failed"><CircleX size={44} aria-hidden /><h2>Payment {current.status === 'expired' ? 'timed out' : 'declined'}</h2>
            <p>{current.failure_reason}</p><p className="small muted">No money was taken. You can close this window and try again.</p></div>
        )}
      </Modal>
    )
  }
  return (
    <Modal open title={`Pay ${invoice.number}`} onClose={close}
      footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button icon={Smartphone} busy={start.isPending} disabled={!phone || !amount} onClick={() => start.mutate()}>Send payment request</Button></>}>
      <div className="notice"><Info size={18} aria-hidden /><span><strong>Sandbox (simulated operator).</strong> No real money moves. Numbers ending in <b>0</b> are declined, ending in <b>9</b> never answer (timeout), any other number is approved after a few seconds.</span></div>
      <fieldset className="provider-options" style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className="sr-only">Mobile-money operator</legend>
        <label><input type="radio" name="provider" value="mtn_momo" checked={provider === 'mtn_momo'} onChange={() => setProvider('mtn_momo')} /><span className="provider-logo mtn">MTN</span>MTN MoMo</label>
        <label><input type="radio" name="provider" value="orange_money" checked={provider === 'orange_money'} onChange={() => setProvider('orange_money')} /><span className="provider-logo orange">OM</span>Orange Money</label>
      </fieldset>
      <div className="form-grid">
        <Field label="Wallet phone number" hint="e.g. 677 12 34 56" error={errors.msisdn}><Input inputMode="tel" autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} /></Field>
        <Field label="Amount (FCFA)" hint={`Balance ${money(invoice.balance)} · part payments allowed`} error={errors.amount}><Input type="number" min={100} max={invoice.balance} value={amount} onChange={(event) => setAmount(event.target.value)} /></Field>
      </div>
      {failure && !Object.keys(errors).length && <div className="error-box" role="alert"><CircleX size={18} aria-hidden /><span>{failure.message}</span></div>}
      {start.isPending && <Loading rows={1} />}
    </Modal>
  )
}
