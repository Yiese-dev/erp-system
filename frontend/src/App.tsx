import { lazy } from 'react'
import type { ComponentType } from 'react'
import { Route, Routes } from 'react-router-dom'
import AppShell, { Guard } from './components/AppShell'
import { BrandMark } from './components/Brand'
import { useAuth } from './lib/auth'
import Login from './pages/Login'

function page(loader: () => Promise<Record<string, unknown>>, name: string) {
  return lazy(() => loader().then((module) => ({ default: module[name] as ComponentType })))
}

const academic = () => import('./pages/academic/Catalogue')
const teaching = () => import('./pages/academic/Teaching')
const results = () => import('./pages/academic/Results')
const finance = () => import('./pages/finance/Finance')
const payments = () => import('./pages/finance/Payments')
const marketing = () => import('./pages/finance/Marketing')
const people = () => import('./pages/hr/People')
const payroll = () => import('./pages/hr/Payroll')
const presence = () => import('./pages/hr/Presence')
const operations = () => import('./pages/hr/Operations')
const admin = () => import('./pages/admin/Admin')

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Catalogue = page(academic, 'Catalogue')
const Offerings = page(academic, 'Offerings')
const Students = page(academic, 'Students')
const Gradebook = page(teaching, 'Gradebook')
const ClassAttendance = page(teaching, 'ClassAttendance')
const Exams = page(teaching, 'Exams')
const Appeals = page(results, 'Appeals')
const AtRisk = page(results, 'AtRisk')
const MyCourses = page(results, 'MyCourses')
const FinanceOverview = page(finance, 'FinanceOverview')
const Invoices = page(finance, 'Invoices')
const FeePlans = page(finance, 'FeePlans')
const Ledger = page(finance, 'Ledger')
const Pay = page(payments, 'Pay')
const Expenses = page(marketing, 'Expenses')
const Campaigns = page(marketing, 'Campaigns')
const Reports = page(marketing, 'Reports')
const HrOverview = page(people, 'HrOverview')
const Employees = page(people, 'Employees')
const Recruitment = page(people, 'Recruitment')
const Payroll = page(payroll, 'Payroll')
const Kiosk = page(presence, 'Kiosk')
const CheckIn = page(presence, 'CheckIn')
const MyHr = page(presence, 'MyHr')
const Leave = page(operations, 'Leave')
const Reviews = page(operations, 'Reviews')
const Assets = page(operations, 'Assets')
const Users = page(admin, 'Users')
const Tenants = page(admin, 'Tenants')
const System = page(admin, 'System')
const Account = page(admin, 'Account')

const TEACH = ['academic:write', 'academic:teach']
const ACADEMIC = [...TEACH, 'academic:self']

const routes: [string, ComponentType, string[]][] = [
  ['academic/catalogue', Catalogue, ['academic:write']],
  ['academic/offerings', Offerings, TEACH],
  ['academic/students', Students, ['academic:write']],
  ['academic/gradebook', Gradebook, TEACH],
  ['academic/attendance', ClassAttendance, TEACH],
  ['academic/exams', Exams, ACADEMIC],
  ['academic/appeals', Appeals, ACADEMIC],
  ['academic/risk', AtRisk, TEACH],
  ['academic/me', MyCourses, ['academic:self']],
  ['finance', FinanceOverview, ['finance:read']],
  ['finance/invoices', Invoices, ['finance:read']],
  ['finance/fee-plans', FeePlans, ['finance:read']],
  ['finance/ledger', Ledger, ['finance:read']],
  ['finance/pay', Pay, ['finance:self']],
  ['finance/expenses', Expenses, ['finance:read']],
  ['finance/campaigns', Campaigns, ['finance:read']],
  ['finance/reports', Reports, ['finance:read']],
  ['hr', HrOverview, ['hr:read']],
  ['hr/employees', Employees, ['hr:read']],
  ['hr/recruitment', Recruitment, ['hr:read']],
  ['hr/payroll', Payroll, ['hr:read']],
  ['hr/attendance', Kiosk, ['hr:write']],
  ['hr/check-in', CheckIn, ['hr:self']],
  ['hr/me', MyHr, ['hr:self']],
  ['hr/leave', Leave, ['hr:read']],
  ['hr/reviews', Reviews, ['hr:read']],
  ['hr/assets', Assets, ['hr:read']],
  ['admin/users', Users, ['users:manage']],
  ['admin/tenants', Tenants, ['platform:manage']],
  ['admin/system', System, ['users:manage', 'platform:manage']],
  ['account', Account, []],
]

function NotFound() {
  return <div className="panel"><div className="empty"><strong>Page not found</strong><span>Use the navigation to find what you need.</span></div></div>
}

export default function App() {
  const { status } = useAuth()
  if (status === 'loading') {
    return <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }} aria-busy="true"><BrandMark className="brand-mark spin" /></div>
  }
  if (status === 'anonymous') return <Login />
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        {routes.map(([path, Component, perms]) => (
          <Route key={path} path={path} element={<Guard perms={perms}><Component /></Guard>} />
        ))}
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
