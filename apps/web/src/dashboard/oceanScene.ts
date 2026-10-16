// The hero scene (ADR-0076 §5, amended 2026-10-15): a cross-section of the sea. The camera sits
// just above the surface; a translucent "wall" of water a few units ahead shows the underwater
// half, so the Argo float is seen piercing the surface with its hull below. Vanilla three.js in
// its own async chunk. One wave function drives the surface, the wall's top edge and the float
// (GLSL and CPU twins), so they always agree. The float is the GLB under public/models, built
// by scripts/build-float-model.mjs; the sky is a shader with procedural clouds. The loop runs
// only while the hero is visible and the tab is in the foreground; under reduced motion a
// single frame is drawn.
import {
  ACESFilmicToneMapping,
  AmbientLight,
  BackSide,
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  CylinderGeometry,
  DirectionalLight,
  DoubleSide,
  Group,
  HemisphereLight,
  Line,
  LineDashedMaterial,
  Matrix4,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PMREMGenerator,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  PointsMaterial,
  RingGeometry,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  Vector3,
  Vector4,
  WebGLRenderer,
} from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

/** Four directional waves: amplitude, direction (x, z), wavelength and speed. */
const WAVES = [
  { amplitude: 0.11, direction: [1.0, 0.25], length: 7.5, speed: 1.0 },
  { amplitude: 0.06, direction: [0.35, 1.0], length: 4.2, speed: 1.35 },
  { amplitude: 0.035, direction: [-0.8, 0.6], length: 2.3, speed: 1.8 },
  { amplitude: 0.018, direction: [0.6, -0.9], length: 1.1, speed: 2.4 },
] as const;

/** Where the water wall stands (world z); the surface starts here and runs away from the camera. */
const WALL_Z = -4.3;
/** Waves are gentler near the wall, so the waterline stays steady under the copy. */
const DAMP_RANGE = 20;
const CAMERA_HEIGHT = 0.3;
const FOV = 40;
/** Where the float model is served from (copied from public/ by the build). */
const FLOAT_MODEL_URL = `${import.meta.env.BASE_URL}models/argo-float.glb`;

const PALETTE = {
  deep: "#0077b6",
  mid: "#0096c7",
  shallow: "#48cae4",
  sky: "#dff4fa",
  horizon: "#eef9fc",
  zenith: "#a9dcf1",
  sun: "#ffffff",
  underTop: "#0096c7",
  underMid: "#0077b6",
  underDeep: "#023e8a",
  underFloor: "#03045e",
} as const;

const WAVE_SET = WAVES.map((wave) => {
  const [dx, dz] = wave.direction;
  const norm = Math.hypot(dx, dz);
  return {
    amplitude: wave.amplitude,
    dirX: dx / norm,
    dirZ: dz / norm,
    k: (2 * Math.PI) / wave.length,
    w: wave.speed,
  };
});

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(Math.max((x - edge0) / (edge1 - edge0), 0), 1);
  return t * t * (3 - 2 * t);
}

/** Height and slope of the surface at world (x, z), the CPU twin of the GLSL `wave`. */
export function surfaceAt(x: number, z: number, t: number) {
  const damp = 0.5 + 0.5 * smoothstep(0, DAMP_RANGE, -z + WALL_Z);
  let height = 0;
  let dx = 0;
  let dz = 0;
  for (const wave of WAVE_SET) {
    const phase = (wave.dirX * x + wave.dirZ * z) * wave.k + t * wave.w;
    const amplitude = wave.amplitude * damp;
    const cos = Math.cos(phase) * amplitude * wave.k;
    height += Math.sin(phase) * amplitude;
    dx += cos * wave.dirX;
    dz += cos * wave.dirZ;
  }
  return { height, dx, dz };
}

const WAVE_GLSL = /* glsl */ `
  uniform float uTime;
  uniform vec4 uWaveA[4]; // amplitude, dirX, dirZ, k
  uniform float uWaveW[4];
  // Height and world-space slope (dh/dx, dh/dz) at world (x, z).
  vec3 wave(vec2 p) {
    float damp = 0.5 + 0.5 * smoothstep(0.0, ${DAMP_RANGE.toFixed(1)}, -p.y + (${WALL_Z.toFixed(1)}));
    float h = 0.0;
    float dx = 0.0;
    float dz = 0.0;
    for (int i = 0; i < 4; i++) {
      vec4 w = uWaveA[i];
      float phase = (w.y * p.x + w.z * p.y) * w.w + uTime * uWaveW[i];
      float a = w.x * damp;
      float c = cos(phase) * a * w.w;
      h += sin(phase) * a;
      dx += c * w.y;
      dz += c * w.z;
    }
    return vec3(h, dx, dz);
  }
`;

const NOISE_GLSL = /* glsl */ `
  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
  }
  float vnoise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
      f.y
    );
  }
  float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 5; i++) {
      v += a * vnoise(p);
      p = p * 2.03 + vec2(17.0, 9.0);
      a *= 0.5;
    }
    return v;
  }
`;

const SURFACE_VERTEX = /* glsl */ `
  ${WAVE_GLSL}
  varying vec3 vNormal;
  varying vec3 vWorld;
  varying float vHeight;
  void main() {
    vec4 flat_ = modelMatrix * vec4(position, 1.0);
    vec3 w = wave(flat_.xz);
    vec3 world = vec3(flat_.x, w.x, flat_.z);
    vHeight = w.x;
    vNormal = normalize(vec3(-w.y, 1.0, -w.z));
    vWorld = world;
    gl_Position = projectionMatrix * viewMatrix * vec4(world, 1.0);
  }
`;

const SURFACE_FRAGMENT = /* glsl */ `
  precision highp float;
  ${NOISE_GLSL}
  uniform float uTime;
  uniform vec3 uDeep;
  uniform vec3 uMid;
  uniform vec3 uShallow;
  uniform vec3 uSky;
  uniform vec3 uHorizon;
  uniform vec3 uSun;
  uniform vec3 uSunDir;
  uniform vec3 uCamera;
  uniform float uFogNear;
  uniform float uFogFar;
  varying vec3 vNormal;
  varying vec3 vWorld;
  varying float vHeight;
  void main() {
    // Fine ripples on top of the big waves, fading with distance so the horizon stays calm.
    float near = 1.0 - smoothstep(4.0, 30.0, distance(uCamera, vWorld));
    vec2 rp = vWorld.xz * 2.2 + vec2(uTime * 0.35, -uTime * 0.2);
    float r1 = vnoise(rp) - 0.5;
    float r2 = vnoise(rp * 2.7 + vec2(-uTime * 0.5, uTime * 0.3)) - 0.5;
    vec3 n = normalize(vNormal + vec3(r1 * 0.22, 0.0, r2 * 0.22) * near);
    vec3 v = normalize(uCamera - vWorld);
    // Crest-to-trough colouring, then the sky reflected at grazing angles.
    float crest = smoothstep(-0.16, 0.18, vHeight);
    vec3 water = mix(uDeep, uMid, crest);
    water = mix(water, uShallow, crest * crest * 0.75);
    float fresnel = pow(1.0 - max(dot(n, v), 0.0), 3.2);
    vec3 colour = mix(water, uSky, fresnel * 0.9);
    // Foam streaks on the crests.
    float streak = 0.55 + 0.45 * sin(vWorld.x * 6.0 + vWorld.z * 2.5 + uTime * 0.8);
    float foam = smoothstep(0.1, 0.2, vHeight) * streak;
    colour = mix(colour, vec3(1.0), foam * 0.75);
    // A tight sun glint and a broad sheen, clamped so they never blow out.
    vec3 h = normalize(uSunDir + v);
    float ndh = max(dot(n, h), 0.0);
    float glint = min(pow(ndh, 240.0) * 0.6 + pow(ndh, 24.0) * 0.08, 0.5);
    colour += uSun * glint;
    // Distance fog into the horizon so the plane's far edge is never seen.
    float dist = distance(uCamera, vWorld);
    float fog = smoothstep(uFogNear, uFogFar, dist);
    colour = mix(colour, uHorizon, fog);
    gl_FragColor = vec4(colour, 1.0);
  }
`;

const UNDERWATER_GLSL = /* glsl */ `
  uniform vec3 uUnderTop;
  uniform vec3 uUnderMid;
  uniform vec3 uUnderDeep;
  uniform vec3 uUnderFloor;
  vec3 underwater(float depth) {
    vec3 c = mix(uUnderTop, uUnderMid, smoothstep(0.0, 0.9, depth));
    c = mix(c, uUnderDeep, smoothstep(0.6, 3.2, depth));
    c = mix(c, uUnderFloor, smoothstep(3.0, 10.0, depth));
    return c;
  }
`;

const WALL_VERTEX = /* glsl */ `
  ${WAVE_GLSL}
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    // The top row follows the surface, a little above it, to hide the seam and draw the foam line.
    if (uv.y > 0.999) {
      world.y = wave(world.xz).x + 0.07;
    }
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const WALL_FRAGMENT = /* glsl */ `
  precision highp float;
  ${WAVE_GLSL}
  ${UNDERWATER_GLSL}
  ${NOISE_GLSL}
  varying vec3 vWorld;
  void main() {
    float surface = wave(vWorld.xz).x;
    float depth = max(surface - vWorld.y, 0.0);
    vec3 colour = underwater(depth);
    // Soft light shafts from the surface, fading with depth.
    float shaft = pow(max(sin(vWorld.x * 0.9 - depth * 0.22 + uTime * 0.18), 0.0), 9.0);
    shaft += pow(max(sin(vWorld.x * 1.7 + depth * 0.15 - uTime * 0.11), 0.0), 14.0) * 0.6;
    colour += vec3(0.55, 0.85, 1.0) * shaft * exp(-depth * 0.4) * 0.22;
    // Caustic shimmer just under the surface.
    float caustic = vnoise(vWorld.xz * 3.0 + vec2(uTime * 0.6, uTime * 0.4));
    caustic *= vnoise(vWorld.xz * 5.0 - vec2(uTime * 0.5, uTime * 0.7));
    colour += vec3(0.6, 0.9, 1.0) * pow(caustic, 2.0) * exp(-depth * 1.6) * 0.35;
    // The foam line where the wall meets the surface.
    float above = vWorld.y - surface;
    float edge = smoothstep(-0.06, 0.03, above);
    colour = mix(colour, vec3(1.0), edge * 0.9);
    float alpha = mix(0.6, 1.0, edge);
    gl_FragColor = vec4(colour, alpha);
  }
`;

const BACKDROP_VERTEX = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vec4 world = modelMatrix * vec4(position, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const BACKDROP_FRAGMENT = /* glsl */ `
  precision highp float;
  ${UNDERWATER_GLSL}
  varying vec3 vWorld;
  void main() {
    gl_FragColor = vec4(underwater(max(-vWorld.y, 0.0) * 0.8), 1.0);
  }
`;

/** The sky: a full-screen quad that traces a view ray per pixel into gradient, sun and
 * two layers of procedural clouds on planes above the camera. */
const SKY_VERTEX = /* glsl */ `
  varying vec2 vNdc;
  void main() {
    vNdc = position.xy;
    gl_Position = vec4(position.xy, 0.99999, 1.0);
  }
`;

const SKY_FRAGMENT = /* glsl */ `
  precision highp float;
  ${NOISE_GLSL}
  uniform mat4 uInvProj;
  uniform mat4 uCamWorld;
  uniform vec3 uCamera;
  uniform vec3 uSunDir;
  uniform vec3 uZenith;
  uniform vec3 uHorizon;
  uniform float uTime;
  varying vec2 vNdc;
  vec4 cloudLayer(vec3 dir, float height, float scale, float coverage, vec2 drift, float softness) {
    if (dir.y < 0.004) return vec4(0.0);
    float t = (height - uCamera.y) / dir.y;
    vec2 p = (uCamera.xz + dir.xz * t) * scale + drift * uTime;
    float n = fbm(p);
    float density = smoothstep(coverage, coverage + softness, n);
    // Lit side faces the sun; the underside is shaded.
    float lit = fbm(p + normalize(uSunDir.xz + vec2(0.001)) * 0.06);
    float shade = clamp(0.62 + (lit - n) * 3.5, 0.45, 1.0);
    vec3 colour = mix(vec3(0.70, 0.78, 0.88), vec3(1.0, 1.0, 1.0), shade);
    float fade = smoothstep(0.0, 0.14, dir.y);
    return vec4(colour, density * fade);
  }
  void main() {
    vec4 clip = vec4(vNdc, 1.0, 1.0);
    vec4 view = uInvProj * clip;
    view /= view.w;
    vec3 dir = normalize((uCamWorld * vec4(view.xyz, 0.0)).xyz);
    float e = dir.y;
    vec3 sky = mix(uHorizon, uZenith, smoothstep(0.0, 0.5, e));
    // Sun: a small disc and a wide haze.
    float s = max(dot(dir, uSunDir), 0.0);
    sky += vec3(1.0, 0.98, 0.92) * (pow(s, 700.0) * 0.9 + pow(s, 10.0) * 0.12);
    vec4 high = cloudLayer(dir, 160.0, 0.0045, 0.56, vec2(0.004, 0.0015), 0.34);
    sky = mix(sky, high.rgb, high.a * 0.85);
    vec4 low = cloudLayer(dir, 70.0, 0.011, 0.5, vec2(0.009, 0.003), 0.3);
    sky = mix(sky, low.rgb, low.a * 0.96);
    gl_FragColor = vec4(sky, 1.0);
  }
`;

const ENV_VERTEX = /* glsl */ `
  varying vec3 vWorld;
  void main() {
    vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
    gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
  }
`;

const ENV_FRAGMENT = /* glsl */ `
  precision highp float;
  uniform vec3 uSunDir;
  varying vec3 vWorld;
  void main() {
    vec3 d = normalize(vWorld);
    float e = d.y;
    vec3 sky = mix(vec3(0.93, 0.97, 0.99), vec3(0.55, 0.78, 0.92), smoothstep(0.0, 0.6, e));
    vec3 sea = mix(vec3(0.0, 0.45, 0.65), vec3(0.0, 0.12, 0.32), smoothstep(0.0, -0.6, e));
    vec3 c = e > 0.0 ? sky : sea;
    c += vec3(1.0, 0.97, 0.9) * pow(max(dot(d, uSunDir), 0.0), 200.0) * 3.0;
    gl_FragColor = vec4(c, 1.0);
  }
`;

/** A placeholder hull from primitives, used only if the model cannot be loaded. */
function makeFallbackFloat(): { group: Group; tip: Object3D } {
  const group = new Group();
  const hull = new MeshStandardMaterial({ color: "#f2b61f", roughness: 0.5 });
  const dark = new MeshStandardMaterial({ color: "#15181f", roughness: 0.5 });
  const body = new Mesh(new CylinderGeometry(0.21, 0.21, 2.3, 32), hull);
  const cap = new Mesh(new CylinderGeometry(0.17, 0.2, 0.25, 32), dark);
  cap.position.y = 1.2;
  const antenna = new Mesh(new CylinderGeometry(0.012, 0.012, 1.05, 10), dark);
  antenna.position.y = 1.9;
  const tip = new Mesh(new SphereGeometry(0.02, 12, 8), dark);
  tip.position.y = 2.45;
  group.add(body, cap, antenna, tip);
  return { group, tip };
}

/** A stylised satellite from primitives: a body, two panels and a dish facing the sea. */
function makeSatellite(): Group {
  const group = new Group();
  const shell = new MeshStandardMaterial({
    color: "#d8e1ea",
    roughness: 0.4,
    metalness: 0.4,
  });
  const panel = new MeshStandardMaterial({
    color: "#4f7fb0",
    roughness: 0.3,
    metalness: 0.4,
  });
  const body = new Mesh(new BoxGeometry(0.5, 0.5, 0.7), shell);
  const left = new Mesh(new BoxGeometry(1.5, 0.02, 0.55), panel);
  left.position.x = -1.15;
  const right = new Mesh(new BoxGeometry(1.5, 0.02, 0.55), panel);
  right.position.x = 1.15;
  const boom = new Mesh(new BoxGeometry(2.4, 0.03, 0.03), shell);
  const dish = new Mesh(
    new CylinderGeometry(0.02, 0.26, 0.18, 20, 1, true),
    shell,
  );
  dish.position.y = -0.42;
  group.add(body, left, right, boom, dish);
  return group;
}

/** The surfacing intro: seconds of scene time after the model is ready before the float
 * breaks the surface. */
const INTRO_DELAY = 0.2;
const INTRO_SECONDS = 2.6;
const INTRO_DEPTH = 3.2;
/** Uplink timing: pulses travel for a while, then the link is quiet, like a report being sent. */
const UPLINK_PERIOD = 6.5;
const UPLINK_ACTIVE = 3.2;
const PULSES = 3;
const BUBBLES = 320;
const FLOAT_SCALE = 0.85;

export type OceanSceneOptions = {
  /** Draw one frame and stop. */
  still: boolean;
  /** The copy block; the waterline is measured under its centre for the two-tone text. */
  copy?: HTMLElement | null;
  /** Where the waterline crosses the frame under the copy, as a fraction from the top. */
  onWaterline?: (fraction: number) => void;
  /** Called once the first frame has been drawn. */
  onReady?: () => void;
};

/** Mounts the scene into `container` and returns its disposer. */
export function mountOceanScene(
  container: HTMLElement,
  options: OceanSceneOptions,
): () => void {
  const disposers: Array<() => void> = [];
  const renderer = new WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping = ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);

  const scene = new Scene();
  const camera = new PerspectiveCamera(FOV, 1, 0.1, 400);
  camera.position.set(0, CAMERA_HEIGHT, 0);
  let pitch = 10;
  const target = new Vector3();
  const aim = () => {
    target.set(0, CAMERA_HEIGHT - 10 * Math.tan((pitch * Math.PI) / 180), -10);
    camera.lookAt(target);
    camera.updateMatrixWorld();
  };
  aim();

  const sunDir = new Vector3(0.4, 0.5, -1).normalize();
  const waveUniforms = {
    uTime: { value: 0 },
    uWaveA: {
      value: WAVE_SET.map(
        (wave) => new Vector4(wave.amplitude, wave.dirX, wave.dirZ, wave.k),
      ),
    },
    uWaveW: { value: WAVE_SET.map((wave) => wave.w) },
  };
  const underwaterUniforms = {
    uUnderTop: { value: new Color(PALETTE.underTop) },
    uUnderMid: { value: new Color(PALETTE.underMid) },
    uUnderDeep: { value: new Color(PALETTE.underDeep) },
    uUnderFloor: { value: new Color(PALETTE.underFloor) },
  };

  // Image-based lighting from a sky-over-sea gradient, prefiltered once.
  const envScene = new Scene();
  const envMaterial = new ShaderMaterial({
    side: BackSide,
    uniforms: { uSunDir: { value: sunDir } },
    vertexShader: ENV_VERTEX,
    fragmentShader: ENV_FRAGMENT,
  });
  const envGeometry = new SphereGeometry(50, 32, 16);
  envScene.add(new Mesh(envGeometry, envMaterial));
  const pmrem = new PMREMGenerator(renderer);
  const environment = pmrem.fromScene(envScene, 0.04).texture;
  scene.environment = environment;
  pmrem.dispose();
  envGeometry.dispose();
  envMaterial.dispose();

  // The sky, drawn first behind everything.
  const skyGeometry = new PlaneGeometry(2, 2);
  const skyMaterial = new ShaderMaterial({
    uniforms: {
      uInvProj: { value: new Matrix4() },
      uCamWorld: { value: new Matrix4() },
      uCamera: { value: camera.position },
      uSunDir: { value: sunDir },
      uZenith: { value: new Color(PALETTE.zenith) },
      uHorizon: { value: new Color(PALETTE.horizon) },
      uTime: waveUniforms.uTime,
    },
    vertexShader: SKY_VERTEX,
    fragmentShader: SKY_FRAGMENT,
    depthWrite: false,
    depthTest: false,
  });
  const sky = new Mesh(skyGeometry, skyMaterial);
  sky.renderOrder = -1;
  sky.frustumCulled = false;
  scene.add(sky);

  // The backdrop: an opaque gradient far behind everything under the water.
  const backdropGeometry = new PlaneGeometry(400, 80);
  const backdropMaterial = new ShaderMaterial({
    uniforms: underwaterUniforms,
    vertexShader: BACKDROP_VERTEX,
    fragmentShader: BACKDROP_FRAGMENT,
  });
  const backdrop = new Mesh(backdropGeometry, backdropMaterial);
  backdrop.position.set(0, -40.6, -70);
  backdrop.renderOrder = 0;
  scene.add(backdrop);

  // Bubbles rising through the water, kept below the surface.
  const bubbleGeometry = new BufferGeometry();
  const bubblePositions = new Float32Array(BUBBLES * 3);
  const bubbleSpeeds = new Float32Array(BUBBLES);
  for (let i = 0; i < BUBBLES; i += 1) {
    bubblePositions[i * 3] = (Math.random() - 0.5) * 20;
    bubblePositions[i * 3 + 1] = -0.5 - Math.random() * 9.5;
    bubblePositions[i * 3 + 2] = WALL_Z - 0.3 - Math.random() * 10;
    bubbleSpeeds[i] = 0.12 + Math.random() * 0.25;
  }
  bubbleGeometry.setAttribute(
    "position",
    new BufferAttribute(bubblePositions, 3),
  );
  const bubbleMaterial = new PointsMaterial({
    color: "#d8f3fb",
    size: 0.07,
    transparent: true,
    opacity: 0.65,
    depthWrite: false,
    sizeAttenuation: true,
  });
  const bubbles = new Points(bubbleGeometry, bubbleMaterial);
  bubbles.renderOrder = 1;
  bubbles.frustumCulled = false;
  scene.add(bubbles);

  // The float: the GLB model, with a primitive stand-in only if the load fails.
  const floatModel = new Group();
  let tip: Object3D | null = null;
  let floatX = -1.7;
  let floatZ = WALL_Z - 1.7;
  const floatLean = 0.2;
  floatModel.position.set(floatX, -INTRO_DEPTH, floatZ);
  floatModel.rotation.set(0, 0.4, floatLean);
  floatModel.scale.setScalar(FLOAT_SCALE);
  floatModel.visible = false;
  floatModel.renderOrder = 2;
  scene.add(floatModel);
  /** Scene time at which the model became available; the intro counts from here. */
  let floatReadyAt: number | null = null;
  let disposed = false;
  const attachFloat = (model: Object3D, antennaTip: Object3D) => {
    if (disposed) return;
    floatModel.add(model);
    tip = antennaTip;
    floatModel.visible = true;
    floatReadyAt = options.still ? 0 : null;
  };
  new GLTFLoader().loadAsync(FLOAT_MODEL_URL).then(
    (gltf) => {
      const antennaTip = gltf.scene.getObjectByName("antenna-tip");
      attachFloat(gltf.scene, antennaTip ?? gltf.scene);
    },
    () => {
      const fallback = makeFallbackFloat();
      attachFloat(fallback.group, fallback.tip);
    },
  );
  const collarGeometry = new RingGeometry(0.3, 0.66, 40);
  const collarMaterial = new MeshStandardMaterial({
    color: "#ffffff",
    roughness: 0.9,
    transparent: true,
    opacity: 0.85,
    side: DoubleSide,
    depthWrite: false,
  });
  const collar = new Mesh(collarGeometry, collarMaterial);
  collar.renderOrder = 4;
  collar.visible = false;
  scene.add(collar);

  // The surface, starting at the wall and running to the horizon.
  const surfaceGeometry = new PlaneGeometry(160, 100, 160, 110);
  const surfaceMaterial = new ShaderMaterial({
    uniforms: {
      ...waveUniforms,
      uDeep: { value: new Color(PALETTE.deep) },
      uMid: { value: new Color(PALETTE.mid) },
      uShallow: { value: new Color(PALETTE.shallow) },
      uSky: { value: new Color(PALETTE.sky) },
      uHorizon: { value: new Color(PALETTE.horizon) },
      uSun: { value: new Color(PALETTE.sun) },
      uSunDir: { value: sunDir },
      uCamera: { value: camera.position },
      uFogNear: { value: 18 },
      uFogFar: { value: 85 },
    },
    vertexShader: SURFACE_VERTEX,
    fragmentShader: SURFACE_FRAGMENT,
  });
  const surface = new Mesh(surfaceGeometry, surfaceMaterial);
  surface.rotation.x = -Math.PI / 2;
  surface.position.set(0, 0, WALL_Z - 50);
  surface.renderOrder = 3;
  surface.frustumCulled = false;
  scene.add(surface);

  // The water wall: everything below the waterline is seen through it.
  const wallGeometry = new PlaneGeometry(60, 16, 240, 1);
  const wallMaterial = new ShaderMaterial({
    uniforms: { ...waveUniforms, ...underwaterUniforms },
    vertexShader: WALL_VERTEX,
    fragmentShader: WALL_FRAGMENT,
    transparent: true,
    depthWrite: false,
  });
  const wall = new Mesh(wallGeometry, wallMaterial);
  wall.position.set(0, -8, WALL_Z);
  wall.renderOrder = 5;
  wall.frustumCulled = false;
  scene.add(wall);

  // The satellite the float reports to: small and far, high in the sky band.
  const satellite = makeSatellite();
  satellite.scale.setScalar(0.3);
  let satelliteY = 6.6;
  satellite.position.set(8, satelliteY, -60);
  satellite.rotation.set(0.35, 0.3, 0.08);
  scene.add(satellite);
  const tipWorld = new Vector3();
  const satWorld = new Vector3();
  const uplinkGeometry = new BufferGeometry();
  uplinkGeometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array(6), 3),
  );
  const uplinkMaterial = new LineDashedMaterial({
    color: "#0096c7",
    dashSize: 0.3,
    gapSize: 0.25,
    transparent: true,
    opacity: 0.22,
    depthWrite: false,
  });
  const uplink = new Line(uplinkGeometry, uplinkMaterial);
  uplink.frustumCulled = false;
  uplink.visible = false;
  scene.add(uplink);
  const pulseMaterial = new MeshStandardMaterial({
    color: "#ffffff",
    emissive: "#9ad8ec",
    emissiveIntensity: 2,
    transparent: true,
    opacity: 1,
    depthWrite: false,
  });
  const pulses = Array.from({ length: PULSES }, () => {
    const pulse = new Mesh(new SphereGeometry(0.09, 10, 8), pulseMaterial);
    pulse.visible = false;
    scene.add(pulse);
    return pulse;
  });
  const updateUplink = (sinceSurfaced: number) => {
    if (!tip) return;
    tip.getWorldPosition(tipWorld);
    satellite.getWorldPosition(satWorld);
    const positions = uplinkGeometry.attributes.position as BufferAttribute;
    positions.setXYZ(0, tipWorld.x, tipWorld.y, tipWorld.z);
    positions.setXYZ(1, satWorld.x, satWorld.y, satWorld.z);
    positions.needsUpdate = true;
    uplinkGeometry.computeBoundingSphere();
    uplink.computeLineDistances();
    // The link appears once the float has surfaced, then pulses leave the antenna in short
    // bursts.
    uplink.visible = options.still || sinceSurfaced >= 0;
    uplinkMaterial.opacity = options.still
      ? 0.22
      : Math.min(Math.max(sinceSurfaced / 1.2, 0), 1) * 0.22;
    const phase = sinceSurfaced >= 0 ? sinceSurfaced % UPLINK_PERIOD : -1;
    pulses.forEach((pulse, index) => {
      const local = phase - index * 0.55;
      const active = options.still
        ? false
        : local >= 0 && local < UPLINK_ACTIVE;
      pulse.visible = active;
      if (!active) return;
      const k = local / UPLINK_ACTIVE;
      pulse.position.lerpVectors(tipWorld, satWorld, k);
      pulse.scale.setScalar(1 - k * 0.6);
    });
  };

  const sun = new DirectionalLight("#fff6e8", 2.2);
  const placeSun = () => {
    sun.position
      .copy(sunDir)
      .multiplyScalar(14)
      .add(new Vector3(floatX, 0, floatZ));
    sun.target.position.set(floatX, 0, floatZ);
  };
  placeSun();
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.camera.left = -2.5;
  sun.shadow.camera.right = 2.5;
  sun.shadow.camera.top = 3;
  sun.shadow.camera.bottom = -3;
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 40;
  sun.shadow.bias = -0.0005;
  scene.add(sun, sun.target);
  scene.add(new HemisphereLight("#eaf8fc", "#0077b6", 0.7));
  scene.add(new AmbientLight("#ffffff", 0.25));

  let width = 0;
  let height = 0;
  let copyCentre = 0.75;
  const resize = () => {
    const next = container.getBoundingClientRect();
    const block = options.copy?.getBoundingClientRect();
    if (block && next.width > 0)
      copyCentre = (block.left + block.width / 2 - next.left) / next.width;
    if (next.width === width && next.height === height) return;
    width = Math.max(1, next.width);
    height = Math.max(1, next.height);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const narrow = camera.aspect < 0.9;
    // A low pitch keeps the whole float and plenty of sky in view; the copy is coloured by
    // which side of the waterline it falls on, so it may cross it.
    pitch = narrow ? 7 : 6;
    aim();
    // The float sits left of centre; nearer the middle on phones where the view is narrow.
    floatX = narrow ? -0.5 : camera.aspect < 1.4 ? -1.3 : -1.7;
    floatZ = narrow ? WALL_Z - 3.6 : WALL_Z - 1.7;
    floatModel.position.set(floatX, floatModel.position.y, floatZ);
    placeSun();
    satellite.position.x = narrow ? 2.5 : 8;
    // The satellite sits about a third of the way from the horizon to the top of the frame.
    const horizon = 0.5 - pitch / FOV;
    const elevation = 0.35 * horizon * FOV * (Math.PI / 180);
    satelliteY = CAMERA_HEIGHT + 60 * Math.tan(elevation);
  };
  resize();

  // The screen position of the foam line under the copy, for the two-tone text.
  const probe = new Vector3();
  let lastWaterline = -1;
  const reportWaterline = (t: number) => {
    if (!options.onWaterline) return;
    probe
      .set(copyCentre * 2 - 1, 0, 0.5)
      .unproject(camera)
      .sub(camera.position);
    if (probe.z >= 0) return;
    const along = (WALL_Z - camera.position.z) / probe.z;
    const x = camera.position.x + probe.x * along;
    const surfaceLine = surfaceAt(x, WALL_Z, t).height + 0.07;
    probe.set(x, surfaceLine, WALL_Z).project(camera);
    const fraction = Math.min(Math.max((1 - probe.y) / 2, 0), 1);
    if (Math.abs(fraction - lastWaterline) < 0.0005) return;
    lastWaterline = fraction;
    options.onWaterline(fraction);
  };

  let frame = 0;
  let visible = true;
  let started = performance.now();
  let paused = performance.now();
  let lastElapsed = 0;
  const timeOffset = 2.4;
  let ready = false;

  const draw = (elapsed: number) => {
    const dt = Math.min(Math.max(elapsed - lastElapsed, 0), 0.1);
    lastElapsed = elapsed;
    const t = elapsed * 0.72 + timeOffset;
    waveUniforms.uTime.value = t;
    skyMaterial.uniforms.uInvProj.value.copy(camera.projectionMatrixInverse);
    skyMaterial.uniforms.uCamWorld.value.copy(camera.matrixWorld);
    // The float follows the surface: height from the same waves, tilt from the slope, with
    // a little lag so it reads as a heavy body rather than a cork.
    const surfaceHere = surfaceAt(floatX, floatZ, t);
    const restY = surfaceHere.height - 0.47;
    if (floatModel.visible && floatReadyAt === null) floatReadyAt = elapsed;
    // It surfaces over the first seconds after the model is ready (scene time, so a paused
    // loop never replays it); the still frame shows it settled.
    const intro = options.still
      ? 1
      : floatReadyAt === null
        ? 0
        : Math.min(
            Math.max((elapsed - floatReadyAt - INTRO_DELAY) / INTRO_SECONDS, 0),
            1,
          );
    const risen = 1 - Math.pow(1 - intro, 3);
    const ease = 1 - Math.exp(-dt * 6);
    const settle = 1 - Math.exp(-dt * 3.5);
    if (intro < 1) {
      floatModel.position.y = restY - (1 - risen) * INTRO_DEPTH;
    } else {
      floatModel.position.y += (restY - floatModel.position.y) * ease;
    }
    floatModel.rotation.z +=
      (floatLean + surfaceHere.dx * 0.9 - floatModel.rotation.z) * settle;
    floatModel.rotation.x +=
      (-surfaceHere.dz * 0.9 - floatModel.rotation.x) * settle;
    floatModel.rotation.y = 0.4 + Math.sin(t * 0.11) * 0.08;
    // The collar rides the surface around the hull once it is up.
    collar.visible = floatModel.visible && intro > 0.85;
    collar.position.set(floatX, surfaceHere.height + 0.015, floatZ);
    collar.lookAt(
      floatX - surfaceHere.dx,
      surfaceHere.height + 1.015,
      floatZ - surfaceHere.dz,
    );
    collarMaterial.opacity = 0.85 * Math.min((intro - 0.85) / 0.15, 1);
    // Bubbles rise and wrap below the surface.
    for (let i = 0; i < BUBBLES; i += 1) {
      let y = bubblePositions[i * 3 + 1] + bubbleSpeeds[i] * dt;
      if (y > -0.45) y = -10;
      bubblePositions[i * 3 + 1] = y;
    }
    (bubbleGeometry.attributes.position as BufferAttribute).needsUpdate = true;
    satellite.rotation.y = 0.3 + Math.sin(t * 0.05) * 0.25;
    satellite.position.y = satelliteY + Math.sin(t * 0.07) * 0.15;
    floatModel.updateMatrixWorld();
    satellite.updateMatrixWorld();
    const sinceSurfaced =
      floatReadyAt === null
        ? -1
        : options.still
          ? 1
          : elapsed - floatReadyAt - INTRO_DELAY - INTRO_SECONDS;
    updateUplink(sinceSurfaced);
    renderer.render(scene, camera);
    reportWaterline(t);
    if (!ready) {
      ready = true;
      options.onReady?.();
    }
  };

  const loop = (now: number) => {
    frame = 0;
    if (!visible || document.hidden) return;
    resize();
    draw((now - started) / 1000);
    frame = requestAnimationFrame(loop);
  };
  const resume = () => {
    if (frame || options.still || !visible || document.hidden) return;
    started += performance.now() - paused;
    frame = requestAnimationFrame(loop);
  };
  const pause = () => {
    if (!frame) return;
    cancelAnimationFrame(frame);
    frame = 0;
    paused = performance.now();
  };

  const observer =
    typeof IntersectionObserver === "function"
      ? new IntersectionObserver(
          (entries) => {
            visible = entries.some((entry) => entry.isIntersecting);
            if (visible) resume();
            else pause();
          },
          { threshold: 0.05 },
        )
      : null;
  observer?.observe(container);
  const onVisibility = () => {
    if (document.hidden) pause();
    else resume();
  };
  document.addEventListener("visibilitychange", onVisibility);
  // A dozen settling steps are enough for the float to come to rest on the single frame.
  const stillFrame = () => {
    for (let i = 0; i < 12; i += 1) draw(1.2 + i * 0.1);
    draw(3.2);
  };
  const resizeObserver =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
          resize();
          if (options.still) draw(3.2);
        })
      : null;
  resizeObserver?.observe(container);
  if (options.copy) resizeObserver?.observe(options.copy);

  if (options.still) {
    // Settle the float on the surface before the single frame; again once the model lands.
    stillFrame();
    const settleWhenLoaded = setInterval(() => {
      if (!floatModel.visible) return;
      clearInterval(settleWhenLoaded);
      stillFrame();
    }, 100);
    const stopWaiting = setTimeout(
      () => clearInterval(settleWhenLoaded),
      15000,
    );
    disposers.push(() => {
      clearInterval(settleWhenLoaded);
      clearTimeout(stopWaiting);
    });
  } else {
    paused = started = performance.now();
    frame = requestAnimationFrame(loop);
  }

  return () => {
    disposed = true;
    pause();
    disposers.forEach((fn) => fn());
    observer?.disconnect();
    resizeObserver?.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    [floatModel, satellite].forEach((group) =>
      group.traverse((object) => {
        if (object instanceof Mesh) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material)
            ? object.material
            : [object.material];
          materials.forEach((material) => {
            (material as MeshStandardMaterial).map?.dispose();
            material.dispose();
          });
        }
      }),
    );
    pulses.forEach((pulse) => pulse.geometry.dispose());
    pulseMaterial.dispose();
    uplinkGeometry.dispose();
    uplinkMaterial.dispose();
    [
      skyGeometry,
      backdropGeometry,
      bubbleGeometry,
      collarGeometry,
      surfaceGeometry,
      wallGeometry,
    ].forEach((geometry) => geometry.dispose());
    [
      skyMaterial,
      backdropMaterial,
      bubbleMaterial,
      collarMaterial,
      surfaceMaterial,
      wallMaterial,
    ].forEach((material) => material.dispose());
    environment.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
  };
}
