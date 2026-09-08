/** Decoding changed-region frames (specification section 10).
 *
 *  The endpoint sends a whole screen only when it has to; the rest of the time
 *  it sends the tiles that changed. This keeps a backing canvas holding the
 *  last complete picture and paints updates onto it, so the viewer always has a
 *  full frame to draw even though most messages carry a fraction of one.
 *
 *  Wire format, little-endian, matching `agent/rmm_agent/tiles.py`:
 *
 *    keyframe   0x00 | width u16 | height u16 | jpeg bytes
 *    tile frame 0x01 | width u16 | height u16 | count u16 |
 *                     count x ( x u16 | y u16 | w u16 | h u16 | len u32 | jpeg )
 */

export const KEYFRAME = 0x00
export const TILE_FRAME = 0x01

export interface DecodedFrame {
  /** The complete picture after applying this message. */
  canvas: HTMLCanvasElement | OffscreenCanvas
  width: number
  height: number
  /** How many tiles this message carried; 0 means nothing moved. */
  tiles: number
  keyframe: boolean
}

function makeCanvas(width: number, height: number): HTMLCanvasElement | OffscreenCanvas {
  if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(width, height)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  return canvas
}

/** Holds the last complete picture and applies updates to it. */
export class FrameAssembler {
  private canvas: HTMLCanvasElement | OffscreenCanvas | null = null
  private context: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null = null
  private width = 0
  private height = 0
  /** True once a keyframe has arrived: before that there is nothing to patch. */
  private primed = false

  get ready(): boolean {
    return this.primed && this.canvas !== null
  }

  private ensure(width: number, height: number) {
    if (this.canvas && this.width === width && this.height === height) return
    this.canvas = makeCanvas(width, height)
    this.context = this.canvas.getContext('2d') as
      | CanvasRenderingContext2D
      | OffscreenCanvasRenderingContext2D
    this.width = width
    this.height = height
    this.primed = false
  }

  /** Decode one binary message. Returns null when it cannot be used yet. */
  async apply(buffer: ArrayBuffer): Promise<DecodedFrame | null> {
    if (buffer.byteLength < 5) return null
    const view = new DataView(buffer)
    const kind = view.getUint8(0)
    const width = view.getUint16(1, true)
    const height = view.getUint16(3, true)
    if (width === 0 || height === 0) return null

    this.ensure(width, height)
    if (!this.context || !this.canvas) return null

    if (kind === KEYFRAME) {
      const jpeg = buffer.slice(5)
      const bitmap = await createImageBitmap(new Blob([jpeg], { type: 'image/jpeg' }))
      this.context.drawImage(bitmap, 0, 0)
      bitmap.close?.()
      this.primed = true
      return { canvas: this.canvas, width, height, tiles: 1, keyframe: true }
    }

    if (kind !== TILE_FRAME) return null

    const count = view.getUint16(5, true)
    // Tiles patch the previous picture, so they are useless without one.
    if (!this.primed) return null
    if (count === 0) {
      return { canvas: this.canvas, width, height, tiles: 0, keyframe: false }
    }

    let offset = 7
    const decoded: { x: number; y: number; bitmap: ImageBitmap }[] = []
    for (let i = 0; i < count; i++) {
      if (offset + 12 > buffer.byteLength) break
      const x = view.getUint16(offset, true)
      const y = view.getUint16(offset + 2, true)
      const w = view.getUint16(offset + 4, true)
      const h = view.getUint16(offset + 6, true)
      const length = view.getUint32(offset + 8, true)
      offset += 12
      if (offset + length > buffer.byteLength) break

      const jpeg = buffer.slice(offset, offset + length)
      offset += length
      try {
        const bitmap = await createImageBitmap(new Blob([jpeg], { type: 'image/jpeg' }))
        decoded.push({ x, y, bitmap })
      } catch {
        // A damaged tile is dropped; the next keyframe repairs that region.
      }
      void w
      void h
    }

    for (const tile of decoded) {
      this.context.drawImage(tile.bitmap, tile.x, tile.y)
      tile.bitmap.close?.()
    }

    return { canvas: this.canvas, width, height, tiles: decoded.length, keyframe: false }
  }

  reset() {
    this.primed = false
  }
}
