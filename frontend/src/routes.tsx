import { Link, Navigate, Route, Routes } from "react-router";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import AuthenticatedLayout from "@/layouts/authenticated-layout";
import Login from "@/pages/login/login";
import Workspaces from "@/pages/workspace/workspace";
import WorkspaceDetail from "@/pages/workspace/workspace-detail";
import KnowledgeBaseDetail from "@/pages/knowledge-base/knowledge-base";

export default function AppRoutes() {
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
