import { NavLink, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="layout">
      <nav className="sidebar">
        <div className="brand">Die Casting<br />Lead Hunter</div>
        <NavLink to="/leads" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Leads
        </NavLink>
        <NavLink to="/drafts" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Outreach Drafts
        </NavLink>
        <NavLink to="/discovery" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Discovery
        </NavLink>
        <NavLink to="/discovery/jobs" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Discovery Jobs
        </NavLink>
        <NavLink to="/discovery/automation" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Automation
        </NavLink>
        <NavLink to="/followups" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Follow-up Automation
        </NavLink>
        <NavLink to="/inbox" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Reply Inbox
        </NavLink>
        <NavLink to="/quality" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Quality & Ranking
        </NavLink>
        <NavLink to="/authority" className={({ isActive }) => (isActive ? "nav active" : "nav")}>
          Authority Engine
        </NavLink>
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
