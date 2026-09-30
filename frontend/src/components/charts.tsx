import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { compact } from '../lib/format'

export const PALETTE = ['#00695F', '#B44C3B', '#2864A0', '#C28A1E', '#5E7F3A', '#6D5A8C', '#3F8F86']
const axis = { fontSize: 12, fill: '#5b6b6e' }
const tooltipStyle = { borderRadius: 8, border: '1px solid #d7e0dd', fontSize: 13 }

type Series = { key: string; label: string; color?: string }

export function Bars({ data, x, series, height = 260, money, horizontal, format }: {
  data: Record<string, unknown>[]; x: string; series: Series[]; height?: number; money?: boolean; horizontal?: boolean; format?: (value: number) => string
}) {
  const show = format ?? ((value: number) => (money ? `${compact(value)} FCFA` : String(value)))
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 12, right: 18, left: horizontal ? 8 : 0, bottom: 4 }}>
          <CartesianGrid stroke="#e7edeb" vertical={!!horizontal} horizontal={!horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" tick={axis} tickFormatter={(value) => (money ? compact(Number(value)) : String(value))} />
              <YAxis type="category" dataKey={x} tick={axis} width={130} />
            </>
          ) : (
            <>
              <XAxis dataKey={x} tick={axis} tickLine={false} />
              <YAxis tick={axis} tickFormatter={(value) => (money ? compact(Number(value)) : String(value))} width={48} allowDecimals={false} />
            </>
          )}
          <Tooltip contentStyle={tooltipStyle} formatter={(value) => show(Number(value))} cursor={{ fill: 'rgba(0,105,95,0.06)' }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12.5 }} iconType="square" />}
          {series.map((item, index) => (
            <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color ?? PALETTE[index]} radius={horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0]} maxBarSize={34} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Lines({ data, x, series, height = 240, format }: { data: Record<string, unknown>[]; x: string; series: Series[]; height?: number; format?: (value: number) => string }) {
  return (
    <div className="chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 18, left: 0, bottom: 4 }}>
          <CartesianGrid stroke="#e7edeb" vertical={false} />
          <XAxis dataKey={x} tick={axis} tickLine={false} />
          <YAxis tick={axis} width={40} allowDecimals={false} />
          <Tooltip contentStyle={tooltipStyle} formatter={(value) => (format ? format(Number(value)) : String(value))} />
          {series.map((item, index) => (
            <Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color ?? PALETTE[index]} strokeWidth={2.2} dot={{ r: 3 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function Donut({ data, height = 230, format }: { data: { name: string; value: number }[]; height?: number; format?: (value: number) => string }) {
  const total = data.reduce((sum, item) => sum + item.value, 0)
  return (
    <div>
      <div className="chart" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="86%" paddingAngle={2} stroke="none">
              {data.map((item, index) => <Cell key={item.name} fill={PALETTE[index % PALETTE.length]} />)}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} formatter={(value) => (format ? format(Number(value)) : String(value))} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="legend">
        {data.map((item, index) => (
          <span key={item.name}><i style={{ background: PALETTE[index % PALETTE.length] }} />{item.name} · {total ? Math.round((item.value / total) * 100) : 0}%</span>
        ))}
      </div>
    </div>
  )
}
