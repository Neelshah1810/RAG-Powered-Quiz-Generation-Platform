import React, { useState, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react'
import { ChevronRight, ChevronLeft, LayoutTemplate, Maximize2, X } from 'lucide-react'

export interface MindmapNode {
  title: string
  description: string
  children?: MindmapNode[]
}

interface MindmapViewProps {
  rootNode: MindmapNode
  /** If true, the expand button inside the center card is hidden.
   *  Use this when the parent renders its own expand button externally. */
  hideInlineExpand?: boolean
}

/** Imperative handle exposed via ref — lets the parent open fullscreen. */
export interface MindmapViewHandle {
  openFullscreen: () => void
}

/* ─────────────────────────────────────────────────────────────
   Internal renderer — shared between inline and fullscreen.
   `isFullscreen` only controls visual sizing (larger cards,
   grid layout for children). Navigation logic is identical.
   ───────────────────────────────────────────────────────────── */
interface MindmapContentProps {
  path: MindmapNode[]
  setPath: React.Dispatch<React.SetStateAction<MindmapNode[]>>
  isFullscreen?: boolean
  /** Only shown in fullscreen mode — closes the modal */
  onClose?: () => void
  /** Only shown in inline mode — opens fullscreen */
  onExpand?: () => void
  /** When true, the expand icon inside the center card is hidden */
  hideInlineExpand?: boolean
}

function MindmapContent({ path, setPath, isFullscreen = false, onClose, onExpand, hideInlineExpand = false }: MindmapContentProps) {
  const currentNode = path[path.length - 1]
  const hasParent = path.length > 1

  const goBack = () => {
    if (hasParent) {
      setPath(prev => prev.slice(0, -1))
    }
  }

  const navigateTo = (node: MindmapNode) => {
    if (node.children && node.children.length > 0) {
      setPath(prev => [...prev, node])
    }
  }

  const jumpTo = (index: number) => {
    setPath(prev => prev.slice(0, index + 1))
  }

  /* ── Size tokens that scale up in fullscreen ── */
  const centerPad = isFullscreen ? '28px' : '20px'
  const centerFontSize = isFullscreen ? '22px' : '18px'
  const centerDescSize = isFullscreen ? '15px' : '14px'
  const childPad = isFullscreen ? '18px 20px' : '16px'
  const childTitleSize = isFullscreen ? '16px' : '15px'
  const childDescSize = isFullscreen ? '14px' : '13px'
  const maxCenterWidth = isFullscreen ? '680px' : '500px'

  return (
    <div
      className="mindmap-view"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
        alignItems: 'center',
        width: '100%',
        padding: isFullscreen ? '32px 40px' : '16px',
        /* Fullscreen needs scroll support */
        ...(isFullscreen ? { overflowY: 'auto', maxHeight: '100%' } : {}),
      }}
    >

      {/* ── Breadcrumbs ────────────────────────────── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', alignSelf: 'flex-start', marginBottom: '10px' }}>
        {path.map((node, i) => (
          <React.Fragment key={i}>
            <button
              onClick={() => jumpTo(i)}
              className="text-small"
              style={{
                background: 'none',
                border: 'none',
                color: i === path.length - 1 ? 'var(--color-text)' : 'var(--color-primary)',
                fontWeight: i === path.length - 1 ? 600 : 500,
                cursor: i === path.length - 1 ? 'default' : 'pointer',
                padding: 0,
                fontSize: isFullscreen ? '14px' : undefined,
              }}
            >
              {node.title}
            </button>
            {i < path.length - 1 && <ChevronRight size={14} color="var(--color-text-3)" />}
          </React.Fragment>
        ))}
      </div>

      {/* ── Main Node Area ─────────────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative', width: '100%', maxWidth: maxCenterWidth }}>

        {/* Back Button (Above Center Card) */}
        {hasParent && (
          <button
            onClick={goBack}
            className="btn btn-ghost"
            style={{ marginBottom: '16px', borderRadius: '50%', padding: '8px' }}
            title="Go Back"
          >
            <ChevronLeft size={20} />
          </button>
        )}

        {/* Current (Center) Node */}
        <div className="mindmap-card current" style={{
            background: 'var(--color-surface)',
            border: '2px solid var(--color-primary)',
            borderRadius: '12px',
            padding: centerPad,
            width: '100%',
            textAlign: 'center',
            boxShadow: '0 4px 12px rgba(66, 133, 244, 0.15)',
            zIndex: 2,
            position: 'relative'
        }}>
          {/* Inline expand button — only shown when parent hasn't hidden it */}
          {onExpand && !isFullscreen && !hideInlineExpand && (
            <button
              onClick={(e) => { e.stopPropagation(); onExpand(); }}
              title="Expand to Fullscreen"
              style={{
                position: 'absolute',
                top: '10px',
                right: '10px',
                background: 'var(--color-primary-bg)',
                border: 'none',
                borderRadius: '8px',
                padding: '6px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-primary)',
                transition: 'background 0.15s',
              }}
            >
              <Maximize2 size={16} />
            </button>
          )}

          <h3 style={{ margin: '0 0 8px 0', fontSize: centerFontSize, color: 'var(--color-text)' }}>
            {currentNode.title}
          </h3>
          <p className="text-muted" style={{ margin: 0, fontSize: centerDescSize, lineHeight: '1.5' }}>
            {currentNode.description}
          </p>
        </div>

        {/* Connector Line to Children */}
        {currentNode.children && currentNode.children.length > 0 && (
          <div style={{
            width: '2px',
            height: '30px',
            background: 'var(--color-border)',
            margin: '0 auto'
          }} />
        )}

        {/* Children Nodes — grid in fullscreen, stacked column inline */}
        {currentNode.children && currentNode.children.length > 0 && (
          <div style={{
            display: isFullscreen ? 'grid' : 'flex',
            ...(isFullscreen
              ? { gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '14px' }
              : { flexDirection: 'column' as const, gap: '12px' }),
            width: '100%',
            marginTop: '8px',
            ...(isFullscreen ? { maxWidth: '900px' } : {}),
          }}>
            {currentNode.children.map((child, i) => {
              const isExpandable = child.children && child.children.length > 0
              return (
                <div
                  key={i}
                  className={`mindmap-card child ${isExpandable ? 'expandable' : ''}`}
                  onClick={() => navigateTo(child)}
                  style={{
                    background: 'var(--color-surface-2)',
                    border: '1px solid var(--color-border)',
                    borderRadius: '10px',
                    padding: childPad,
                    cursor: isExpandable ? 'pointer' : 'default',
                    transition: 'all 0.2s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    boxShadow: 'var(--shadow-1)'
                  }}
                >
                  <div style={{ flex: 1, paddingRight: '12px' }}>
                    <h4 style={{ margin: '0 0 4px 0', fontSize: childTitleSize, color: 'var(--color-text)' }}>
                      {child.title}
                    </h4>
                    <p className="text-muted" style={{ margin: 0, fontSize: childDescSize }}>
                      {child.description}
                    </p>
                  </div>
                  {isExpandable && (
                    <div style={{
                      background: 'var(--color-primary-bg)',
                      borderRadius: '50%',
                      padding: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--color-primary)'
                    }}>
                      <ChevronRight size={18} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* Placeholder if no children */}
        {(!currentNode.children || currentNode.children.length === 0) && (
           <div style={{ marginTop: '24px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-3)', fontSize: '14px' }}>
             <LayoutTemplate size={16} /> Leaf concept reached
           </div>
        )}

      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────
   Public component — owns the path state so it's shared
   between the inline view and the fullscreen modal.
   ───────────────────────────────────────────────────────────── */
const MindmapView = forwardRef<MindmapViewHandle, MindmapViewProps>(
  function MindmapView({ rootNode, hideInlineExpand = false }, ref) {
  const [path, setPath] = useState<MindmapNode[]>([rootNode])
  const [isFullscreen, setIsFullscreen] = useState(false)

  /* Expose openFullscreen so the parent can trigger it via ref */
  useImperativeHandle(ref, () => ({
    openFullscreen: () => setIsFullscreen(true),
  }), [])

  /* Close fullscreen on Esc key */
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape' && isFullscreen) {
      setIsFullscreen(false)
    }
  }, [isFullscreen])

  useEffect(() => {
    if (isFullscreen) {
      document.addEventListener('keydown', handleKeyDown)
      /* Prevent body scroll while modal is open */
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isFullscreen, handleKeyDown])

  return (
    <>
      {/* ── Inline (normal) view — unchanged behavior ── */}
      <MindmapContent
        path={path}
        setPath={setPath}
        isFullscreen={false}
        onExpand={() => setIsFullscreen(true)}
        hideInlineExpand={hideInlineExpand}
      />

      {/* ── Fullscreen modal overlay ── */}
      {isFullscreen && (
        <div
          className="mindmap-fullscreen-overlay"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            background: 'rgba(0, 0, 0, 0.65)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            animation: 'fadeIn 0.2s ease',
          }}
          /* Click on the dark backdrop to close */
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsFullscreen(false)
          }}
        >
          <div
            className="mindmap-fullscreen-container"
            style={{
              background: 'var(--color-bg, #fff)',
              borderRadius: '16px',
              width: 'calc(100vw - 80px)',
              maxWidth: '1100px',
              height: 'calc(100vh - 80px)',
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              boxShadow: '0 24px 64px rgba(0,0,0,0.25)',
            }}
          >
            {/* Close button */}
            <button
              onClick={() => setIsFullscreen(false)}
              title="Close fullscreen"
              style={{
                position: 'absolute',
                top: '14px',
                right: '14px',
                zIndex: 10,
                background: 'var(--color-surface-2, #f1f3f5)',
                border: '1px solid var(--color-border)',
                borderRadius: '10px',
                padding: '8px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-text)',
                transition: 'background 0.15s',
              }}
            >
              <X size={20} />
            </button>

            {/* Same content, larger sizing */}
            <div style={{ flex: 1, overflow: 'auto' }}>
              <MindmapContent
                path={path}
                setPath={setPath}
                isFullscreen={true}
                onClose={() => setIsFullscreen(false)}
              />
            </div>
          </div>
        </div>
      )}
    </>
  )
})

export default MindmapView
