import { create } from 'zustand'

/**
 * Transient UI state (modal/overlay visibility). Kept separate from the
 * domain stores so it never gets serialized into project files.
 */
interface UiState {
  bilibiliOpen: boolean
  openBilibili: () => void
  closeBilibili: () => void
}

export const useUiStore = create<UiState>((set) => ({
  bilibiliOpen: false,
  openBilibili: () => set({ bilibiliOpen: true }),
  closeBilibili: () => set({ bilibiliOpen: false })
}))
