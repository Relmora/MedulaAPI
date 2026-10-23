import { Navigate, Route, Routes, Link } from "react-router";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import AuthenticatedLayout from "@/layouts/authenticated-layout";
import Login from "@/pages/Login/login";
import Workspaces from "@/pages/Workspace/workspace";
import WorkspaceDetail from "@/pages/Workspace/workspace-detail";
import KnowledgeBaseDetail from "@/pages/Knowledge-base/knowledge-base";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<AuthenticatedLayout />}>
        <Route index element={<Navigate to="/workspaces" replace />} />
        <Route path="/workspaces" element={<Workspaces />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceDetail />} />
        <Route
          path="/workspaces/:workspaceId/knowledge-bases/:knowledgeBaseId"
          element={<KnowledgeBaseDetail />}
        />
        <Route
          path="*"
          element={
            <Card>
              <CardHeader>
                <CardTitle>Page not found</CardTitle>
              </CardHeader>
              <CardContent>
                <Link to="/workspaces">Go to workspaces</Link>
              </CardContent>
            </Card>
          }
        />
      </Route>
    </Routes>
  );
}
