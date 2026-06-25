import Database from 'better-sqlite3'
import path from 'path'
import fs from 'fs'
import { app } from 'electron'
import type {
  MotionData,
  MotionMeta,
  ListMotionsOptions,
  ListMotionsResult
} from '@shared/types/motion'
import type { ProjectFile, ProjectListItem } from '@shared/types/project'

type DB = Database.Database

/** Locate database/schema.sql across dev + packaged layouts. */
function findSchema(): string {
  const candidates = [
    path.join(app.getAppPath(), 'database', 'schema.sql'),
    path.join(process.resourcesPath ?? '', 'database', 'schema.sql'),
    path.join(__dirname, '..', '..', 'database', 'schema.sql'),
    path.join(process.cwd(), 'database', 'schema.sql')
  ]
  for (const c of candidates) {
    try {
      if (fs.existsSync(c)) return c
    } catch {
      /* ignore */
    }
  }
  return candidates[0]
}

export class DatabaseHandler {
  private db: DB

  constructor() {
    const dbPath = path.join(app.getPath('userData'), 'torch-monkey.db')
    this.db = new Database(dbPath)
    this.db.pragma('journal_mode = WAL')
    this.db.pragma('foreign_keys = ON')
    this.initialize()
  }

  private initialize(): void {
    const schemaPath = findSchema()
    const schema = fs.readFileSync(schemaPath, 'utf-8')
    this.db.exec(schema)
  }

  // ===== Motion CRUD =====

  createMotion(data: MotionData): void {
    const stmt = this.db.prepare(`
      INSERT OR REPLACE INTO motions
        (id, name, description, tags, fps, duration, frame_count, skeleton_type,
         poses_json, beat_markers_json, keyframe_flags, motion_intensity,
         primary_joints, is_loopable, source, source_video_path, thumbnail,
         created_at, updated_at)
      VALUES (@id, @name, @description, @tags, @fps, @duration, @frame_count, @skeleton_type,
              @poses_json, @beat_markers_json, @keyframe_flags, @motion_intensity,
              @primary_joints, @is_loopable, @source, @source_video_path, @thumbnail,
              @created_at, @updated_at)
    `)
    stmt.run({
      id: data.id,
      name: data.name,
      description: data.description ?? '',
      tags: JSON.stringify(data.tags ?? []),
      fps: data.fps,
      duration: data.duration,
      frame_count: data.frameCount,
      skeleton_type: data.skeletonType,
      poses_json: JSON.stringify(data.poses),
      beat_markers_json: JSON.stringify(data.beatMarkers ?? []),
      keyframe_flags: JSON.stringify(data.keyframeFlags ?? []),
      motion_intensity: data.motionIntensity ?? 0,
      primary_joints: JSON.stringify(data.primaryJoints ?? []),
      is_loopable: data.isLoopable ? 1 : 0,
      source: data.source,
      source_video_path: data.sourceVideoPath ?? null,
      thumbnail: data.thumbnail ?? null,
      created_at: data.createdAt,
      updated_at: data.updatedAt
    })
    this.bumpTags(data.tags ?? [])
  }

  getMotion(id: string): MotionData | null {
    const row = this.db.prepare('SELECT * FROM motions WHERE id = ?').get(id) as
      | MotionRow
      | undefined
    return row ? this.rowToMotionData(row) : null
  }

  listMotions(options: ListMotionsOptions = {}): ListMotionsResult {
    const where: string[] = []
    const params: Record<string, unknown> = {}

    if (options.search) {
      where.push('(LOWER(name) LIKE @q OR LOWER(description) LIKE @q)')
      params.q = `%${options.search.toLowerCase()}%`
    }
    if (options.source) {
      where.push('source = @source')
      params.source = options.source
    }
    for (let i = 0; i < (options.tags ?? []).length; i++) {
      where.push(`tags LIKE @tag${i}`)
      params[`tag${i}`] = `"${options.tags![i]}"`
    }

    const whereSql = where.length ? `WHERE ${where.join(' AND ')}` : ''
    const sortCol =
      options.sortBy === 'name'
        ? 'name'
        : options.sortBy === 'intensity'
          ? 'motion_intensity'
          : options.sortBy === 'created_at'
            ? 'created_at'
            : 'updated_at'
    const order = options.sortOrder === 'asc' ? 'ASC' : 'DESC'
    const limit = options.limit ?? 200
    const offset = options.offset ?? 0

    const total = (
      this.db
        .prepare(`SELECT COUNT(*) as c FROM motions ${whereSql}`)
        .get(params) as { c: number }
    ).c

    const rows = this.db
      .prepare(
        `SELECT * FROM motions ${whereSql} ORDER BY ${sortCol} ${order} LIMIT ${limit} OFFSET ${offset}`
      )
      .all(params) as MotionRow[]

    return { motions: rows.map((r) => this.rowToMotionMeta(r)), total }
  }

  updateMotion(id: string, partial: Partial<MotionData>): void {
    const sets: string[] = []
    const params: Record<string, unknown> = { id }
    if (partial.name !== undefined) {
      sets.push('name = @name')
      params.name = partial.name
    }
    if (partial.description !== undefined) {
      sets.push('description = @description')
      params.description = partial.description
    }
    if (partial.tags !== undefined) {
      sets.push('tags = @tags')
      params.tags = JSON.stringify(partial.tags)
    }
    if (partial.beatMarkers !== undefined) {
      sets.push('beat_markers_json = @bm')
      params.bm = JSON.stringify(partial.beatMarkers)
    }
    if (partial.keyframeFlags !== undefined) {
      sets.push('keyframe_flags = @kf')
      params.kf = JSON.stringify(partial.keyframeFlags)
    }
    if (partial.thumbnail !== undefined) {
      sets.push('thumbnail = @thumb')
      params.thumb = partial.thumbnail
    }
    sets.push("updated_at = @now")
    params.now = new Date().toISOString()
    if (sets.length === 0) return
    this.db.prepare(`UPDATE motions SET ${sets.join(', ')} WHERE id = @id`).run(params)
  }

  deleteMotion(id: string): void {
    this.db.prepare('DELETE FROM motions WHERE id = ?').run(id)
  }

  getPopularTags(limit = 20): { name: string; count: number }[] {
    const rows = this.db
      .prepare('SELECT name, usage_count as count FROM tags ORDER BY usage_count DESC LIMIT ?')
      .all(limit) as { name: string; count: number }[]
    return rows
  }

  // ===== Project CRUD =====

  saveProject(data: ProjectFile): void {
    const id = (data as ProjectFile & { id?: string }).id ?? data.metadata.name
    this.db
      .prepare(
        `INSERT OR REPLACE INTO projects (id, name, project_json, thumbnail, updated_at)
         VALUES (@id, @name, @json, @thumb, @updated)`
      )
      .run({
        id,
        name: data.metadata.name,
        json: JSON.stringify(data),
        thumb: null,
        updated: new Date().toISOString()
      })
  }

  getProject(id: string): ProjectFile | null {
    const row = this.db.prepare('SELECT * FROM projects WHERE id = ?').get(id) as
      | ProjectRow
      | undefined
    return row ? (JSON.parse(row.project_json) as ProjectFile) : null
  }

  listProjects(): ProjectListItem[] {
    const rows = this.db
      .prepare('SELECT id, name, thumbnail, updated_at FROM projects ORDER BY updated_at DESC')
      .all() as (ProjectRow & { updated_at: string })[]
    return rows.map((r) => ({
      id: r.id,
      name: r.name,
      thumbnail: r.thumbnail ?? undefined,
      updatedAt: r.updated_at
    }))
  }

  // ===== Settings & stats =====

  getSetting(key: string): string | null {
    const row = this.db.prepare('SELECT value FROM settings WHERE key = ?').get(key) as
      | { value: string }
      | undefined
    return row ? row.value : null
  }
  setSetting(key: string, value: string): void {
    this.db
      .prepare('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)')
      .run(key, value)
  }

  getStats(): { motionCount: number; projectCount: number; totalStorageBytes: number } {
    const m = this.db.prepare('SELECT COUNT(*) as c, SUM(LENGTH(poses_json)) as s FROM motions').get() as {
      c: number
      s: number | null
    }
    const p = this.db.prepare('SELECT COUNT(*) as c FROM projects').get() as { c: number }
    return {
      motionCount: m.c,
      projectCount: p.c,
      totalStorageBytes: m.s ?? 0
    }
  }

  close(): void {
    this.db.close()
  }

  // ===== helpers =====

  private bumpTags(tags: string[]): void {
    const stmt = this.db.prepare(
      `INSERT INTO tags (name, usage_count) VALUES (?, 1)
       ON CONFLICT(name) DO UPDATE SET usage_count = usage_count + 1`
    )
    for (const t of tags) if (t) stmt.run(t)
  }

  private rowToMotionMeta(r: MotionRow): MotionMeta {
    return {
      id: r.id,
      name: r.name,
      description: r.description,
      duration: r.duration,
      fps: r.fps,
      frameCount: r.frame_count,
      tags: safeParse(r.tags, []),
      motionIntensity: r.motion_intensity,
      source: r.source as MotionMeta['source'],
      thumbnail: r.thumbnail ?? undefined,
      updatedAt: r.updated_at
    }
  }

  private rowToMotionData(r: MotionRow): MotionData {
    return {
      id: r.id,
      name: r.name,
      description: r.description,
      tags: safeParse(r.tags, []),
      fps: r.fps,
      duration: r.duration,
      frameCount: r.frame_count,
      skeletonType: r.skeleton_type as MotionData['skeletonType'],
      poses: safeParse(r.poses_json, []),
      beatMarkers: safeParse(r.beat_markers_json, []),
      keyframeFlags: safeParse(r.keyframe_flags, []),
      motionIntensity: r.motion_intensity,
      primaryJoints: safeParse(r.primary_joints, []),
      isLoopable: !!r.is_loopable,
      source: r.source as MotionData['source'],
      sourceVideoPath: r.source_video_path ?? undefined,
      thumbnail: r.thumbnail ?? undefined,
      createdAt: r.created_at,
      updatedAt: r.updated_at
    }
  }
}

function safeParse<T>(s: string | null | undefined, fallback: T): T {
  if (!s) return fallback
  try {
    return JSON.parse(s) as T
  } catch {
    return fallback
  }
}

interface MotionRow {
  id: string
  name: string
  description: string
  tags: string
  fps: number
  duration: number
  frame_count: number
  skeleton_type: string
  poses_json: string
  beat_markers_json: string
  keyframe_flags: string
  motion_intensity: number
  primary_joints: string
  is_loopable: number
  source: string
  source_video_path: string | null
  thumbnail: string | null
  created_at: string
  updated_at: string
}

interface ProjectRow {
  id: string
  name: string
  project_json: string
  thumbnail: string | null
}
