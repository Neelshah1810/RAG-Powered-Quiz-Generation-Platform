import React, { useState, useEffect } from 'react'
import { X, ExternalLink, Download } from 'lucide-react'

interface FilePreviewModalProps {
  url: string
  fileName: string
  onClose: () => void
}

export default function FilePreviewModal({ url, fileName, onClose }: FilePreviewModalProps) {
  const [content, setContent] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  const isImage = ['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)
  const isPdf = ext === 'pdf'
  const isOffice = ['doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx'].includes(ext)
  const isTextBased = ['txt', 'md', 'csv', 'json', 'log', 'py', 'ipynb', 'js', 'ts', 'jsx', 'tsx', 'html', 'css'].includes(ext)

  useEffect(() => {
    if (isTextBased) {
      fetch(url)
        .then(res => {
          if (!res.ok) throw new Error('Failed to fetch content')
          return res.text()
        })
        .then(text => {
          setContent(text)
          setLoading(false)
        })
        .catch(() => {
          setError(true)
          setLoading(false)
        })
    } else {
      setLoading(false)
    }
  }, [url, isTextBased])

  return (
    <div className="modal-overlay" onClick={onClose} style={{ zIndex: 9999 }}>
      <div 
        className="modal" 
        onClick={e => e.stopPropagation()} 
        style={{ 
          maxWidth: '90%', 
          width: 1000, 
          height: '90vh', 
          display: 'flex', 
          flexDirection: 'column',
          padding: 0,
          overflow: 'hidden'
        }}
      >
        <div className="modal-header" style={{ padding: '16px 20px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <h3 style={{ margin: 0 }}>{fileName}</h3>
            <a href={url} target="_blank" rel="noopener noreferrer" className="btn btn-ghost btn-icon" title="Open in new tab">
              <ExternalLink size={18} />
            </a>
            <a href={url} download={fileName} className="btn btn-ghost btn-icon" title="Download">
              <Download size={18} />
            </a>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="modal-body" style={{ flex: 1, padding: 0, overflow: 'auto', background: 'var(--color-surface-2)', position: 'relative' }}>
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
              Loading preview...
            </div>
          )}
          
          {!loading && error && (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--color-danger)' }}>
              Failed to load preview. Please download the file instead.
            </div>
          )}

          {!loading && !error && (
            <>
              {isImage && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', padding: 20 }}>
                  <img src={url} alt={fileName} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
                </div>
              )}

              {isPdf && (
                <iframe 
                  src={url} 
                  title={fileName}
                  style={{ width: '100%', height: '100%', border: 'none' }} 
                />
              )}

              {isOffice && (
                <iframe 
                  src={`https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(url)}`} 
                  title={fileName}
                  style={{ width: '100%', height: '100%', border: 'none' }} 
                />
              )}

              {isTextBased && content !== null && (
                <pre style={{ 
                  margin: 0, 
                  padding: 20, 
                  whiteSpace: 'pre-wrap', 
                  wordBreak: 'break-word',
                  fontFamily: 'monospace',
                  fontSize: 13,
                  background: 'var(--color-surface)',
                  minHeight: '100%'
                }}>
                  {content}
                </pre>
              )}

              {!isImage && !isPdf && !isOffice && !isTextBased && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', padding: 20, gap: 16 }}>
                  <div style={{ fontSize: 48 }}>📄</div>
                  <div style={{ textAlign: 'center' }}>
                    <p style={{ fontWeight: 500, marginBottom: 8 }}>Preview not available for this file format.</p>
                    <p className="text-muted">Please download the file to view its contents.</p>
                  </div>
                  <a href={url} download={fileName} className="btn btn-primary">
                    <Download size={16} /> Download File
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
