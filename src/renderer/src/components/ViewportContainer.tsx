import { useEffect, useRef } from 'react'
import { SceneController } from '@renderer/lib/sceneController'

/**
 * Hosts the Babylon canvas and boots the scene controller. Nothing else renders
 * here — the 3D viewport is a single full-bleed canvas driven imperatively.
 */
export function ViewportContainer(): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let disposed = false
    let disposeController: (() => void) | null = null

    SceneController.init(canvas)
      .then(() => {
        if (disposed) {
          SceneController.dispose()
          return
        }
        disposeController = () => SceneController.dispose()
      })
      .catch((e) => console.error('[ViewportContainer] scene init failed:', e))

    const onResize = () => SceneController
    window.addEventListener('resize', onResize)

    return () => {
      disposed = true
      window.removeEventListener('resize', onResize)
      disposeController?.()
    }
  }, [])

  return (
    <div className="relative h-full w-full">
      <canvas ref={canvasRef} className="h-full w-full touch-none outline-none" />
      <ViewportOverlay />
    </div>
  )
}

function ViewportOverlay(): React.JSX.Element {
  return (
    <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-black/40 px-2 py-1 text-[10px] text-zinc-400">
      左键拖拽旋转 · 滚轮缩放 · 右键平移
    </div>
  )
}
