import { create } from 'zustand'

/**
 * Transient UI state (modal/overlay visibility). Kept separate from the
 * domain stores so it never gets serialized into project files.
 */
interface UiState {
  bilibiliOpen: boolean
  openBilibili: () => void
  closeBilibili: () => void

  serverSettingsOpen: boolean
  openServerSettings: () => void
  closeServerSettings: () => void
}

export const useUiStore = create<UiState>((set) => ({
  bilibiliOpen: false,
  openBilibili: () => set({ bilibiliOpen: true }),
  closeBilibili: () => set({ bilibiliOpen: false }),

  serverSettingsOpen: false,
  openServerSettings: () => set({ serverSettingsOpen: true }),
  closeServerSettings: () => set({ serverSettingsOpen: false })
}))
