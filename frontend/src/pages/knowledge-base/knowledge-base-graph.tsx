import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import { Network } from "lucide-react";
import { Link, useParams } from "react-router";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getKnowledgeBaseGraph,
  type KnowledgeBaseGraph,
} from "@/services/knowledge-base";
import { getErrorMessage } from "@/services/http";

type EntityNodeData = {
  label: string;
  entityType: string;
};

function flowElements(graph: KnowledgeBaseGraph): {
  nodes: Node<EntityNodeData>[];
  edges: Edge[];
} {
  const radius = Math.max(180, graph.nodes.length * 24);
  const nodes = graph.nodes.map((node, index) => {
    const angle = (index / Math.max(graph.nodes.length, 1)) * Math.PI * 2;
    return {
      id: node.id,
      position: {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      },
      data: { label: node.name, entityType: node.entity_type },
      className:
        "!rounded-xl !border-border !bg-card !px-3 !py-2 !text-card-foreground !shadow-sm",
    };
  });
  const edges = graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.predicate,
    type: "smoothstep",
  }));
  return { nodes, edges };
}

function GraphCanvas({
  initialNodes,
  initialEdges,
  onSelect,
}: {
  initialNodes: Node<EntityNodeData>[];
  initialEdges: Edge[];
  onSelect: (nodeId: string | null) => void;
}) {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      fitView
      minZoom={0.2}
      maxZoom={2}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) => onSelect(node.id)}
      onPaneClick={() => onSelect(null)}
      nodesDraggable
      aria-label="Document entity graph"
    >
      <Background />
      <MiniMap pannable zoomable nodeColor="var(--muted-foreground)" />
      <Controls />
    </ReactFlow>
  );
}

export default function KnowledgeBaseGraphPage() {
  const { workspaceId = "", knowledgeBaseId = "" } = useParams();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["knowledge-base-graph", workspaceId, knowledgeBaseId],
    queryFn: ({ signal }) =>
      getKnowledgeBaseGraph(workspaceId, knowledgeBaseId, signal),
  });
  const elements = useMemo(
    () => (query.data ? flowElements(query.data) : { nodes: [], edges: [] }),
    [query.data],
  );
  const selectedEntity = query.data?.nodes.find(
    (node) => node.id === selectedId,
  );
  const relationships = useMemo(() => {
    if (!query.data || !selectedId) return [];
    const names = new Map(query.data.nodes.map((node) => [node.id, node.name]));
    return query.data.edges
      .filter(
        (edge) => edge.source === selectedId || edge.target === selectedId,
      )
      .map((edge) => ({
        id: edge.id,
        predicate: edge.predicate,
        direction: edge.source === selectedId ? "to" : "from",
        entityName:
          names.get(
            edge.source === selectedId ? edge.target : edge.source,
          ) ?? "Unknown entity",
      }));
  }, [query.data, selectedId]);

  const backPath = `/workspaces/${workspaceId}/knowledge-bases/${knowledgeBaseId}`;

  return (
    <div className="space-y-4">
      <Button
        variant="link"
        nativeButton={false}
        render={<Link to={backPath} />}
      >
        Back to knowledge base
      </Button>
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold">
          <Network className="size-6" />
          Knowledge base graph
        </h1>
        <p className="text-sm text-muted-foreground">
          Explore relationships across every processed document in this
          knowledge base.
        </p>
      </div>

      {query.isPending ? (
        <Skeleton className="h-[65vh] min-h-96" aria-label="Loading graph" />
      ) : query.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Could not load graph</AlertTitle>
          <AlertDescription className="space-y-3">
            <p>{getErrorMessage(query.error)}</p>
            <Button variant="outline" onClick={() => void query.refetch()}>
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      ) : query.data.nodes.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>No entities found</CardTitle>
            <CardDescription>
              No processed documents in this knowledge base have produced graph
              entities or relationships yet.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <Card className="overflow-hidden">
            <CardContent className="h-[65vh] min-h-96 p-0">
              <GraphCanvas
                initialNodes={elements.nodes}
                initialEdges={elements.edges}
                onSelect={setSelectedId}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Entity details</CardTitle>
              <CardDescription>
                Select a node to inspect its relationships.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {selectedEntity ? (
                <div className="space-y-5">
                  <div>
                    <p className="text-lg font-medium">{selectedEntity.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {selectedEntity.entity_type}
                    </p>
                  </div>
                  <div className="space-y-2">
                    <h2 className="text-sm font-medium">
                      Relationships ({relationships.length})
                    </h2>
                    {relationships.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        This entity has no connected relationships.
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {relationships.map((relationship) => (
                          <li
                            key={relationship.id}
                            className="rounded-lg border p-3 text-sm"
                          >
                            <span className="font-medium">
                              {relationship.predicate}
                            </span>{" "}
                            <span className="text-muted-foreground">
                              {relationship.direction} {relationship.entityName}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No entity selected.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
