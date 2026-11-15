// The data-path graph: where the values in a call came from. Untrusted nodes are red,
// trusted green; the offending argument's node pulses. Lazy-loaded (React Flow is big).
import { Graph, layout } from '@dagrejs/dagre'
import { Background, type Edge, type Node, ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import type { ProvenanceOut } from '../api/client.ts'

const WIDTH = 196
const HEIGHT = 44

function positioned(provenance: ProvenanceOut, offendingArg: string | null | undefined) {
  const graph = new Graph()
  graph.setGraph({ rankdir: 'LR', nodesep: 22, ranksep: 64 })
  graph.setDefaultEdgeLabel(() => ({}))
  for (const node of provenance.nodes) graph.setNode(node.id, { width: WIDTH, height: HEIGHT })
  for (const edge of provenance.edges) graph.setEdge(edge.source, edge.target)
  layout(graph)

  const untrustedIds = new Set(provenance.nodes.filter((n) => n.label.integrity === 'untrusted').map((n) => n.id))
  const nodes: Node[] = provenance.nodes.map((node) => {
    const point = graph.node(node.id)
    const untrusted = untrustedIds.has(node.id)
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
        fontSize: 11.5,
        fontFamily: 'Geist Mono, ui-monospace, monospace',
        borderRadius: 14,
        color: sink ? '#ffffff' : '#0c0d12',
        background: sink ? '#0c0d12' : untrusted ? '#fff1f2' : '#ecfdf5',
        border: `${offending ? 2.5 : 1}px solid ${sink ? '#0c0d12' : untrusted ? '#ff5a64' : '#22c58b'}`,
        boxShadow: offending ? '0 0 0 6px rgb(255 90 100 / 0.15)' : '0 1px 2px rgb(16 18 27 / 0.06)',
      },
    }
  })
  const edges: Edge[] = provenance.edges.map((edge) => ({
    id: `${edge.source}->${edge.target}`,
    source: edge.source,
    target: edge.target,
    animated: true,
    style: { stroke: untrustedIds.has(edge.source) ? '#ff5a64' : '#8a8fa2', strokeWidth: 1.6 },
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
    <div className="h-80 w-full overflow-hidden rounded-3xl bg-surface-2">
      <ReactFlow nodes={nodes} edges={edges} fitView proOptions={{ hideAttribution: true }} colorMode="light">
        <Background gap={18} size={1.2} color="#d3d6df" />
      </ReactFlow>
    </div>
  )
}
