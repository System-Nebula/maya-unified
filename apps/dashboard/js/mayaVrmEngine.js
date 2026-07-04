/**
 * Browser VRM avatar renderer — Three.js + @pixiv/three-vrm.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";
import { VrmLipSync } from "/dashboard/js/mayaVrmLipSync.js";
import { VrmExpressionController } from "/dashboard/js/mayaVrmExpressions.js";
import { loadMixamoClipForVrm, resolveAnimationUrl } from "/dashboard/js/mayaVrmMixamo.js";

export const DEFAULT_VRM_LOCAL = "Yuki.vrm";
export const DEFAULT_IDLE_ANIM = "Idle.fbx";

export function resolveVrmUrl(model) {
  const raw = String(model || "").trim();
  if (!raw) return `/api/voice/agent/vrm/file?name=${encodeURIComponent(DEFAULT_VRM_LOCAL)}`;
  if (/^https?:\/\//i.test(raw)) return raw;
  const name = raw.replace(/^.*[/\\]/, "");
  return `/api/voice/agent/vrm/file?name=${encodeURIComponent(name)}`;
}

export class MayaVrmEngine {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.opts = opts;
    this.lookAtCamera = opts.lookAtCamera !== false;
    this.cameraDistance = Number(opts.cameraDistance ?? 1.8);
    this.idleEnabled = opts.idleEnabled !== false;
    this.idleAnimation = opts.idleAnimation || DEFAULT_IDLE_ANIM;

    this.lipSync = new VrmLipSync({
      gain: opts.mouthGain ?? 6,
      smoothing: opts.mouthSmoothing ?? 0.5,
      mode: opts.lipSyncMode === "amplitude" ? "amplitude" : "viseme",
    });
    this.expressions = new VrmExpressionController();

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x000000, 0);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(28, 1, 0.05, 30);
    this.camera.position.set(0, 1.35, this.cameraDistance);

    const hemi = new THREE.HemisphereLight(0xffffff, 0x444466, 0.85);
    this.scene.add(hemi);
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(1.2, 1.8, 2.4);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xaaccff, 0.35);
    fill.position.set(-1.5, 0.6, -1);
    this.scene.add(fill);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 0.8;
    this.controls.maxDistance = 4.5;
    this.controls.target.set(0, 1.35, 0);
    this.controls.update();

    this.clock = new THREE.Clock();
    this.vrm = null;
    this._loader = new GLTFLoader();
    this._loader.setWithCredentials(true);
    this._loader.register((parser) => new VRMLoaderPlugin(parser));
    this._mixer = null;
    this._idleAction = null;
    this._gestureAction = null;
    this._gestureFinishHandler = null;
    this._returnIdleGuard = 0;
    this._headSwayRamp = 1;
    this._lastLevel = 0;
    this._lastBands = [];
    this._raf = 0;
    this._loadToken = 0;
    this._resizeObs = null;
    this.lipSyncInfo = null;
    this.exprInfo = null;
    this._headPhase = 0;
    this._lookTarget = new THREE.Vector3();
    this._headBone = null;
    this._neckBone = null;
    this._headSwayEuler = new THREE.Euler(0, 0, 0, "YXZ");
    this._headSwayQuat = new THREE.Quaternion();
    this._headBaseQuat = new THREE.Quaternion();
    this._neckBaseQuat = new THREE.Quaternion();
  }

  resize() {
    const parent = this.canvas.parentElement;
    if (!parent) return;
    const w = Math.max(1, parent.clientWidth);
    const h = Math.max(1, parent.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  watchResize() {
    this.resize();
    if (typeof ResizeObserver === "undefined") return;
    const parent = this.canvas.parentElement;
    if (!parent) return;
    this._resizeObs = new ResizeObserver(() => this.resize());
    this._resizeObs.observe(parent);
  }

  async loadModel(url) {
    const token = ++this._loadToken;
    await this._disposeVrm();
    const gltf = await this._loader.loadAsync(url);
    if (token !== this._loadToken) return;
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error("File loaded but is not a VRM model");

    try {
      VRMUtils.rotateVRM0(vrm);
    } catch (_) {
      /* VRM 1.x */
    }

    this.scene.add(vrm.scene);
    this.vrm = vrm;
    this.lipSyncInfo = this.lipSync.bind(vrm);
    const mouthKeys = Object.values(this.lipSyncInfo?.keys || {});
    this.exprInfo = this.expressions.bind(vrm, { extraProtected: mouthKeys });
    this._mixer = new THREE.AnimationMixer(vrm.scene);

    const box = new THREE.Box3().setFromObject(vrm.scene);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const height = Math.max(size.y, 0.01);
    const dist = Math.max(this.cameraDistance, height * 1.35);
    this.controls.target.copy(center);
    this.camera.position.set(center.x, center.y + height * 0.05, center.z + dist);
    this.controls.update();

    if (this.lookAtCamera && vrm.lookAt) {
      vrm.lookAt.target = new THREE.Object3D();
      this.scene.add(vrm.lookAt.target);
      const applier = vrm.lookAt.applier;
      if (applier) {
        if ("yawMax" in applier) applier.yawMax = Math.max(applier.yawMax || 0, 60);
        if ("pitchMax" in applier) applier.pitchMax = Math.max(applier.pitchMax || 0, 45);
      }
    }

    this._headBone = vrm.humanoid?.getNormalizedBoneNode?.("head") || null;
    this._neckBone = vrm.humanoid?.getNormalizedBoneNode?.("neck") || null;
    if (this._headBone) this._headBaseQuat.copy(this._headBone.quaternion);
    if (this._neckBone) this._neckBaseQuat.copy(this._neckBone.quaternion);

    if (this.idleEnabled) {
      await this._loadIdleAnimation(token);
    }
  }

  async _loadIdleAnimation(token) {
    const url = resolveAnimationUrl(this.idleAnimation);
    if (!url || !this.vrm) return;
    try {
      const clip = await loadMixamoClipForVrm(this.vrm, url);
      if (!clip || token !== this._loadToken || !this._mixer || !this.vrm) return;
      this.vrm.humanoid?.resetNormalizedPose?.();
      this._idleAction = this._mixer.clipAction(clip);
      this._idleAction.setLoop(THREE.LoopRepeat, Infinity);
      this._idleAction.play();
    } catch (_) {
      /* idle clip optional */
    }
  }

  async setIdleAnimation(name) {
    this.idleAnimation = String(name || DEFAULT_IDLE_ANIM).trim() || DEFAULT_IDLE_ANIM;
    if (!this.vrm || !this.idleEnabled) return;
    const token = this._loadToken;
    if (this._idleAction) {
      this._idleAction.stop();
      this._idleAction = null;
    }
    await this._loadIdleAnimation(token);
  }

  _clearGestureListener() {
    if (this._gestureFinishHandler && this._mixer) {
      this._mixer.removeEventListener("finished", this._gestureFinishHandler);
    }
    this._gestureFinishHandler = null;
  }

  stopGesture(fadeOut = 0.45) {
    this._clearGestureListener();
    const gesture = this._gestureAction;
    this._gestureAction = null;
    if (!gesture || !this._mixer) return;
    this._headSwayRamp = 0;
    this._returnIdleGuard = fadeOut + 0.1;
    if (this._idleAction) {
      this._idleAction.enabled = true;
      gesture.crossFadeTo(this._idleAction, fadeOut, true);
      this._idleAction.play();
    } else {
      gesture.fadeOut(fadeOut);
    }
  }

  /**
   * Play a one-shot or looping Mixamo gesture on top of idle.
   * @param {string} name animation filename e.g. Wave.fbx
   * @param {{ loop?: boolean, fadeIn?: number, fadeOut?: number }} [opts]
   */
  async playAnimation(name, opts = {}) {
    if (!this.vrm || !this._mixer) return false;
    const loop = !!opts.loop;
    const fadeIn = Math.max(0.08, Number(opts.fadeIn ?? 0.32));
    const fadeOut = Math.max(0.12, Number(opts.fadeOut ?? 0.55));
    const url = resolveAnimationUrl(name);
    if (!url) return false;

    let clip;
    try {
      clip = await loadMixamoClipForVrm(this.vrm, url);
    } catch (_) {
      return false;
    }
    if (!clip || !this._mixer || !this.vrm) return false;

    this._clearGestureListener();
    if (this._gestureAction) {
      this._gestureAction.stop();
      this._gestureAction = null;
    }

    const action = this._mixer.clipAction(clip);
    action.reset();
    action.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1);
    action.clampWhenFinished = !loop;
    action.setEffectiveWeight(1);

    if (this._idleAction) {
      this._idleAction.enabled = true;
      this._idleAction.play();
      if (loop) {
        this._idleAction.crossFadeTo(action, fadeIn, true);
      } else {
        this._idleAction.crossFadeTo(action, fadeIn, true);
      }
    } else {
      action.fadeIn(fadeIn);
    }
    action.play();
    this._gestureAction = action;
    this._headSwayRamp = 0;
    this._returnIdleGuard = fadeIn + 0.05;

    if (!loop) {
      this._gestureFinishHandler = (e) => {
        if (e.action !== action) return;
        this._clearGestureListener();
        this._gestureAction = null;
        this._headSwayRamp = 0;
        this._returnIdleGuard = fadeOut + 0.15;
        if (this._idleAction) {
          this._idleAction.enabled = true;
          action.crossFadeTo(this._idleAction, fadeOut, true);
          this._idleAction.play();
        } else {
          action.fadeOut(fadeOut);
        }
      };
      this._mixer.addEventListener("finished", this._gestureFinishHandler);
    }
    return true;
  }

  setIdleEnabled(v) {
    this.idleEnabled = !!v;
    if (!v && this._idleAction) {
      this._idleAction.stop();
      this._idleAction = null;
    } else if (v && this.vrm && !this._idleAction) {
      this._loadIdleAnimation(this._loadToken);
    }
  }

  setMood(mood) {
    this.expressions.setMood(mood);
  }

  easeMoodToIdle() {
    this.expressions.easeToIdle();
  }

  getMood() {
    return this.expressions.getMood();
  }

  /** @deprecated Lips follow setAudioFrame(); does not touch idle/body animation. */
  setSpeaking(_v) {
    /* no-op — mouth sync is layered on top of idle via setAudioFrame only */
  }

  setAudioFrame(frame = {}) {
    this._lastLevel = Math.max(0, Number(frame.level) || 0);
    this._lastBands = Array.isArray(frame.bands) ? frame.bands : [];
    this.lipSync.pushFrame({
      speaking: !!frame.speaking || this._lastLevel > 0.002,
      level: this._lastLevel,
      bands: this._lastBands,
    });
  }

  setMouthGain(v) {
    this.lipSync.setGain(v);
  }

  setMouthSmoothing(v) {
    this.lipSync.setSmoothing(v);
  }

  setLipSyncMode(mode) {
    this.lipSync.setMode(mode);
  }

  _idleHeadSway() {
    const t = this._headPhase;
    const yaw = Math.sin(t * 0.28) * 0.28 + Math.sin(t * 0.46 + 2.1) * 0.12;
    const pitch = Math.sin(t * 0.2 + 0.8) * 0.16 + Math.sin(t * 0.34 + 1.4) * 0.08;
    const roll = Math.sin(t * 0.16 + 4.2) * 0.07;
    return { yaw, pitch, roll };
  }

  _updateIdleHead(delta, intensity = 1) {
    if (!this.vrm || !this.idleEnabled) return;

    this._headPhase += delta;
    const amp = Math.max(0, Math.min(1, intensity));
    const { yaw, pitch, roll } = this._idleHeadSway();
    const dist = Math.max(0.8, this.camera.position.distanceTo(this.controls.target));
    const aim = dist * 0.55 * amp;

    if (this.lookAtCamera && this.vrm.lookAt?.target) {
      this._lookTarget.copy(this.camera.position);
      this._lookTarget.x += yaw * aim;
      this._lookTarget.y += pitch * aim * 0.85;
      this._lookTarget.z += Math.cos(this._headPhase * 0.25 + 0.5) * aim * 0.45;
      this.vrm.lookAt.target.position.copy(this._lookTarget);
    }

    if (this._neckBone) {
      this._headSwayEuler.set(pitch * 0.35 * amp, yaw * 0.45 * amp, roll * 0.55 * amp);
      this._headSwayQuat.setFromEuler(this._headSwayEuler);
      this._neckBone.quaternion.copy(this._neckBaseQuat).multiply(this._headSwayQuat);
    }
    if (this._headBone) {
      this._headSwayEuler.set(pitch * 0.55 * amp, yaw * 0.65 * amp, roll * 0.35 * amp);
      this._headSwayQuat.setFromEuler(this._headSwayEuler);
      this._headBone.quaternion.copy(this._headBaseQuat).multiply(this._headSwayQuat);
    }
  }

  _resetIdleHeadBases() {
    if (this._neckBone) this._neckBaseQuat.copy(this._neckBone.quaternion);
    if (this._headBone) this._headBaseQuat.copy(this._headBone.quaternion);
  }

  start() {
    if (this._raf) return;
    this.clock.start();
    const tick = () => {
      this._raf = requestAnimationFrame(tick);
      const delta = this.clock.getDelta();
      if (this.expressions) {
        this.expressions.update(delta);
      }
      this.lipSync.update(delta);
      if (this._mixer) {
        if (this._returnIdleGuard > 0) {
          this._returnIdleGuard = Math.max(0, this._returnIdleGuard - delta);
        }
        this._mixer.update(delta);
        if (this.idleEnabled && !this._gestureAction) {
          if (this._headSwayRamp < 1) {
            this._headSwayRamp = Math.min(1, this._headSwayRamp + delta / 0.7);
          }
          this._resetIdleHeadBases();
          this._updateIdleHead(delta, this._headSwayRamp);
        }
      } else if (this.idleEnabled && !this._gestureAction) {
        this._headSwayRamp = 1;
        this._resetIdleHeadBases();
        this._updateIdleHead(delta, 1);
      }
      if (this.vrm) {
        if (!this.idleEnabled && this.lookAtCamera && this.vrm.lookAt?.target) {
          this.vrm.lookAt.target.position.copy(this.camera.position);
        }
        this.vrm.update(delta);
      }
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    tick();
  }

  async _disposeVrm() {
    if (!this.vrm) return;
    this.lipSync.reset();
    this.expressions.reset();
    this._clearGestureListener();
    this._gestureAction = null;
    if (this._idleAction) {
      this._idleAction.stop();
      this._idleAction = null;
    }
    if (this._mixer) {
      this._mixer.stopAllAction();
      this._mixer = null;
    }
    try {
      if (this.vrm.lookAt?.target) {
        this.scene.remove(this.vrm.lookAt.target);
      }
      VRMUtils.deepDispose(this.vrm.scene);
    } catch (_) {
      this.scene.remove(this.vrm.scene);
    }
    this.vrm = null;
    this.lipSyncInfo = null;
    this.exprInfo = null;
    this._headBone = null;
    this._neckBone = null;
  }

  dispose() {
    this._loadToken += 1;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = 0;
    }
    this._resizeObs?.disconnect();
    this._resizeObs = null;
    this._disposeVrm();
    this.controls?.dispose();
    this.renderer?.dispose();
  }
}
