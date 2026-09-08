/** Minimal ANSI renderer for the remote terminal.
 *
 *  A real shell emits colour, bracketed-paste toggles and cursor moves. Only
 *  the colour is worth showing; everything else is control noise that must not
 *  reach the screen as literal text.
 */
export interface Segment {
  text: string
  colour?: string
  bold?: boolean
  dim?: boolean
}

const FOREGROUND: Record<number, string> = {
  30: '#5b6674', 31: '#ff6b6b', 32: '#4ec97a', 33: '#e8c46a',
  34: '#6aa9ff', 35: '#d28bff', 36: '#5fd0d0', 37: '#d7dee8',
  90: '#7a8798', 91: '#ff8f8f', 92: '#79dd9b', 93: '#f0d68d',
  94: '#8fbfff', 95: '#dfa9ff', 96: '#8adfdf', 97: '#ffffff',
}

// CSI sequences (colour, cursor moves, bracketed paste), OSC title sequences
// terminated by BEL or ST, and bare two-character escapes.
const ANSI_SOURCE = '\\x1b\\[[0-?]*[ -/]*[@-~]|\\x1b\\][\\s\\S]*?(?:\\x07|\\x1b\\\\)|\\x1b[@-Z\\\\-_]'

export function parseAnsi(input: string): Segment[] {
  const pattern = new RegExp(ANSI_SOURCE, 'g')
  const segments: Segment[] = []
  let style: Omit<Segment, 'text'> = {}
  let index = 0

  let match: RegExpExecArray | null
  while ((match = pattern.exec(input)) !== null) {
    if (match.index > index) {
      segments.push({ text: input.slice(index, match.index), ...style })
    }
    index = match.index + match[0].length

    // Only SGR ("...m") changes how text looks; the rest is discarded.
    const sequence = match[0]
    if (sequence.charAt(1) === '[' && sequence.endsWith('m')) {
      const body = sequence.slice(2, -1)
      if (body.startsWith('?')) continue
      for (const part of body.split(';')) {
        const code = Number(part || '0')
        if (code === 0) style = {}
        else if (code === 1) style = { ...style, bold: true }
        else if (code === 2) style = { ...style, dim: true }
        else if (code === 22) style = { ...style, bold: false, dim: false }
        else if (code === 39) style = { ...style, colour: undefined }
        else if (FOREGROUND[code]) style = { ...style, colour: FOREGROUND[code] }
      }
    }
  }

  if (index < input.length) segments.push({ text: input.slice(index), ...style })
  return segments
}

/** Apply carriage returns and backspaces so progress output does not stack up. */
export function applyControlChars(text: string): string {
  // A pty ends every line with CR LF. Normalise those first, or the trailing
  // CR would be read as "return to column zero" and blank the whole line.
  const normalised = text.replace(/\r\n/g, '\n')
  const lines: string[] = []
  for (const raw of normalised.split('\n')) {
    let line = ''
    for (const char of raw) {
      if (char === '\r') line = ''
      else if (char === '\b') line = line.slice(0, -1)
      else line += char
    }
    lines.push(line)
  }
  return lines.join('\n')
}
