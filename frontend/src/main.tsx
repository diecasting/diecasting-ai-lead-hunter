import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import LeadsPage from "./pages/LeadsPage";
import LeadDetailPage from "./pages/LeadDetailPage";
import DraftsPage from "./pages/DraftsPage";
import QualityPage from "./pages/QualityPage";
import DiscoveryPage from "./pages/DiscoveryPage";
import DiscoveryJobsPage from "./pages/DiscoveryJobsPage";
import DiscoveryAutomationPage from "./pages/DiscoveryAutomationPage";
import FollowupAutomationPage from "./pages/FollowupAutomationPage";
import InboxPage from "./pages/InboxPage";
import AuthorityPage from "./pages/AuthorityPage";
import "./index.css";

const router = createHashRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <LeadsPage /> },
      { path: "leads", element: <LeadsPage /> },
      { path: "leads/:id", element: <LeadDetailPage /> },
      { path: "drafts", element: <DraftsPage /> },
      { path: "quality", element: <QualityPage /> },
      { path: "discovery", element: <DiscoveryPage /> },
      { path: "discovery/jobs", element: <DiscoveryJobsPage /> },
      { path: "discovery/automation", element: <DiscoveryAutomationPage /> },
      { path: "followups", element: <FollowupAutomationPage /> },
      { path: "inbox", element: <InboxPage /> },
      { path: "authority", element: <AuthorityPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
