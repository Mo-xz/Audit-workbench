/**
 * An exhibit as the Word export needs it: a PNG of what the page drew.
 *
 * The exhibits are SVG styled by classes and `--aw-chart-*` tokens, which
 * mean nothing once the drawing leaves the page. So each element's computed
 * paint is written onto a copy as attributes, under the light theme — a file
 * is printed on white whatever the reader's screen is — and the copy is drawn
 * onto a canvas at twice its size.
 */
const PAINT = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'font-size', 'font-weight', 'font-family', 'opacity'] as const

function inlined(svg: SVGSVGElement): SVGSVGElement {
  const html = document.documentElement
  const theme = html.getAttribute('data-theme')
  html.setAttribute('data-theme', 'light')
  try {
    const copy = svg.cloneNode(true) as SVGSVGElement
    const from = [svg, ...svg.querySelectorAll('*')]
    const to = [copy, ...copy.querySelectorAll('*')]
    from.forEach((node, index) => {
      const style = getComputedStyle(node)
      const target = to[index] as SVGElement
      for (const name of PAINT) target.setAttribute(name, style.getPropertyValue(name))
      target.removeAttribute('class')
      target.removeAttribute('tabindex')
    })
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    return copy
  } finally {
    if (theme === null) html.removeAttribute('data-theme')
    else html.setAttribute('data-theme', theme)
  }
}

export async function svgImage(svg: SVGSVGElement): Promise<{ data: string; width: number; height: number } | null> {
  const width = Number(svg.getAttribute('width')), height = Number(svg.getAttribute('height'))
  if (!width || !height) return null
  const markup = new XMLSerializer().serializeToString(inlined(svg))
  const image = new Image()
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`
  try { await image.decode() } catch { return null }
  const canvas = document.createElement('canvas')
  canvas.width = width * 2
  canvas.height = height * 2
  const context = canvas.getContext('2d')
  if (!context) return null
  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.scale(2, 2)
  context.drawImage(image, 0, 0, width, height)
  return { data: canvas.toDataURL('image/png'), width, height }
}
