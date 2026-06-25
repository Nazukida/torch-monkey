import { create } from 'zustand'
import type {
  MotionData,
  MotionMeta,
  ListMotionsOptions,
  ListMotionsResult
} from '@shared/types/motion'

interface MotionState {
  motionList: MotionMeta[]
  total: number
  selectedId: string | null
  selectedMotion: MotionData | null
  loadingFull: boolean

  searchQuery: string
  filterTags: string[]
  sortBy: NonNullable<ListMotionsOptions['sortBy']>
  sortOrder: NonNullable<ListMotionsOptions['sortOrder']>

  loadMotionList: () => Promise<void>
  selectMotion: (id: string | null) => Promise<void>
  getMotionData: (id: string) => Promise<MotionData | null>
  importMotion: (data: MotionData) => Promise<void>
  deleteMotion: (id: string) => Promise<void>
  updateMotionMeta: (id: string, partial: Partial<MotionData>) => Promise<void>

  setSearchQuery: (q: string) => void
  toggleFilterTag: (tag: string) => void
  setSortBy: (s: MotionState['sortBy']) => void
}

export const useMotionStore = create<MotionState>((set, get) => ({
  motionList: [],
  total: 0,
  selectedId: null,
  selectedMotion: null,
  loadingFull: false,
  searchQuery: '',
  filterTags: [],
  sortBy: 'updated_at',
  sortOrder: 'desc',

  loadMotionList: async () => {
    const s = get()
    const opts: ListMotionsOptions = {
      search: s.searchQuery.trim() || undefined,
      tags: s.filterTags.length ? s.filterTags : undefined,
      sortBy: s.sortBy,
      sortOrder: s.sortOrder
    }
    const res: ListMotionsResult = await window.electronAPI.dbListMotions(opts)
    set({ motionList: res.motions, total: res.total })
  },

  selectMotion: async (id) => {
    if (id === null) {
      set({ selectedId: null, selectedMotion: null })
      return
    }
    set({ selectedId: id, loadingFull: true })
    const data = await window.electronAPI.dbGetMotion(id)
    set({ selectedMotion: data, loadingFull: false })
  },

  getMotionData: async (id) => {
    return window.electronAPI.dbGetMotion(id)
  },

  importMotion: async (data) => {
    await window.electronAPI.dbCreateMotion(data)
    await get().loadMotionList()
    await get().selectMotion(data.id)
  },

  deleteMotion: async (id) => {
    await window.electronAPI.dbDeleteMotion(id)
    if (get().selectedId === id) set({ selectedId: null, selectedMotion: null })
    await get().loadMotionList()
  },

  updateMotionMeta: async (id, partial) => {
    await window.electronAPI.dbUpdateMotion(id, partial)
    await get().loadMotionList()
  },

  setSearchQuery: (q) => {
    set({ searchQuery: q })
  },
  toggleFilterTag: (tag) =>
    set((s) => ({
      filterTags: s.filterTags.includes(tag)
        ? s.filterTags.filter((t) => t !== tag)
        : [...s.filterTags, tag]
    })),
  setSortBy: (sb) => set({ sortBy: sb })
}))
