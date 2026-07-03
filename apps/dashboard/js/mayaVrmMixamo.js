/**
 * Retarget Mixamo FBX clips onto a VRM humanoid rig.
 * Based on the official @pixiv/three-vrm humanoidAnimation example.
 */
import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";

const MIXAMO_TO_VRM = {
  mixamorigHips: "hips",
  mixamorigSpine: "spine",
  mixamorigSpine1: "chest",
  mixamorigSpine2: "upperChest",
  mixamorigNeck: "neck",
  mixamorigHead: "head",
  mixamorigLeftShoulder: "leftShoulder",
  mixamorigLeftArm: "leftUpperArm",
  mixamorigLeftForeArm: "leftLowerArm",
  mixamorigLeftHand: "leftHand",
  mixamorigLeftHandThumb1: "leftThumbMetacarpal",
  mixamorigLeftHandThumb2: "leftThumbProximal",
  mixamorigLeftHandThumb3: "leftThumbDistal",
  mixamorigLeftHandIndex1: "leftIndexProximal",
  mixamorigLeftHandIndex2: "leftIndexIntermediate",
  mixamorigLeftHandIndex3: "leftIndexDistal",
  mixamorigLeftHandMiddle1: "leftMiddleProximal",
  mixamorigLeftHandMiddle2: "leftMiddleIntermediate",
  mixamorigLeftHandMiddle3: "leftMiddleDistal",
  mixamorigLeftHandRing1: "leftRingProximal",
  mixamorigLeftHandRing2: "leftRingIntermediate",
  mixamorigLeftHandRing3: "leftRingDistal",
  mixamorigLeftHandPinky1: "leftLittleProximal",
  mixamorigLeftHandPinky2: "leftLittleIntermediate",
  mixamorigLeftHandPinky3: "leftLittleDistal",
  mixamorigRightShoulder: "rightShoulder",
  mixamorigRightArm: "rightUpperArm",
  mixamorigRightForeArm: "rightLowerArm",
  mixamorigRightHand: "rightHand",
  mixamorigRightHandPinky1: "rightLittleProximal",
  mixamorigRightHandPinky2: "rightLittleIntermediate",
  mixamorigRightHandPinky3: "rightLittleDistal",
  mixamorigRightHandRing1: "rightRingProximal",
  mixamorigRightHandRing2: "rightRingIntermediate",
  mixamorigRightHandRing3: "rightRingDistal",
  mixamorigRightHandMiddle1: "rightMiddleProximal",
  mixamorigRightHandMiddle2: "rightMiddleIntermediate",
  mixamorigRightHandMiddle3: "rightMiddleDistal",
  mixamorigRightHandIndex1: "rightIndexProximal",
  mixamorigRightHandIndex2: "rightIndexIntermediate",
  mixamorigRightHandIndex3: "rightIndexDistal",
  mixamorigRightHandThumb1: "rightThumbMetacarpal",
  mixamorigRightHandThumb2: "rightThumbProximal",
  mixamorigRightHandThumb3: "rightThumbDistal",
  mixamorigLeftUpLeg: "leftUpperLeg",
  mixamorigLeftLeg: "leftLowerLeg",
  mixamorigLeftFoot: "leftFoot",
  mixamorigLeftToeBase: "leftToes",
  mixamorigRightUpLeg: "rightUpperLeg",
  mixamorigRightLeg: "rightLowerLeg",
  mixamorigRightFoot: "rightFoot",
  mixamorigRightToeBase: "rightToes",
};

/** mixamorig:LeftArm → mixamorigLeftArm */
export function mixamoRigKey(name) {
  return String(name || "").replace(/^mixamorig:/i, "mixamorig");
}

/** Build lookup for both mixamorigHips and mixamorig:Hips style names. */
export function buildMixamoNodeMap(asset) {
  /** @type {Map<string, THREE.Object3D>} */
  const map = new Map();
  if (!asset) return map;
  asset.traverse((obj) => {
    const key = mixamoRigKey(obj.name);
    if (key.startsWith("mixamorig") && !map.has(key)) {
      map.set(key, obj);
    }
  });
  return map;
}

export function resolveAnimationUrl(name) {
  const raw = String(name || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw)) return raw;
  const base = raw.replace(/^.*[/\\]/, "");
  return `/api/voice/agent/animation/file?name=${encodeURIComponent(base)}`;
}

/** @param {import('@pixiv/three-vrm').VRM} vrm @param {string} url */
export async function loadMixamoClipForVrm(vrm, url) {
  if (!vrm?.humanoid || !url) return null;
  const loader = new FBXLoader();
  const asset = await loader.loadAsync(url);
  const clip =
    THREE.AnimationClip.findByName(asset.animations, "mixamo.com") || asset.animations?.[0];
  if (!clip) return null;
  return retargetMixamoClip(vrm, clip, asset);
}

/**
 * @param {import('@pixiv/three-vrm').VRM} vrm
 * @param {THREE.AnimationClip} clip
 * @param {THREE.Group} [asset]
 */
export function retargetMixamoClip(vrm, clip, asset = null) {
  const tracks = [];
  const restRotationInverse = new THREE.Quaternion();
  const parentRestWorldRotation = new THREE.Quaternion();
  const quatA = new THREE.Quaternion();
  const isVrm0 = vrm.meta?.metaVersion === "0";
  const mixamoNodes = buildMixamoNodeMap(asset);

  let hipsPositionScale = 1;
  const hipsNode = mixamoNodes.get("mixamorigHips");
  const motionHipsHeight = hipsNode?.position?.y;
  const vrmHipsHeight = vrm.humanoid?.normalizedRestPose?.hips?.position?.[1];
  if (motionHipsHeight > 0 && vrmHipsHeight > 0) {
    hipsPositionScale = vrmHipsHeight / motionHipsHeight;
  }

  for (const track of clip.tracks) {
    const dot = track.name.indexOf(".");
    if (dot < 0) continue;
    const mixamoName = mixamoRigKey(track.name.slice(0, dot));
    const propertyName = track.name.slice(dot + 1);
    const vrmBoneName = MIXAMO_TO_VRM[mixamoName];
    if (!vrmBoneName) continue;

    const vrmNode = vrm.humanoid.getNormalizedBoneNode(vrmBoneName);
    if (!vrmNode) continue;

    const mixamoRigNode = mixamoNodes.get(mixamoName);
    if (!mixamoRigNode?.parent) continue;

    mixamoRigNode.getWorldQuaternion(restRotationInverse).invert();
    mixamoRigNode.parent.getWorldQuaternion(parentRestWorldRotation);

    if (track instanceof THREE.QuaternionKeyframeTrack) {
      const values = track.values.slice();
      for (let i = 0; i < values.length; i += 4) {
        quatA.fromArray(values, i);
        quatA.premultiply(parentRestWorldRotation).multiply(restRotationInverse);
        quatA.toArray(values, i);
      }
      const flipped = values.map((v, i) => (isVrm0 && i % 2 === 0 ? -v : v));
      tracks.push(
        new THREE.QuaternionKeyframeTrack(
          `${vrmNode.name}.${propertyName}`,
          track.times,
          flipped,
        ),
      );
    } else if (track instanceof THREE.VectorKeyframeTrack) {
      const values = track.values.map((v, i) => {
        const scaled = v * hipsPositionScale;
        return isVrm0 && i % 3 !== 1 ? -scaled : scaled;
      });
      tracks.push(
        new THREE.VectorKeyframeTrack(`${vrmNode.name}.${propertyName}`, track.times, values),
      );
    }
  }

  if (!tracks.length) return null;
  return new THREE.AnimationClip("mixamo_retarget", clip.duration, tracks);
}
