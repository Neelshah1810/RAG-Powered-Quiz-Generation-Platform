import { useState, type ReactNode } from 'react'
import { Copy, Check } from 'lucide-react'

interface MarkdownRendererProps {
  content: string
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)

  const copyToClipboard = (text: string, index: number) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  if (!content) return null

  // Process code blocks first
  const parts = content.split(/(```[\s\S]*?```)/g)

  return (
    <div className="markdown-body" style={{ lineHeight: 1.65, fontSize: '14.5px', color: 'var(--color-text)' }}>
      {parts.map((part, index) => {
        // Code Block
        if (part.startsWith('```') && part.endsWith('```')) {
          const match = part.match(/^```(\w*)\n?([\s\S]*?)```$/)
          const language = match ? match[1] || 'code' : 'code'
          const codeText = match ? match[2].trim() : part.slice(3, -3).trim()

          return (
            <div
              key={index}
              style={{
                margin: '14px 0',
                borderRadius: 10,
                overflow: 'hidden',
                background: '#181825',
                color: '#CDD6F4',
                fontFamily: 'SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace',
                fontSize: 13,
                border: '1px solid #313244',
                boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '8px 14px',
                  background: '#11111B',
                  borderBottom: '1px solid #313244',
                  color: '#A6ADC8',
                  fontSize: 12,
                  fontWeight: 600,
                  letterSpacing: '0.5px',
                }}
              >
                <span>{language.toUpperCase()}</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  style={{ color: '#A6ADC8', padding: '2px 8px', fontSize: 11, gap: 4 }}
                  onClick={() => copyToClipboard(codeText, index)}
                >
                  {copiedIndex === index ? (
                    <>
                      <Check size={13} color="#A6E3A1" /> Copied!
                    </>
                  ) : (
                    <>
                      <Copy size={13} /> Copy code
                    </>
                  )}
                </button>
              </div>
              <pre style={{ margin: 0, padding: 14, overflowX: 'auto', whiteSpace: 'pre' }}>
                <code>{codeText}</code>
              </pre>
            </div>
          )
        }

        // Render prose & structural elements
        const lines = part.split('\n')
        const elements: ReactNode[] = []
        let tableRows: string[] = []

        const flushTable = (keyPrefix: string) => {
          if (tableRows.length === 0) return
          const rows = tableRows.map(r => r.split('|').filter((_, i, a) => i > 0 && i < a.length - 1).map(c => c.trim()))
          if (rows.length > 0) {
            const header = rows[0]
            const body = rows.slice(rows[1] && rows[1].every(cell => cell.includes('-')) ? 2 : 1)
            elements.push(
              <div key={`${keyPrefix}-table`} style={{ overflowX: 'auto', margin: '14px 0' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13.5, border: '1px solid var(--color-border)' }}>
                  <thead>
                    <tr style={{ background: 'var(--color-surface-2)', borderBottom: '2px solid var(--color-border)' }}>
                      {header.map((cell, cIdx) => (
                        <th key={cIdx} style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600 }}>
                          {renderFormattedText(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {body.map((r, rIdx) => (
                      <tr key={rIdx} style={{ borderBottom: '1px solid var(--color-border)' }}>
                        {r.map((cell, cIdx) => (
                          <td key={cIdx} style={{ padding: '8px 12px' }}>
                            {renderFormattedText(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
          tableRows = []
        }

        for (let lIdx = 0; lIdx < lines.length; lIdx++) {
          const line = lines[lIdx]
          const trimmed = line.trim()

          // Table detection
          if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
            tableRows.push(trimmed)
            continue
          } else {
            flushTable(`${index}-${lIdx}`)
          }

          if (!trimmed) {
            elements.push(<div key={lIdx} style={{ height: 6 }} />)
            continue
          }

          // Horizontal rule
          if (trimmed === '---' || trimmed === '***' || trimmed === '___') {
            elements.push(<hr key={lIdx} style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '14px 0' }} />)
            continue
          }

          // Headings
          if (trimmed.startsWith('### ')) {
            elements.push(
              <h4 key={lIdx} style={{ fontSize: 16, fontWeight: 700, margin: '14px 0 6px', color: 'var(--color-primary-dark, #1A73E8)' }}>
                {renderFormattedText(trimmed.slice(4))}
              </h4>
            )
            continue
          }
          if (trimmed.startsWith('## ')) {
            elements.push(
              <h3 key={lIdx} style={{ fontSize: 17.5, fontWeight: 700, margin: '16px 0 8px', color: 'var(--color-text)' }}>
                {renderFormattedText(trimmed.slice(3))}
              </h3>
            )
            continue
          }
          if (trimmed.startsWith('# ')) {
            elements.push(
              <h2 key={lIdx} style={{ fontSize: 19, fontWeight: 700, margin: '18px 0 10px', color: 'var(--color-text)' }}>
                {renderFormattedText(trimmed.slice(2))}
              </h2>
            )
            continue
          }

          // Blockquote
          if (trimmed.startsWith('> ')) {
            elements.push(
              <div
                key={lIdx}
                style={{
                  borderLeft: '4px solid var(--color-primary)',
                  background: 'var(--color-primary-bg, #F8FAFC)',
                  padding: '8px 14px',
                  margin: '8px 0',
                  borderRadius: '0 8px 8px 0',
                  fontSize: 14,
                  color: 'var(--color-text-2)',
                }}
              >
                {renderFormattedText(trimmed.slice(2))}
              </div>
            )
            continue
          }

          // Bullet points
          if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
            elements.push(
              <div key={lIdx} style={{ display: 'flex', gap: 8, marginLeft: 6, marginBottom: 5, alignItems: 'flex-start' }}>
                <span style={{ color: 'var(--color-primary)', fontWeight: 'bold', lineHeight: '1.4' }}>•</span>
                <span style={{ flex: 1 }}>{renderFormattedText(trimmed.slice(2))}</span>
              </div>
            )
            continue
          }

          // Numbered list
          const numMatch = trimmed.match(/^(\d+)\.\s+(.*)$/)
          if (numMatch) {
            elements.push(
              <div key={lIdx} style={{ display: 'flex', gap: 8, marginLeft: 6, marginBottom: 5, alignItems: 'flex-start' }}>
                <span style={{ fontWeight: 700, color: 'var(--color-primary)', minWidth: 20, fontSize: 13.5 }}>
                  {numMatch[1]}.
                </span>
                <span style={{ flex: 1 }}>{renderFormattedText(numMatch[2])}</span>
              </div>
            )
            continue
          }

          // Normal Paragraph Line
          elements.push(
            <p key={lIdx} style={{ margin: '0 0 6px 0' }}>
              {renderFormattedText(line)}
            </p>
          )
        }

        flushTable(`${index}-end`)
        return <div key={index}>{elements}</div>
      })}
    </div>
  )
}

/** Formats bold, italic, inline code, and math expressions within markdown text */
function renderFormattedText(text: string) {
  // Capture **bold**, *italic*, `code`, and $math$
  const regex = /(\*\*.*?\*\*|\*.*?\*|`.*?`|\$.*?\$)/g
  const tokens = text.split(regex)

  return tokens.map((token, i) => {
    if (token.startsWith('**') && token.endsWith('**') && token.length > 4) {
      return <strong key={i} style={{ fontWeight: 650, color: 'var(--color-text)' }}>{token.slice(2, -2)}</strong>
    }
    if (token.startsWith('*') && token.endsWith('*') && token.length > 2) {
      return <em key={i}>{token.slice(1, -1)}</em>
    }
    if (token.startsWith('`') && token.endsWith('`') && token.length > 2) {
      return (
        <code
          key={i}
          style={{
            background: 'var(--color-surface-2, #F1F3F4)',
            color: '#D93025',
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: 13,
            fontFamily: 'SFMono-Regular, Consolas, monospace',
          }}
        >
          {token.slice(1, -1)}
        </code>
      )
    }
    if (token.startsWith('$') && token.endsWith('$') && token.length > 2) {
      return (
        <span
          key={i}
          style={{
            fontFamily: 'serif',
            fontStyle: 'italic',
            padding: '0 4px',
            background: 'rgba(66, 133, 244, 0.08)',
            borderRadius: 3,
            color: 'var(--color-primary-dark)',
          }}
        >
          {token.slice(1, -1)}
        </span>
      )
    }
    return token
  })
}
