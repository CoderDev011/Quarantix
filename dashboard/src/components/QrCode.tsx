// A crisp SVG QR code (qrcode-generator, no network).
import qrcode from 'qrcode-generator'
import { useMemo } from 'react'

export function QrCode({ text, size = 320 }: { text: string; size?: number }) {
  const path = useMemo(() => {
    const qr = qrcode(0, 'M')
    qr.addData(text)
    qr.make()
    const count = qr.getModuleCount()
    let d = ''
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) {
        if (qr.isDark(row, col)) d += `M${col} ${row}h1v1h-1z`
      }
    }
    return { d, count }
  }, [text])
  return (
    <svg
      viewBox={`-2 -2 ${path.count + 4} ${path.count + 4}`}
      width={size}
      height={size}
      role="img"
      aria-label={`QR code for ${text}`}
      className="rounded-lg bg-white"
      shapeRendering="crispEdges"
    >
      <path d={path.d} fill="#000" />
    </svg>
  )
}
