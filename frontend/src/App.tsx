import { NavLink, Outlet } from 'react-router-dom'
import './App.css'

function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-kicker">Task Console</span>
          <h1>AI Code Review Sentinel</h1>
          <p>面向 Java / Python 协同链路的代码审查控制台</p>
        </div>
        <nav className="app-nav" aria-label="主导航">
          <NavLink end className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} to="/">
            提交审查
          </NavLink>
          <NavLink className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} to="/tasks">
            任务查询
          </NavLink>
          <NavLink className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} to="/business-risk/source">
            业务风险
          </NavLink>
          <NavLink className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`} to="/feedback">
            反馈统计
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}

export default App
