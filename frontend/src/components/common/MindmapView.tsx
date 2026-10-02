// ============================================================
// Academix AI — Mind Map (light theme, NotebookLM-style)
// Architecture: single wrapper div holds both SVG edges +
// HTML node divs. Imperative DOM transforms for drag.
// ============================================================
import React, {
  useState,
  useEffect,
  useCallback,
  useImperativeHandle,
  forwardRef,
  useRef,
  useMemo,
  useLayoutEffect,
} from 'react'
import { Maximize2, X, Plus, Minus, Maximize } from 'lucide-react'

// ──────────────────────────────────────────────────────────────
// Public types
// ──────────────────────────────────────────────────────────────
export interface MindmapNode {
  title: string
  description: string
  children?: MindmapNode[]
}
export interface MindmapViewHandle { openFullscreen: () => void }
interface MindmapViewProps {
  rootNode: MindmapNode
  hideInlineExpand?: boolean
}

// ──────────────────────────────────────────────────────────────
// Colour palette (light theme)
// ──────────────────────────────────────────────────────────────
const C = {
  bg:      '#f0f4ff',
  dot:     '#d1daf5',
  // node fills
  f0:      '#4285F4',   // root  — solid blue
  f1:      '#ffffff',   // L1    — white
  f2:      '#f4f7ff',   // leaf  — pale blue
  // borders
  b0:      '#2563eb',
  b1:      '#93b0f0',
  b2:      '#c2d0f8',
  // text
  t0:      '#ffffff',
  t1:      '#1e293b',
  t2:      '#334155',
  d0:      'rgba(255,255,255,0.78)',
  d1:      '#64748b',
  // connectors
  edge:    '#93b0f0',
  // badge
  badge:   '#4285F4',
  // controls
  ctrl:    '#ffffff',
  ctrlB:   '#dde3f0',
  ctrlT:   '#475569',
  ctrlH:   '#ebf0ff',
}

// ──────────────────────────────────────────────────────────────
// Layout constants
// ──────────────────────────────────────────────────────────────
const NW     = 180   // node width
const NH     = 58    // base node height
const H_GAP  = 80    // horizontal gap between levels
const V_GAP  = 18    // vertical gap between sibling subtrees
const PAD    = 48    // canvas padding

// ──────────────────────────────────────────────────────────────
// Internal layout node
// ──────────────────────────────────────────────────────────────
interface LN {
  id:       string        // stable path-based id
  data:     MindmapNode
  depth:    number
  x:        number        // LEFT edge of card
  y:        number        // TOP edge of card
  w:        number
  h:        number
  children: LN[]
  isCol:    boolean
}

// ──────────────────────────────────────────────────────────────
// Build tree — stable IDs from path so collapse state survives
// ──────────────────────────────────────────────────────────────
function buildTree(
  node:     MindmapNode,
  depth:    number,
  path:     string,
  colSet:   Set<string>,
): LN {
  const id    = path
  const isCol = colSet.has(id)
  const kids  = isCol
    ? []
    : (node.children ?? []).map((c, i) =>
        buildTree(c, depth + 1, `${path}/${i}`, colSet)
      )
  // height: base + extra for long title
  const titleLines = Math.ceil(node.title.length / 22)
  const h = NH + Math.max(0, titleLines - 1) * 16
  return { id, data: node, depth, x: 0, y: 0, w: NW, h, children: kids, isCol }
}

// Subtree height (used for layout)
function subH(n: LN): number {
  if (n.children.length === 0) return n.h
  const ch = n.children.reduce((s, c) => s + subH(c), 0)
  return Math.max(n.h, ch + (n.children.length - 1) * V_GAP)
}

// Assign x, y (top-left corner of each card)
function layout(n: LN, left: number, topOfSubtree: number): void {
  const sh  = subH(n)
  n.x       = left
  n.y       = topOfSubtree + (sh - n.h) / 2     // vertically centred in subtree
  if (n.children.length === 0) return
  const childLeft = left + n.w + H_GAP
  let   cy        = topOfSubtree
  for (const ch of n.children) {
    layout(ch, childLeft, cy)
    cy += subH(ch) + V_GAP
  }
}

// Collect all visible nodes and parent→child edges
function collect(n: LN, ns: LN[], es: [LN, LN][]): void {
  ns.push(n)
  for (const ch of n.children) {
    es.push([n, ch])
    collect(ch, ns, es)
  }
}

// Bounding box
function bbox(ns: LN[]) {
  if (!ns.length) return { x: 0, y: 0, w: 800, h: 500 }
  const minX = Math.min(...ns.map(n => n.x))
  const minY = Math.min(...ns.map(n => n.y))
  const maxX = Math.max(...ns.map(n => n.x + n.w))
  const maxY = Math.max(...ns.map(n => n.y + n.h))
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

// SVG cubic bezier: right-centre of source → left-centre of target
function edgePath(a: LN, b: LN): string {
  const x1 = a.x + a.w           // right edge centre
  const y1 = a.y + a.h / 2
  const x2 = b.x                 // left edge centre
  const y2 = b.y + b.h / 2
  const cx = (x1 + x2) / 2
  return `M${x1},${y1} C${cx},${y1} ${cx},${y2} ${x2},${y2}`
}

// ──────────────────────────────────────────────────────────────
// Ctrl button
// ──────────────────────────────────────────────────────────────
function Btn({ onClick, title, children }: {
  onClick: () => void; title: string; children: React.ReactNode
}) {
  const [h, sh] = useState(false)
  return (
    <button
      onClick={onClick} title={title}
      onMouseEnter={() => sh(true)} onMouseLeave={() => sh(false)}
      style={{
        width: 32, height: 32, borderRadius: 8,
        background: h ? C.ctrlH : C.ctrl,
        border: `1px solid ${C.ctrlB}`, color: C.ctrlT,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', transition: 'background 0.12s',
        boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
      }}
    >
      {children}
    </button>
  )
}

// ──────────────────────────────────────────────────────────────
// TreeCanvas
// ──────────────────────────────────────────────────────────────
interface CanvasProps {
  rootNode:      MindmapNode
  isFullscreen:  boolean
  allowWheelZoom: boolean
  onClose?:      () => void
}

function TreeCanvas({ rootNode, isFullscreen, allowWheelZoom, onClose }: CanvasProps) {
  const outerRef  = useRef<HTMLDivElement>(null)   // clipping container
  const innerRef  = useRef<HTMLDivElement>(null)   // transformed wrapper (holds SVG + nodes)

  // pan/zoom stored in refs — updated imperatively for zero-lag drag
  const tx    = useRef(PAD)
  const ty    = useRef(PAD)
  const sc    = useRef(1)
  const applyTransform = useCallback(() => {
    if (innerRef.current) {
      innerRef.current.style.transform =
        `translate(${tx.current}px,${ty.current}px) scale(${sc.current})`
    }
  }, [])

  // collapsed node ids
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  // build & layout tree
  const { tree, nodes, edges } = useMemo(() => {
    const t = buildTree(rootNode, 0, 'r', collapsed)
    layout(t, PAD, PAD)
    const ns: LN[] = []; const es: [LN, LN][] = []
    collect(t, ns, es)
    return { tree: t, nodes: ns, edges: es }
  }, [rootNode, collapsed])

  // canvas size (SVG needs explicit dimensions)
  const bb     = bbox(nodes)
  const svgW   = bb.x + bb.w + PAD * 2
  const svgH   = bb.y + bb.h + PAD * 2

  // ── fit to screen ──────────────────────────────────────────
  const fitToScreen = useCallback(() => {
    const outer = outerRef.current
    if (!outer || !nodes.length) return
    const cw  = outer.clientWidth  || 800
    const ch  = outer.clientHeight || 480
    const pad = 40
    const b   = bbox(nodes)
    const ns  = Math.min(1.0, Math.min((cw - pad*2) / b.w, (ch - pad*2) / b.h))
    tx.current = (cw - b.w * ns) / 2 - b.x * ns
    ty.current = (ch - b.h * ns) / 2 - b.y * ns
    sc.current = ns
    applyTransform()
  }, [nodes, applyTransform])

  // initial fit
  useLayoutEffect(() => { fitToScreen() }, [rootNode])   // eslint-disable-line
  // fit after collapse/expand
  useEffect(()        => { fitToScreen() }, [collapsed])  // eslint-disable-line

  // ── drag — pure imperative, no React state ─────────────────
  useEffect(() => {
    let dragging = false
    let sx = 0, sy = 0, stx = 0, sty = 0

    const onDown = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('[data-mm]')) return
      dragging = true
      sx = e.clientX; sy = e.clientY
      stx = tx.current; sty = ty.current
      e.preventDefault()
    }
    const onMove = (e: MouseEvent) => {
      if (!dragging) return
      tx.current = stx + e.clientX - sx
      ty.current = sty + e.clientY - sy
      applyTransform()
    }
    const onUp   = () => { dragging = false }

    const outer = outerRef.current
    if (!outer) return
    outer.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup',   onUp)
    return () => {
      outer.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup',   onUp)
    }
  }, [applyTransform])

  // ── wheel zoom ────────────────────────────────────────────
  useEffect(() => {
    if (!allowWheelZoom) return
    const outer = outerRef.current
    if (!outer) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      // zoom towards mouse position
      const rect  = outer.getBoundingClientRect()
      const mx    = e.clientX - rect.left
      const my    = e.clientY - rect.top
      const delta = e.deltaY > 0 ? 0.9 : 1.1
      const ns    = Math.min(3, Math.max(0.15, sc.current * delta))
      tx.current  = mx - (mx - tx.current) * (ns / sc.current)
      ty.current  = my - (my - ty.current) * (ns / sc.current)
      sc.current  = ns
      applyTransform()
    }
    outer.addEventListener('wheel', onWheel, { passive: false })
    return () => outer.removeEventListener('wheel', onWheel)
  }, [allowWheelZoom, applyTransform])

  // ── zoom buttons (always work) ────────────────────────────
  const zoom = useCallback((factor: number) => {
    const outer = outerRef.current
    if (!outer) return
    const cx = outer.clientWidth  / 2
    const cy = outer.clientHeight / 2
    const ns = Math.min(3, Math.max(0.15, sc.current * factor))
    tx.current = cx - (cx - tx.current) * (ns / sc.current)
    ty.current = cy - (cy - ty.current) * (ns / sc.current)
    sc.current = ns
    applyTransform()
  }, [applyTransform])

  // ── toggle collapse ───────────────────────────────────────
  const toggle = useCallback((id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }, [])

  return (
    <div
      ref={outerRef}
      style={{
        position: 'relative',
        width: '100%',
        height: isFullscreen ? '100%' : 490,
        background: C.bg,
        backgroundImage: `radial-gradient(circle, ${C.dot} 1px, transparent 1px)`,
        backgroundSize: '22px 22px',
        borderRadius: isFullscreen ? 0 : 14,
        overflow: 'hidden',
        cursor: 'grab',
        userSelect: 'none',
        fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
      }}
    >
      {/*
        ─────────────────────────────────────────────────────
        Inner wrapper — ONE element that gets pan/zoom.
        Both SVG edges AND HTML node divs live here so they
        share the exact same transform — perfect alignment.
        transformOrigin 0 0 so coordinates match layout.
        ─────────────────────────────────────────────────────
      */}
      <div
        ref={innerRef}
        style={{
          position: 'absolute',
          top: 0, left: 0,
          transformOrigin: '0 0',
          // initial transform applied once layout is known
        }}
      >
        {/* ── SVG layer: edges only ── */}
        <svg
          width={svgW}
          height={svgH}
          style={{ position: 'absolute', top: 0, left: 0, overflow: 'visible', pointerEvents: 'none' }}
        >
          {edges.map(([a, b], i) => (
            <path
              key={i}
              d={edgePath(a, b)}
              stroke={C.edge}
              strokeWidth={2}
              fill="none"
              strokeLinecap="round"
              opacity={0.75}
            />
          ))}
        </svg>

        {/* ── HTML layer: node cards ── */}
        {nodes.map(n => {
          const hasKids = n.data.children != null && n.data.children.length > 0
          const fill   = n.depth === 0 ? C.f0 : n.depth === 1 ? C.f1 : C.f2
          const border = n.depth === 0 ? C.b0 : n.depth === 1 ? C.b1 : C.b2
          const txtCol = n.depth === 0 ? C.t0 : C.t1
          const dscCol = n.depth === 0 ? C.d0 : C.d1
          const shadow = n.depth === 0
            ? '0 4px 18px rgba(66,133,244,0.3)'
            : n.depth === 1 ? '0 2px 10px rgba(0,0,0,0.09)' : '0 1px 4px rgba(0,0,0,0.06)'

          return (
            <div
              key={n.id}
              data-mm="node"
              onClick={() => hasKids && toggle(n.id)}
              style={{
                position: 'absolute',
                left: n.x,
                top:  n.y,
                width: n.w,
                minHeight: n.h,
                background: fill,
                border: `1.5px solid ${border}`,
                borderRadius: 10,
                padding: n.depth === 0 ? '12px 16px' : '9px 14px',
                boxSizing: 'border-box',
                boxShadow: shadow,
                cursor: hasKids ? 'pointer' : 'default',
                transition: 'box-shadow 0.15s, transform 0.12s',
              }}
              onMouseEnter={e => {
                if (hasKids) {
                  (e.currentTarget as HTMLElement).style.boxShadow = '0 6px 24px rgba(66,133,244,0.25)'
                  ;(e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)'
                }
              }}
              onMouseLeave={e => {
                ;(e.currentTarget as HTMLElement).style.boxShadow = shadow
                ;(e.currentTarget as HTMLElement).style.transform = ''
              }}
              title={n.depth >= 2 ? n.data.description : ''}
            >
              {/* Title */}
              <div style={{
                fontSize: n.depth === 0 ? 13.5 : 12.5,
                fontWeight: n.depth === 0 ? 700 : 600,
                color: txtCol,
                lineHeight: 1.35,
                marginBottom: (n.depth <= 1 && n.data.description) ? 4 : 0,
                wordBreak: 'break-word',
              }}>
                {n.data.title}
              </div>

              {/* Description — only root & L1 */}
              {n.depth <= 1 && n.data.description && (
                <div style={{
                  fontSize: 11,
                  color: dscCol,
                  lineHeight: 1.4,
                  wordBreak: 'break-word',
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                  overflow: 'hidden',
                } as React.CSSProperties}>
                  {n.data.description}
                </div>
              )}

              {/* Expand / collapse badge */}
              {hasKids && (
                <div style={{
                  position: 'absolute',
                  right: -12,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 24, height: 24,
                  borderRadius: '50%',
                  background: C.badge,
                  border: '2px solid #fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: '#fff',
                  fontSize: 14, fontWeight: 800,
                  lineHeight: 1,
                  boxShadow: '0 2px 8px rgba(66,133,244,0.4)',
                  zIndex: 2,
                  pointerEvents: 'none',
                  userSelect: 'none',
                }}>
                  {n.isCol ? '+' : '−'}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* ── Controls ── */}
      <div style={{
        position: 'absolute', bottom: 16, right: 16,
        display: 'flex', flexDirection: 'column', gap: 6, zIndex: 30,
      }}>
        {onClose && <Btn onClick={onClose} title="Close"><X size={15} /></Btn>}
        <Btn onClick={() => zoom(1.15)} title="Zoom in"><Plus  size={15} /></Btn>
        <Btn onClick={() => zoom(0.87)} title="Zoom out"><Minus size={15} /></Btn>
        <Btn onClick={fitToScreen}      title="Fit to screen"><Maximize size={15} /></Btn>
      </div>

      {/* ── Legend ── */}
      <div style={{
        position: 'absolute', bottom: 14, left: 14,
        fontSize: 11, color: '#9baacf',
        userSelect: 'none', pointerEvents: 'none',
      }}>
        {allowWheelZoom ? 'Scroll to zoom · ' : ''}Drag to pan · Click node to expand/collapse
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Public MindmapView
// ──────────────────────────────────────────────────────────────
const MindmapView = forwardRef<MindmapViewHandle, MindmapViewProps>(
  function MindmapView({ rootNode, hideInlineExpand = false }, ref) {
    const [isFS, setFS] = useState(false)

    useImperativeHandle(ref, () => ({ openFullscreen: () => setFS(true) }), [])

    const onKey = useCallback((e: KeyboardEvent) => {
      if (e.key === 'Escape') setFS(false)
    }, [])

    useEffect(() => {
      if (isFS) {
        document.addEventListener('keydown', onKey)
        document.body.style.overflow = 'hidden'
      }
      return () => {
        document.removeEventListener('keydown', onKey)
        document.body.style.overflow = ''
      }
    }, [isFS, onKey])

    return (
      <>
        {/* Inline — no wheel zoom */}
        <div style={{ position: 'relative', width: '100%' }}>
          <TreeCanvas rootNode={rootNode} isFullscreen={false} allowWheelZoom={false} />
          {!hideInlineExpand && (
            <button
              onClick={() => setFS(true)}
              title="Open fullscreen"
              style={{
                position: 'absolute', top: 10, right: 10,
                width: 32, height: 32, borderRadius: 8,
                background: 'rgba(255,255,255,0.9)',
                border: `1px solid ${C.ctrlB}`, color: C.ctrlT,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', zIndex: 5,
                boxShadow: '0 1px 4px rgba(0,0,0,0.1)',
              }}
            >
              <Maximize2 size={14} />
            </button>
          )}
        </div>

        {/* Fullscreen — wheel zoom ON */}
        {isFS && (
          <div
            style={{
              position: 'fixed', inset: 0, zIndex: 9999,
              background: 'rgba(15,23,42,0.5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
            onClick={e => { if (e.target === e.currentTarget) setFS(false) }}
          >
            <div style={{
              width: 'calc(100vw - 56px)', maxWidth: 1440,
              height: 'calc(100vh - 56px)',
              borderRadius: 18, overflow: 'hidden',
              boxShadow: '0 32px 80px rgba(0,0,0,0.3)',
            }}>
              <TreeCanvas rootNode={rootNode} isFullscreen allowWheelZoom onClose={() => setFS(false)} />
            </div>
          </div>
        )}
      </>
    )
  }
)

export default MindmapView
