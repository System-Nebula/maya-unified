/**
 * Anime4K experimental line effects (bloc97) ported to WebGPU compute.
 * Sources: Anime4K_Darken_HQ.glsl / Anime4K_Thin_HQ.glsl
 */
import type { Anime4KPipeline } from 'anime4k-webgpu'

type LineEffectDescriptor = {
  device: GPUDevice
  inputTexture: GPUTexture
}

const TEX_USAGE =
  // TEXTURE_BINDING | STORAGE_BINDING — numeric so module load doesn't need WebGPU globals
  0x04 | 0x08

function storageTex(device: GPUDevice, width: number, height: number) {
  return device.createTexture({
    size: [width, height, 1],
    format: 'rgba16float',
    usage: TEX_USAGE,
  })
}

function dispatch(pass: GPUComputePassEncoder, width: number, height: number) {
  pass.dispatchWorkgroups(Math.ceil(width / 8), Math.ceil(height / 8))
}

const LUMA_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;

fn get_luma(rgba: vec4f) -> f32 {
  return dot(rgba, vec4f(0.299, 0.587, 0.114, 0.0));
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let color = textureLoad(tex_in, pixel.xy, 0);
  textureStore(tex_out, pixel.xy, vec4f(get_luma(color), 0.0, 0.0, 1.0));
}
`

/** Separable Gaussian along X; optional DoG (luma - blur, keep negatives). */
const GAUSS_X_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;
@group(0) @binding(2) var<uniform> params: vec4f; // x=sigma

fn load_x(tex: texture_2d<f32>, x: i32, y: i32) -> f32 {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  return textureLoad(tex, vec2u(u32(cx), u32(cy)), 0).x;
}

fn gaussian(x: f32, s: f32) -> f32 {
  let scaled = x / s;
  return exp(-0.5 * scaled * scaled);
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let sigma = max(params.x, 0.001);
  let half = max(i32(ceil(sigma * 2.0)), 1);
  var g = 0.0;
  var gn = 0.0;
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  for (var i = -8; i <= 8; i++) {
    if (abs(i) > half) { continue; }
    let gf = gaussian(f32(i), sigma);
    g += load_x(tex_in, px + i, py) * gf;
    gn += gf;
  }
  textureStore(tex_out, pixel.xy, vec4f(g / gn, 0.0, 0.0, 1.0));
}
`

const GAUSS_Y_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;
@group(0) @binding(2) var<uniform> params: vec4f; // x=sigma

fn load_x(tex: texture_2d<f32>, x: i32, y: i32) -> f32 {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  return textureLoad(tex, vec2u(u32(cx), u32(cy)), 0).x;
}

fn gaussian(x: f32, s: f32) -> f32 {
  let scaled = x / s;
  return exp(-0.5 * scaled * scaled);
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let sigma = max(params.x, 0.001);
  let half = max(i32(ceil(sigma * 2.0)), 1);
  var g = 0.0;
  var gn = 0.0;
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  for (var i = -8; i <= 8; i++) {
    if (abs(i) > half) { continue; }
    let gf = gaussian(f32(i), sigma);
    g += load_x(tex_in, px, py + i) * gf;
    gn += gf;
  }
  textureStore(tex_out, pixel.xy, vec4f(g / gn, 0.0, 0.0, 1.0));
}
`

/** DoG Y: min(luma - gauss_y(kernel), 0) */
const DARKEN_DIFF_Y_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_luma: texture_2d<f32>;
@group(0) @binding(1) var tex_kernel: texture_2d<f32>;
@group(0) @binding(2) var tex_out: texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var<uniform> params: vec4f; // x=sigma

fn load_x(tex: texture_2d<f32>, x: i32, y: i32) -> f32 {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  return textureLoad(tex, vec2u(u32(cx), u32(cy)), 0).x;
}

fn gaussian(x: f32, s: f32) -> f32 {
  let scaled = x / s;
  return exp(-0.5 * scaled * scaled);
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let sigma = max(params.x, 0.001);
  let half = max(i32(ceil(sigma * 2.0)), 1);
  var g = 0.0;
  var gn = 0.0;
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  for (var i = -8; i <= 8; i++) {
    if (abs(i) > half) { continue; }
    let gf = gaussian(f32(i), sigma);
    g += load_x(tex_kernel, px, py + i) * gf;
    gn += gf;
  }
  let dog = min(load_x(tex_luma, px, py) - (g / gn), 0.0);
  textureStore(tex_out, pixel.xy, vec4f(dog, 0.0, 0.0, 1.0));
}
`

const DARKEN_APPLY_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_kernel: texture_2d<f32>;
@group(0) @binding(2) var tex_out: texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var<uniform> params: vec4f; // x=sigma, y=strength

fn load_x(tex: texture_2d<f32>, x: i32, y: i32) -> f32 {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  return textureLoad(tex, vec2u(u32(cx), u32(cy)), 0).x;
}

fn gaussian(x: f32, s: f32) -> f32 {
  let scaled = x / s;
  return exp(-0.5 * scaled * scaled);
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let sigma = max(params.x, 0.001);
  let strength = params.y;
  let half = max(i32(ceil(sigma * 2.0)), 1);
  var g = 0.0;
  var gn = 0.0;
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  for (var i = -8; i <= 8; i++) {
    if (abs(i) > half) { continue; }
    let gf = gaussian(f32(i), sigma);
    g += load_x(tex_kernel, px, py + i) * gf;
    gn += gf;
  }
  let color = textureLoad(tex_in, pixel.xy, 0);
  textureStore(tex_out, pixel.xy, color + vec4f((g / gn) * strength));
}
`

const SOBEL_X_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;

fn load_x(tex: texture_2d<f32>, x: i32, y: i32) -> f32 {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  return textureLoad(tex, vec2u(u32(cx), u32(cy)), 0).x;
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  let l = load_x(tex_in, px - 1, py);
  let c = load_x(tex_in, px, py);
  let r = load_x(tex_in, px + 1, py);
  let xgrad = -l + r;
  let ygrad = l + c + c + r;
  textureStore(tex_out, pixel.xy, vec4f(xgrad, ygrad, 0.0, 1.0));
}
`

const SOBEL_Y_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;

fn load_xy(tex: texture_2d<f32>, x: i32, y: i32) -> vec2f {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  let v = textureLoad(tex, vec2u(u32(cx), u32(cy)), 0);
  return v.xy;
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  let t = load_xy(tex_in, px, py - 1);
  let c = load_xy(tex_in, px, py);
  let b = load_xy(tex_in, px, py + 1);
  let xgrad = (t.x + c.x + c.x + b.x) / 8.0;
  let ygrad = (-t.y + b.y) / 8.0;
  let norm = sqrt(xgrad * xgrad + ygrad * ygrad);
  textureStore(tex_out, pixel.xy, vec4f(pow(norm, 0.7), 0.0, 0.0, 1.0));
}
`

const KERNEL_Y_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_out: texture_storage_2d<rgba16float, write>;

fn load_xy(tex: texture_2d<f32>, x: i32, y: i32) -> vec2f {
  let dim = vec2i(textureDimensions(tex));
  let cx = clamp(x, 0, dim.x - 1);
  let cy = clamp(y, 0, dim.y - 1);
  let v = textureLoad(tex, vec2u(u32(cx), u32(cy)), 0);
  return v.xy;
}

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let px = i32(pixel.x);
  let py = i32(pixel.y);
  let t = load_xy(tex_in, px, py - 1);
  let c = load_xy(tex_in, px, py);
  let b = load_xy(tex_in, px, py + 1);
  let xgrad = (t.x + c.x + c.x + b.x) / 8.0;
  let ygrad = (-t.y + b.y) / 8.0;
  textureStore(tex_out, pixel.xy, vec4f(xgrad, ygrad, 0.0, 1.0));
}
`

const WARP_WGSL = /* wgsl */ `
@group(0) @binding(0) var tex_in: texture_2d<f32>;
@group(0) @binding(1) var tex_grad: texture_2d<f32>;
@group(0) @binding(2) var tex_out: texture_storage_2d<rgba16float, write>;
@group(0) @binding(3) var samp: sampler;
@group(0) @binding(4) var<uniform> params: vec4f; // x=strength (rel), y=unused

@compute @workgroup_size(8, 8)
fn computeMain(@builtin(global_invocation_id) pixel: vec3u) {
  let dim = textureDimensions(tex_out);
  if (pixel.x >= dim.x || pixel.y >= dim.y) { return; }
  let size = vec2f(dim);
  let d = 1.0 / size;
  let relstr = params.x;
  var pos = (vec2f(pixel.xy) + 0.5) / size;
  // ITERATIONS = 1 (HQ default)
  let dn = textureSampleLevel(tex_grad, samp, pos, 0.0).xy;
  let dd = (dn / (length(dn) + 0.01)) * d * relstr;
  pos -= dd;
  let color = textureSampleLevel(tex_in, samp, pos, 0.0);
  textureStore(tex_out, pixel.xy, color);
}
`

type PassBundle = {
  pipeline: GPUComputePipeline
  bindGroup: GPUBindGroup
}

function makeCompute(
  device: GPUDevice,
  label: string,
  code: string,
  layout: GPUBindGroupLayout,
): GPUComputePipeline {
  return device.createComputePipeline({
    label,
    layout: device.createPipelineLayout({ bindGroupLayouts: [layout] }),
    compute: {
      module: device.createShaderModule({ label: `${label} module`, code }),
      entryPoint: 'computeMain',
    },
  })
}

function sigmaBuffer(device: GPUDevice, sigma: number, extra = 0) {
  const buf = device.createBuffer({
    size: 16,
    usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
  })
  device.queue.writeBuffer(buf, 0, new Float32Array([sigma, extra, 0, 0]))
  return buf
}

/** Anime4K Darken_HQ — darkens line art via negative DoG. */
export class DarkenLines implements Anime4KPipeline {
  private readonly width: number
  private readonly height: number
  private readonly output: GPUTexture
  private readonly passes: PassBundle[]

  constructor({ device, inputTexture }: LineEffectDescriptor) {
    this.width = inputTexture.width
    this.height = inputTexture.height
    const sigma = (1.0 * this.height) / 1080.0
    const strength = 1.5

    const luma = storageTex(device, this.width, this.height)
    const gaussX = storageTex(device, this.width, this.height)
    const dog = storageTex(device, this.width, this.height)
    const gaussX2 = storageTex(device, this.width, this.height)
    this.output = storageTex(device, this.width, this.height)

    const sigmaBuf = sigmaBuffer(device, sigma)
    const applyBuf = sigmaBuffer(device, sigma, strength)

    const ioLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 1,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
      ],
    })
    const gaussLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 1,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
        { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      ],
    })
    const diffLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        { binding: 1, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 2,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
        { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      ],
    })
    const applyLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        { binding: 1, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 2,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
        { binding: 3, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      ],
    })

    this.passes = [
      {
        pipeline: makeCompute(device, 'darken-luma', LUMA_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: inputTexture.createView() },
            { binding: 1, resource: luma.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'darken-gauss-x1', GAUSS_X_WGSL, gaussLayout),
        bindGroup: device.createBindGroup({
          layout: gaussLayout,
          entries: [
            { binding: 0, resource: luma.createView() },
            { binding: 1, resource: gaussX.createView() },
            { binding: 2, resource: { buffer: sigmaBuf } },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'darken-diff-y', DARKEN_DIFF_Y_WGSL, diffLayout),
        bindGroup: device.createBindGroup({
          layout: diffLayout,
          entries: [
            { binding: 0, resource: luma.createView() },
            { binding: 1, resource: gaussX.createView() },
            { binding: 2, resource: dog.createView() },
            { binding: 3, resource: { buffer: sigmaBuf } },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'darken-gauss-x2', GAUSS_X_WGSL, gaussLayout),
        bindGroup: device.createBindGroup({
          layout: gaussLayout,
          entries: [
            { binding: 0, resource: dog.createView() },
            { binding: 1, resource: gaussX2.createView() },
            { binding: 2, resource: { buffer: sigmaBuf } },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'darken-apply', DARKEN_APPLY_WGSL, applyLayout),
        bindGroup: device.createBindGroup({
          layout: applyLayout,
          entries: [
            { binding: 0, resource: inputTexture.createView() },
            { binding: 1, resource: gaussX2.createView() },
            { binding: 2, resource: this.output.createView() },
            { binding: 3, resource: { buffer: applyBuf } },
          ],
        }),
      },
    ]
  }

  updateParam(_param: string, _value: unknown): void {
    /* fixed HQ defaults */
  }

  pass(encoder: GPUCommandEncoder): void {
    for (const p of this.passes) {
      const c = encoder.beginComputePass()
      c.setPipeline(p.pipeline)
      c.setBindGroup(0, p.bindGroup)
      dispatch(c, this.width, this.height)
      c.end()
    }
  }

  getOutputTexture(): GPUTexture {
    return this.output
  }
}

/** Anime4K Thin_HQ — warps samples along line gradients to thin strokes. */
export class ThinLines implements Anime4KPipeline {
  private readonly width: number
  private readonly height: number
  private readonly output: GPUTexture
  private readonly passes: PassBundle[]

  constructor({ device, inputTexture }: LineEffectDescriptor) {
    this.width = inputTexture.width
    this.height = inputTexture.height
    const sigma = (2.0 * this.height) / 1080.0
    const strength = 0.6
    const relstr = (this.height / 1080.0) * strength

    const luma = storageTex(device, this.width, this.height)
    const sobelX = storageTex(device, this.width, this.height)
    const sobelY = storageTex(device, this.width, this.height)
    const gaussX = storageTex(device, this.width, this.height)
    const gaussY = storageTex(device, this.width, this.height)
    const kernX = storageTex(device, this.width, this.height)
    const kernY = storageTex(device, this.width, this.height)
    this.output = storageTex(device, this.width, this.height)

    const sigmaBuf = sigmaBuffer(device, sigma)
    const warpBuf = sigmaBuffer(device, relstr)

    const sampler = device.createSampler({
      magFilter: 'linear',
      minFilter: 'linear',
      addressModeU: 'clamp-to-edge',
      addressModeV: 'clamp-to-edge',
    })

    const ioLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 1,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
      ],
    })
    const gaussLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 1,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
        { binding: 2, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      ],
    })
    const warpLayout = device.createBindGroupLayout({
      entries: [
        { binding: 0, visibility: GPUShaderStage.COMPUTE, texture: {} },
        { binding: 1, visibility: GPUShaderStage.COMPUTE, texture: {} },
        {
          binding: 2,
          visibility: GPUShaderStage.COMPUTE,
          storageTexture: { access: 'write-only', format: 'rgba16float' },
        },
        { binding: 3, visibility: GPUShaderStage.COMPUTE, sampler: {} },
        { binding: 4, visibility: GPUShaderStage.COMPUTE, buffer: { type: 'uniform' } },
      ],
    })

    this.passes = [
      {
        pipeline: makeCompute(device, 'thin-luma', LUMA_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: inputTexture.createView() },
            { binding: 1, resource: luma.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-sobel-x', SOBEL_X_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: luma.createView() },
            { binding: 1, resource: sobelX.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-sobel-y', SOBEL_Y_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: sobelX.createView() },
            { binding: 1, resource: sobelY.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-gauss-x', GAUSS_X_WGSL, gaussLayout),
        bindGroup: device.createBindGroup({
          layout: gaussLayout,
          entries: [
            { binding: 0, resource: sobelY.createView() },
            { binding: 1, resource: gaussX.createView() },
            { binding: 2, resource: { buffer: sigmaBuf } },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-gauss-y', GAUSS_Y_WGSL, gaussLayout),
        bindGroup: device.createBindGroup({
          layout: gaussLayout,
          entries: [
            { binding: 0, resource: gaussX.createView() },
            { binding: 1, resource: gaussY.createView() },
            { binding: 2, resource: { buffer: sigmaBuf } },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-kern-x', SOBEL_X_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: gaussY.createView() },
            { binding: 1, resource: kernX.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-kern-y', KERNEL_Y_WGSL, ioLayout),
        bindGroup: device.createBindGroup({
          layout: ioLayout,
          entries: [
            { binding: 0, resource: kernX.createView() },
            { binding: 1, resource: kernY.createView() },
          ],
        }),
      },
      {
        pipeline: makeCompute(device, 'thin-warp', WARP_WGSL, warpLayout),
        bindGroup: device.createBindGroup({
          layout: warpLayout,
          entries: [
            { binding: 0, resource: inputTexture.createView() },
            { binding: 1, resource: kernY.createView() },
            { binding: 2, resource: this.output.createView() },
            { binding: 3, resource: sampler },
            { binding: 4, resource: { buffer: warpBuf } },
          ],
        }),
      },
    ]
  }

  updateParam(_param: string, _value: unknown): void {
    /* fixed HQ defaults */
  }

  pass(encoder: GPUCommandEncoder): void {
    for (const p of this.passes) {
      const c = encoder.beginComputePass()
      c.setPipeline(p.pipeline)
      c.setBindGroup(0, p.bindGroup)
      dispatch(c, this.width, this.height)
      c.end()
    }
  }

  getOutputTexture(): GPUTexture {
    return this.output
  }
}
