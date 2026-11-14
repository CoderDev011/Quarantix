// The data-path graph: where the values in a call came from. Untrusted nodes are red,
// trusted green; the offending argument's node pulses. Lazy-loaded (React Flow is big).
import { Graph, layout } from '@dagrejs/dagre'
import { Background, type Edge, type Node, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import type { ProvenanceOut } from '../api/client.ts'

const WIDTH = 190
const HEIGHT = 46

function positioned(provenance: ProvenanceOut, offendingArg: string | null | undefined) {
  const graph = new Graph()
  graph.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 56 })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const node of provenance.nodes) graph.setNode(node.id, { width: WIDTH, height: HEIGHT })
  for (const edge of provenance.edges) graph.setEdge(edge.source, edge.target)
  layout(graph)

  const nodes: Node[] = provenance.nodes.map((node) => {
    const point = graph.node(node.id)
    const untrusted = node.label.integrity === 'untrusted'
    const offending = Boolean(offendingArg) && node.title.endsWith(`.${offendingArg}`)
    const sink = node.kind === 'sink'
    return {
      id: node.id,
      position: { x: point.x - WIDTH / 2, y: point.y - HEIGHT / 2 },
      data: { label: `${node.title}${untrusted ? '  ⚠' : ''}` },
      draggable: false,
      className: offending ? 'animate-pulse' : '',
      style: {
        width: WIDTH,
        fontSize: 11,
        borderRadius: 6,
        color: '#e2e8f0',
        background: sink ? '#1e293b' : untrusted ? '#450a0a' : '#052e16',
        border: `${offending ? 3 : 1}px solid ${sink ? '#94a3b8' : untrusted ? '#ef4444' : '#22c55e'}`,
      },
    }
  })
  const edges: Edge[] = provenance.edges.map((edge) => ({
    id: `${edge.source}->${edge.target}`,
    source: edge.source,
    target: edge.target,
    animated: true,
    style: { stroke: '#64748b' },
  }))
  return { nodes, edges }
}

export default function PathGraph({
  provenance,
  offendingArg,
}: {
  provenance: ProvenanceOut
  offendingArg?: string | null
}) {
  const { nodes, edges } = useMemo(() => positioned(provenance, offendingArg), [provenance, offendingArg])
  return (
    <div className="h-80 w-full rounded border border-slate-800 bg-slate-950">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }} colorMode="dark">
        <Background gap={18} color="#1e293b" />
      </ReactFlow>
    </div>
  )
}
