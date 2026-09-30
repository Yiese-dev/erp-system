import { useState } from 'react'
import { ArrowDownUp, Check, History, PackagePlus, Plus, Star, Undo2, UserCheck, Wrench, X } from 'lucide-react'
import { Badge, Button, DataTable, Field, Input, Modal, PageHeader, Panel, SearchBox, Select, Stars, Tabs, Textarea } from '../../components/ui'
import { fieldErrors, patch, post } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { date, dateTime, label, money } from '../../lib/format'
import { useAction, useForm, useGet } from '../../lib/hooks'
import type { Page, R } from '../../lib/hooks'

const H = '/api/v1/hr'

function useEmployees() {
  const employees = useGet<Page>(`${H}/employees?size=200`)
  return (employees.data?.items ?? []).map((row) => ({ value: row.id, label: `${row.name} · ${row.department}` }))
}

/* ---------------- Leave ---------------- */
export function Leave() {
  const { can } = useAuth()
  const [status, setStatus] = useState('pending')
  const requests = useGet<R[]>(`${H}/leave${status ? `?status=${status}` : ''}`)
  const [deciding, setDeciding] = useState<{ row: R; decision: string } | null>(null)
  return (
    <div className="stack">
      <PageHeader title="Leave requests" subtitle="Approvals lock the employee's balance so concurrent decisions can never exceed the entitlement. Employees are notified in-app and by email." />
      <Panel title={<Tabs value={status} onChange={setStatus} items={[{ value: 'pending', label: 'Awaiting decision' }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }, { value: 'cancelled', label: 'Cancelled' }, { value: '', label: 'All' }]} />} flush>
        <DataTable rows={requests.data} loading={requests.isLoading} error={requests.error} rowKey={(row) => row.id} empty="No requests in this state." columns={[
          { key: 'employee', header: 'Employee', render: (row) => <><strong>{row.employee_name}</strong><span className="sub">{row.department}</span></> },
          { key: 'kind', header: 'Type', render: (row) => label(row.kind) },
          { key: 'dates', header: 'Dates', render: (row) => <>{date(row.starts_on)} → {date(row.ends_on)}<span className="sub">{row.days} working day(s)</span></> },
          { key: 'reason', header: 'Reason', render: (row) => row.reason || <span className="muted">—</span> },
          { key: 'created_at', header: 'Requested', render: (row) => dateTime(row.created_at) },
          { key: 'status', header: 'Status', render: (row) => <><Badge status={row.status} />{row.decision_note && <span className="sub">{row.decision_note}</span>}</> },
          { key: 'actions', header: '', align: 'right', render: (row) => row.status === 'pending' && can('hr:write') && (
            <div className="row" style={{ justifyContent: 'flex-end' }}>
              <Button small icon={Check} onClick={() => setDeciding({ row, decision: 'approved' })}>Approve</Button>
              <Button small variant="ghost" icon={X} onClick={() => setDeciding({ row, decision: 'rejected' })}>Reject</Button>
            </div>) },
        ]} />
      </Panel>
      {deciding && <LeaveDecision {...deciding} onClose={() => setDeciding(null)} />}
    </div>
  )
}

function LeaveDecision({ row, decision, onClose }: { row: R; decision: string; onClose: () => void }) {
  const [note, setNote] = useState('')
  const save = useAction(() => post(`${H}/leave/${row.id}/decision`, { decision, note }), { invalidate: [`${H}/leave`, `${H}/dashboard`, `${H}/notifications`], success: `Leave ${decision} · ${row.employee_name} notified`, onSuccess: onClose })
  return (
    <Modal open title={`${decision === 'approved' ? 'Approve' : 'Reject'} leave for ${row.employee_name}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={decision === 'approved' ? 'primary' : 'danger'} busy={save.isPending} disabled={decision === 'rejected' && note.trim().length < 3} onClick={() => save.mutate()}>{decision === 'approved' ? 'Approve' : 'Reject'}</Button></>}>
      <p>{label(row.kind)} leave · {date(row.starts_on)} → {date(row.ends_on)} · {row.days} working day(s)</p>
      <Field label={decision === 'approved' ? 'Note to employee (optional)' : 'Reason for rejection'}><Textarea value={note} onChange={(event) => setNote(event.target.value)} /></Field>
    </Modal>
  )
}

/* ---------------- Performance ---------------- */
export function Reviews() {
  const { can } = useAuth()
  const reviews = useGet<R[]>(`${H}/reviews`)
  const periods = [...new Set((reviews.data ?? []).map((row) => row.period))]
  const [period, setPeriod] = useState('')
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<R | null>(null)
  const shown = (reviews.data ?? []).filter((row) => !period || row.period === period)
  const done = shown.filter((row) => row.status === 'completed')
  const average = done.length ? done.reduce((sum, row) => sum + row.rating, 0) / done.length : null
  return (
    <div className="stack">
      <PageHeader title="Performance reviews" subtitle={`Goals, ratings (1–5) and reviewer comments per review period.${average ? ` Average in view: ${average.toFixed(2)} / 5 across ${done.length} completed review(s).` : ''}`}
        actions={can('hr:write') && <Button icon={Plus} onClick={() => setCreating(true)}>Start review</Button>} />
      <Panel title={<Tabs value={period} onChange={setPeriod} items={[{ value: '', label: 'All periods' }, ...periods.map((value) => ({ value, label: value }))]} />} flush>
        <DataTable rows={shown} loading={reviews.isLoading} error={reviews.error} rowKey={(row) => row.id} onRowClick={can('hr:write') ? (row) => row.status === 'draft' && setEditing(row) : undefined} columns={[
          { key: 'employee', header: 'Employee', render: (row) => <><strong>{row.employee_name}</strong><span className="sub">{row.department}</span></> },
          { key: 'period', header: 'Period' },
          { key: 'goals', header: 'Goals', render: (row) => <span className="small">{row.goals}</span> },
          { key: 'rating', header: 'Rating', render: (row) => <Stars rating={row.rating} /> },
          { key: 'reviewer_name', header: 'Reviewer' },
          { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
        ]} />
      </Panel>
      {creating && <ReviewForm onClose={() => setCreating(false)} />}
      {editing && <CompleteReview review={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ReviewForm({ onClose }: { onClose: () => void }) {
  const employees = useEmployees()
  const year = new Date().getFullYear()
  const form = useForm({ employee_id: '', period: `${year}-H2`, goals: '' })
  const save = useAction(() => post(`${H}/reviews`, form.values), { invalidate: [`${H}/reviews`, `${H}/dashboard`], success: 'Review started', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Start a performance review" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Create draft</Button></>}>
      <div className="form-grid">
        <Field label="Employee" wide error={errors.employee_id}><Select {...form.bind('employee_id')} options={employees} placeholder="Choose" /></Field>
        <Field label="Period" error={errors.period}><Select {...form.bind('period')} options={[`${year}-H1`, `${year}-H2`, `${year}-Q3`, `${year}-Q4`].map((value) => ({ value, label: value }))} /></Field>
        <Field label="Objectives" wide error={errors.goals}><Textarea {...form.bind('goals')} /></Field>
      </div>
    </Modal>
  )
}

function CompleteReview({ review, onClose }: { review: R; onClose: () => void }) {
  const [rating, setRating] = useState<number>(review.rating ?? 0)
  const [comments, setComments] = useState(review.comments ?? '')
  const save = useAction((status: string) => patch(`${H}/reviews/${review.id}`, { rating: rating || null, comments, ...(status === 'completed' ? { status } : {}) }),
    { invalidate: [`${H}/reviews`, `${H}/dashboard`], success: 'Review saved', onSuccess: onClose })
  return (
    <Modal open title={`Review · ${review.employee_name} · ${review.period}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={() => save.mutate('draft')} busy={save.isPending}>Save draft</Button><Button icon={Star} disabled={!rating} busy={save.isPending} onClick={() => save.mutate('completed')}>Complete review</Button></>}>
      <p className="small muted">Objectives: {review.goals}</p>
      <div className="field"><span className="field-label">Rating</span>
        <div className="tabs" role="radiogroup" aria-label="Rating">{[1, 2, 3, 4, 5].map((value) => (
          <button key={value} type="button" role="radio" aria-checked={rating === value} className={rating === value ? 'active' : ''} onClick={() => setRating(value)}>{value} ★</button>
        ))}</div>
        <span className="field-hint">1 unsatisfactory · 3 meets expectations · 5 outstanding</span>
      </div>
      <Field label="Comments"><Textarea value={comments} onChange={(event) => setComments(event.target.value)} /></Field>
    </Modal>
  )
}

/* ---------------- Assets & inventory ---------------- */
export function Assets() {
  const { can } = useAuth()
  const [tab, setTab] = useState<'assets' | 'inventory'>('assets')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const assets = useGet<R[]>(`${H}/assets?status=${status}&q=${encodeURIComponent(q)}`)
  const items = useGet<R[]>(`${H}/inventory`)
  const [dialog, setDialog] = useState<{ kind: string; row?: R } | null>(null)
  const writer = can('hr:write')
  const setAssetStatus = useAction(({ id, value }: { id: string; value: string }) => post(`${H}/assets/${id}/status`, { status: value }), { invalidate: [`${H}/assets`, `${H}/dashboard`], success: 'Asset updated' })
  return (
    <div className="stack">
      <PageHeader title="Assets & inventory" subtitle="Track equipment custody and consumable stock. Stock can never go negative and low levels notify HR."
        actions={writer && (tab === 'assets' ? <Button icon={Plus} onClick={() => setDialog({ kind: 'asset' })}>Register asset</Button> : <Button icon={PackagePlus} onClick={() => setDialog({ kind: 'item' })}>New stock item</Button>)} />
      <Panel title={<Tabs value={tab} onChange={setTab} items={[{ value: 'assets', label: 'Equipment', count: assets.data?.length }, { value: 'inventory', label: 'Consumables', count: items.data?.length }]} />}
        actions={tab === 'assets' && <><Select aria-label="Status" value={status} onChange={(event) => setStatus(event.target.value)} options={['available', 'assigned', 'maintenance', 'retired'].map((value) => ({ value, label: label(value) }))} placeholder="All statuses" />
          <SearchBox value={q} onChange={setQ} placeholder="Tag, name or serial" /></>} flush>
        {tab === 'assets' ? (
          <DataTable rows={assets.data} loading={assets.isLoading} error={assets.error} rowKey={(row) => row.id} columns={[
            { key: 'tag', header: 'Tag', mono: true },
            { key: 'name', header: 'Asset', render: (row) => <><strong>{row.name}</strong><span className="sub">{label(row.category)} · {row.serial}</span></> },
            { key: 'location', header: 'Location' },
            { key: 'condition', header: 'Condition', render: (row) => <Badge status={row.condition} /> },
            { key: 'assignee', header: 'Custodian', render: (row) => row.assignee ?? <span className="muted">—</span> },
            { key: 'value', header: 'Value', align: 'right', mono: true, render: (row) => money(row.value) },
            { key: 'status', header: 'Status', render: (row) => <Badge status={row.status} /> },
            { key: 'actions', header: '', align: 'right', render: (row) => (
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <Button small variant="ghost" icon={History} aria-label={`History of ${row.tag}`} onClick={() => setDialog({ kind: 'history', row })} />
                {writer && row.status === 'available' && <Button small variant="secondary" icon={UserCheck} onClick={() => setDialog({ kind: 'assign', row })}>Assign</Button>}
                {writer && row.status === 'assigned' && <Button small variant="secondary" icon={Undo2} onClick={() => setDialog({ kind: 'return', row })}>Return</Button>}
                {writer && row.status === 'available' && <Button small variant="ghost" icon={Wrench} onClick={() => setAssetStatus.mutate({ id: row.id, value: 'maintenance' })} aria-label="Send to maintenance" />}
                {writer && row.status === 'maintenance' && <Button small variant="ghost" onClick={() => setAssetStatus.mutate({ id: row.id, value: 'available' })}>Repaired</Button>}
              </div>) },
          ]} />
        ) : (
          <DataTable rows={items.data} loading={items.isLoading} error={items.error} rowKey={(row) => row.id} columns={[
            { key: 'sku', header: 'SKU', mono: true },
            { key: 'name', header: 'Item', render: (row) => <strong>{row.name}</strong> },
            { key: 'quantity', header: 'In stock', align: 'right', render: (row) => <span className={`mono ${row.low ? 'score-fail' : ''}`}>{row.quantity} {row.unit}</span> },
            { key: 'reorder_level', header: 'Reorder at', align: 'right', mono: true },
            { key: 'low', header: 'Level', render: (row) => <Badge status={row.low ? 'issue' : 'ok'}>{row.low ? 'Reorder' : 'OK'}</Badge> },
            { key: 'actions', header: '', align: 'right', render: (row) => (
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <Button small variant="ghost" icon={History} aria-label={`Movements of ${row.name}`} onClick={() => setDialog({ kind: 'movements', row })} />
                {writer && <Button small variant="secondary" icon={ArrowDownUp} onClick={() => setDialog({ kind: 'move', row })}>Adjust</Button>}
              </div>) },
          ]} />
        )}
      </Panel>
      {dialog?.kind === 'asset' && <AssetForm onClose={() => setDialog(null)} />}
      {dialog?.kind === 'item' && <ItemForm onClose={() => setDialog(null)} />}
      {dialog?.kind === 'assign' && <AssignForm asset={dialog.row!} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'return' && <ReturnForm asset={dialog.row!} onClose={() => setDialog(null)} />}
      {dialog?.kind === 'move' && <MovementForm item={dialog.row!} onClose={() => setDialog(null)} />}
      {(dialog?.kind === 'history' || dialog?.kind === 'movements') && <HistoryModal kind={dialog.kind} row={dialog.row!} onClose={() => setDialog(null)} />}
    </div>
  )
}

function AssetForm({ onClose }: { onClose: () => void }) {
  const form = useForm({ tag: '', name: '', category: 'laptop', serial: '', location: '', purchased_on: '', value: '' })
  const save = useAction(() => post(`${H}/assets`, { ...form.values, value: Number(form.values.value || 0) }), { invalidate: [`${H}/assets`, `${H}/dashboard`], success: 'Asset registered', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="Register asset" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Register</Button></>}>
      <div className="form-grid">
        <Field label="Asset tag" error={errors.tag}><Input {...form.bind('tag')} placeholder="ICT-LPT-020" /></Field>
        <Field label="Category"><Select {...form.bind('category')} options={['laptop', 'desktop', 'projector', 'printer', 'vehicle', 'furniture', 'network', 'other'].map((value) => ({ value, label: label(value) }))} /></Field>
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Serial number"><Input {...form.bind('serial')} /></Field>
        <Field label="Location" error={errors.location}><Input {...form.bind('location')} /></Field>
        <Field label="Purchase date" error={errors.purchased_on}><Input type="date" {...form.bind('purchased_on')} /></Field>
        <Field label="Value (FCFA)" error={errors.value}><Input type="number" min={0} {...form.bind('value')} /></Field>
      </div>
    </Modal>
  )
}

function ItemForm({ onClose }: { onClose: () => void }) {
  const form = useForm({ sku: '', name: '', unit: 'units', quantity: '0', reorder_level: '0' })
  const save = useAction(() => post(`${H}/inventory`, { ...form.values, quantity: Number(form.values.quantity), reorder_level: Number(form.values.reorder_level) }), { invalidate: [`${H}/inventory`], success: 'Stock item created', onSuccess: onClose })
  const errors = fieldErrors(save.error)
  return (
    <Modal open title="New consumable" onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Create</Button></>}>
      <div className="form-grid">
        <Field label="SKU" error={errors.sku}><Input {...form.bind('sku')} /></Field>
        <Field label="Unit"><Input {...form.bind('unit')} /></Field>
        <Field label="Name" wide error={errors.name}><Input {...form.bind('name')} /></Field>
        <Field label="Opening quantity"><Input type="number" min={0} {...form.bind('quantity')} /></Field>
        <Field label="Reorder level"><Input type="number" min={0} {...form.bind('reorder_level')} /></Field>
      </div>
    </Modal>
  )
}

function AssignForm({ asset, onClose }: { asset: R; onClose: () => void }) {
  const employees = useEmployees()
  const [employee, setEmployee] = useState('')
  const [note, setNote] = useState('')
  const save = useAction(() => post(`${H}/assets/${asset.id}/assign`, { employee_id: employee, note }), { invalidate: [`${H}/assets`, `${H}/dashboard`], success: `${asset.tag} assigned`, onSuccess: onClose })
  return (
    <Modal open title={`Assign ${asset.tag}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={!employee} onClick={() => save.mutate()}>Assign</Button></>}>
      <Field label="Employee"><Select value={employee} onChange={(event) => setEmployee(event.target.value)} options={employees} placeholder="Choose" /></Field>
      <Field label="Handover note"><Input value={note} onChange={(event) => setNote(event.target.value)} /></Field>
    </Modal>
  )
}

function ReturnForm({ asset, onClose }: { asset: R; onClose: () => void }) {
  const [condition, setCondition] = useState('good')
  const save = useAction(() => post(`${H}/assets/${asset.id}/return`, { condition }), { invalidate: [`${H}/assets`, `${H}/dashboard`], success: `${asset.tag} returned`, onSuccess: onClose })
  return (
    <Modal open title={`Return ${asset.tag} from ${asset.assignee}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} onClick={() => save.mutate()}>Record return</Button></>}>
      <Field label="Condition on return" hint="Poor condition sends the asset to maintenance."><Select value={condition} onChange={(event) => setCondition(event.target.value)} options={['good', 'fair', 'poor'].map((value) => ({ value, label: label(value) }))} /></Field>
    </Modal>
  )
}

function MovementForm({ item, onClose }: { item: R; onClose: () => void }) {
  const [direction, setDirection] = useState<'in' | 'out'>('out')
  const [quantity, setQuantity] = useState('')
  const [reason, setReason] = useState('')
  const save = useAction(() => post(`${H}/inventory/${item.id}/movements`, { delta: (direction === 'in' ? 1 : -1) * Number(quantity), reason }),
    { invalidate: [`${H}/inventory`, `${H}/dashboard`, `${H}/notifications`], success: 'Stock updated', onSuccess: onClose })
  return (
    <Modal open title={`Adjust stock · ${item.name}`} onClose={onClose} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button busy={save.isPending} disabled={!quantity || reason.length < 3} onClick={() => save.mutate()}>Record movement</Button></>}>
      <p className="muted">Currently {item.quantity} {item.unit} in stock.</p>
      <Tabs value={direction} onChange={setDirection} items={[{ value: 'out', label: 'Issue (remove)' }, { value: 'in', label: 'Receive (add)' }]} />
      <div className="form-grid">
        <Field label={`Quantity (${item.unit})`}><Input type="number" min={1} value={quantity} onChange={(event) => setQuantity(event.target.value)} /></Field>
        <Field label="Reason"><Input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={direction === 'in' ? 'Purchase order PO-…' : 'Issued to …'} /></Field>
      </div>
    </Modal>
  )
}

function HistoryModal({ kind, row, onClose }: { kind: string; row: R; onClose: () => void }) {
  const history = useGet<R[]>(kind === 'history' ? `${H}/assets/${row.id}/history` : `${H}/inventory/${row.id}/movements`)
  return (
    <Modal open size="lg" title={kind === 'history' ? `Custody history · ${row.tag}` : `Stock movements · ${row.name}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {kind === 'history' ? (
        <DataTable rows={history.data} loading={history.isLoading} rowKey={(item) => item.id} empty="Never assigned." columns={[
          { key: 'employee_name', header: 'Employee' }, { key: 'assigned_at', header: 'Assigned', render: (item) => dateTime(item.assigned_at) },
          { key: 'returned_at', header: 'Returned', render: (item) => item.returned_at ? dateTime(item.returned_at) : <Badge status="assigned">Still assigned</Badge> }, { key: 'note', header: 'Note' },
        ]} />
      ) : (
        <DataTable rows={history.data} loading={history.isLoading} rowKey={(item) => item.id} columns={[
          { key: 'created_at', header: 'When', render: (item) => dateTime(item.created_at) },
          { key: 'delta', header: 'Change', align: 'right', render: (item) => <span className={`mono ${item.delta < 0 ? 'score-fail' : ''}`}>{item.delta > 0 ? `+${item.delta}` : item.delta}</span> },
          { key: 'balance_after', header: 'Balance', align: 'right', mono: true }, { key: 'reason', header: 'Reason' },
        ]} />
      )}
      <p className="small muted">{kind === 'history' ? `Purchased ${date(row.purchased_on)}.` : 'Movements are append-only; corrections are recorded as new movements.'}</p>
    </Modal>
  )
}
