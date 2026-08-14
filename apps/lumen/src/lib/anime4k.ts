/**
 * Anime4K (bloc97) via WebGPU — https://github.com/bloc97/Anime4K
 * Presets: anime4k-webgpu (Mode A/B/C/AA/BB/CA).
 * Line effects: local WebGPU port of Darken_HQ / Thin_HQ.
 */
import {
  ModeA,
  ModeAA,
  ModeB,
  ModeBB,
  ModeC,
  ModeCA,
  type Anime4KPipeline,
} from 'anime4k-webgpu'
import { DarkenLines, ThinLines } from './anime4kLineEffects'

const ENABLED_KEY = 'cinemaya:anime4k'
const SETTINGS_KEY = 'cinemaya:anime4k-settings'

export type Anime4KPreset = 'A' | 'B' | 'C' | 'AA' | 'BB' | 'CA'
export type Anime4KWorkgroup = '8x8' | '16x16' | '32x8'

export type Anime4KSettings = {
  preset: Anime4KPreset
  darkenLines: boolean
  thinLines: boolean
  workgroup: Anime4KWorkgroup
}

export const DEFAULT_ANIME4K_SETTINGS: Anime4KSettings = {
  preset: 'A',
  darkenLines: false,
  thinLines: false,
  workgroup: '8x8',
}

export const ANIME4K_PRESETS: {
  id: Anime4KPreset
  title: string
  subtitle: string
}[] = [
  { id: 'A', title: 'Mode A', subtitle: 'Most 1080p' },
  { id: 'B', title: 'Mode B', subtitle: 'Soft restore' },
  { id: 'C', title: 'Mode C', subtitle: 'Denoise' },
  { id: 'AA', title: 'A+A', subtitle: 'Best quality' },
  { id: 'BB', title: 'B+B', subtitle: 'Double soft' },
  { id: 'CA', title: 'C+A', subtitle: 'Denoise+A' },
]

export const ANIME4K_WORKGROUPS: {
  id: Anime4KWorkgroup
  title: string
  subtitle: string
  supported: boolean
}[] = [
  { id: '8x8', title: '8×8', subtitle: 'Compatible', supported: true },
  { id: '16x16', title: '16×16', subtitle: 'Faster', supported: false },
  { id: '32x8', title: '32×8', subtitle: 'Wide', supported: false },
]

const FULLSCREEN_QUAD = /* wgsl */ `
struct VertexOutput {
  @builtin(position) Position : vec4f,
  @location(0) fragUV : vec2f,
}
@vertex
fn vert_main(@builtin(vertex_index) VertexIndex : u32) -> VertexOutput {
  const pos = array(
    vec2( 1.0,  1.0),
    vec2( 1.0, -1.0),
    vec2(-1.0, -1.0),
    vec2( 1.0,  1.0),
    vec2(-1.0, -1.0),
    vec2(-1.0,  1.0),
  );
  const uv = array(
    vec2(1.0, 0.0),
    vec2(1.0, 1.0),
    vec2(0.0, 1.0),
    vec2(1.0, 0.0),
    vec2(0.0, 1.0),
    vec2(0.0, 0.0),
  );
  var output : VertexOutput;
  output.Position = vec4(pos[VertexIndex], 0.0, 1.0);
  output.fragUV = uv[VertexIndex];
  return output;
}
`

const SAMPLE_TEXTURE = /* wgsl */ `
@group(0) @binding(1) var mySampler: sampler;
@group(0) @binding(2) var myTexture: texture_2d<f32>;
@fragment
fn main(@location(0) fragUV : vec2f) -> @location(0) vec4f {
  return textureSample(myTexture, mySampler, fragUV);
}
`

export function isAnime4KSupported(): boolean {
  if (typeof navigator === 'undefined' || typeof window === 'undefined') return false
  // WebGPU is only exposed in secure contexts (https / localhost). LAN + Tailscale
  // http://192.x / http://100.x pages leave navigator.gpu undefined even on capable GPUs.
  if (!window.isSecureContext) return false
  return Boolean(navigator.gpu)
}

/** Human-readable reason Anime4K can't run (or null if it can). */
export function anime4kUnsupportedReason(): string | null {
  if (typeof navigator === 'undefined' || typeof window === 'undefined') {
    return 'WebGPU is not available'
  }
  if (!window.isSecureContext) {
    return 'WebGPU needs https:// or http://localhost — LAN/Tailscale HTTP hides the GPU API'
  }
  if (!navigator.gpu) return 'WebGPU is not available in this browser'
  return null
}

export function readAnime4KEnabled(): boolean {
  try {
    return localStorage.getItem(ENABLED_KEY) === '1'
  } catch {
    return false
  }
}

export function saveAnime4KEnabled(on: boolean) {
  try {
    localStorage.setItem(ENABLED_KEY, on ? '1' : '0')
  } catch {
    /* ignore */
  }
}

export function readAnime4KSettings(): Anime4KSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (!raw) return { ...DEFAULT_ANIME4K_SETTINGS }
    const parsed = JSON.parse(raw) as Partial<Anime4KSettings>
    return {
      ...DEFAULT_ANIME4K_SETTINGS,
      ...parsed,
      workgroup: '8x8', // WebGPU shaders are compiled at 8×8
    }
  } catch {
    return { ...DEFAULT_ANIME4K_SETTINGS }
  }
}

export function saveAnime4KSettings(settings: Anime4KSettings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch {
    /* ignore */
  }
}

export type Anime4KSession = {
  stop: () => void
}

function fitCanvasSize(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
  const vw = Math.max(1, video.videoWidth || 1280)
  const vh = Math.max(1, video.videoHeight || 720)
  const maxEdge = 2560
  const scale = Math.min(2, maxEdge / Math.max(vw, vh))
  canvas.width = Math.max(2, Math.round(vw * scale))
  canvas.height = Math.max(2, Math.round(vh * scale))
  return { width: canvas.width, height: canvas.height }
}

function buildPreset(
  preset: Anime4KPreset,
  device: GPUDevice,
  inputTexture: GPUTexture,
  nativeDimensions: { width: number; height: number },
  targetDimensions: { width: number; height: number },
): Anime4KPipeline {
  const desc = { device, inputTexture, nativeDimensions, targetDimensions }
  switch (preset) {
    case 'B':
      return new ModeB(desc)
    case 'C':
      return new ModeC(desc)
    case 'AA':
      return new ModeAA(desc)
    case 'BB':
      return new ModeBB(desc)
    case 'CA':
      return new ModeCA(desc)
    case 'A':
    default:
      return new ModeA(desc)
  }
}

export async function startAnime4K(
  video: HTMLVideoElement,
  canvas: HTMLCanvasElement,
  settings: Anime4KSettings = readAnime4KSettings(),
): Promise<Anime4KSession> {
  if (!navigator.gpu) throw new Error('WebGPU is not available in this browser')

  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
    await new Promise<void>((resolve, reject) => {
      const onReady = () => {
        cleanup()
        resolve()
      }
      const onErr = () => {
        cleanup()
        reject(new Error('Video failed before Anime4K could start'))
      }
      const cleanup = () => {
        video.removeEventListener('loadeddata', onReady)
        video.removeEventListener('error', onErr)
      }
      video.addEventListener('loadeddata', onReady)
      video.addEventListener('error', onErr)
    })
  }

  const adapter = await navigator.gpu.requestAdapter()
  if (!adapter) throw new Error('No WebGPU adapter')
  const device = await adapter.requestDevice()
  const context = canvas.getContext('webgpu')
  if (!context) {
    device.destroy()
    throw new Error('Could not create WebGPU canvas context')
  }

  const presentationFormat = navigator.gpu.getPreferredCanvasFormat()
  const target = fitCanvasSize(video, canvas)
  context.configure({
    device,
    format: presentationFormat,
    alphaMode: 'premultiplied',
  })

  const width = Math.max(1, video.videoWidth)
  const height = Math.max(1, video.videoHeight)

  const videoFrameTexture = device.createTexture({
    size: [width, height, 1],
    format: 'rgba16float',
    usage:
      GPUTextureUsage.TEXTURE_BINDING |
      GPUTextureUsage.COPY_DST |
      GPUTextureUsage.RENDER_ATTACHMENT,
  })

  // Mode preset → optional Thin → optional Darken (thin first so darken can
  // restore contrast after warping lightens strokes).
  const pipelines: Anime4KPipeline[] = []
  const preset = buildPreset(
    settings.preset,
    device,
    videoFrameTexture,
    { width, height },
    target,
  )
  pipelines.push(preset)
  let current = preset.getOutputTexture()

  if (settings.thinLines) {
    const thin = new ThinLines({ device, inputTexture: current })
    pipelines.push(thin)
    current = thin.getOutputTexture()
  }
  if (settings.darkenLines) {
    const darken = new DarkenLines({ device, inputTexture: current })
    pipelines.push(darken)
    current = darken.getOutputTexture()
  }

  const renderBindGroupLayout = device.createBindGroupLayout({
    entries: [
      { binding: 1, visibility: GPUShaderStage.FRAGMENT, sampler: {} },
      { binding: 2, visibility: GPUShaderStage.FRAGMENT, texture: {} },
    ],
  })

  const renderPipeline = device.createRenderPipeline({
    layout: device.createPipelineLayout({ bindGroupLayouts: [renderBindGroupLayout] }),
    vertex: {
      module: device.createShaderModule({ code: FULLSCREEN_QUAD }),
      entryPoint: 'vert_main',
    },
    fragment: {
      module: device.createShaderModule({ code: SAMPLE_TEXTURE }),
      entryPoint: 'main',
      targets: [{ format: presentationFormat }],
    },
    primitive: { topology: 'triangle-list' },
  })

  const sampler = device.createSampler({ magFilter: 'linear', minFilter: 'linear' })
  const renderBindGroup = device.createBindGroup({
    layout: renderBindGroupLayout,
    entries: [
      { binding: 1, resource: sampler },
      { binding: 2, resource: current.createView() },
    ],
  })

  let alive = true
  let frameHandle: number | null = null

  const frame = () => {
    if (!alive) return
    try {
      if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        device.queue.copyExternalImageToTexture(
          { source: video },
          { texture: videoFrameTexture },
          [width, height],
        )
      }
      const commandEncoder = device.createCommandEncoder()
      for (const pipeline of pipelines) pipeline.pass(commandEncoder)
      const pass = commandEncoder.beginRenderPass({
        colorAttachments: [
          {
            view: context.getCurrentTexture().createView(),
            clearValue: { r: 0, g: 0, b: 0, a: 1 },
            loadOp: 'clear',
            storeOp: 'store',
          },
        ],
      })
      pass.setPipeline(renderPipeline)
      pass.setBindGroup(0, renderBindGroup)
      pass.draw(6)
      pass.end()
      device.queue.submit([commandEncoder.finish()])
    } catch {
      alive = false
      return
    }
    frameHandle = video.requestVideoFrameCallback(frame)
  }

  frameHandle = video.requestVideoFrameCallback(frame)

  return {
    stop() {
      alive = false
      if (frameHandle != null && typeof video.cancelVideoFrameCallback === 'function') {
        try {
          video.cancelVideoFrameCallback(frameHandle)
        } catch {
          /* ignore */
        }
      }
      frameHandle = null
      try {
        device.destroy()
      } catch {
        /* ignore */
      }
    },
  }
}
