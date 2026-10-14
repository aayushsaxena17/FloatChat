// The hero scene: an Argo float riding a sunlit sea. Vanilla three.js in its own async chunk
// (ADR-0076); the ocean is one displaced plane with a fragment shader, the float a handful of
// primitives. The same wave function runs in the vertex shader and on the CPU so the float
// sits on the surface it is drawn on. The loop runs only while the hero is visible and the
// tab is in the foreground; under reduced motion a single frame is drawn.
import {
  AmbientLight,
  CylinderGeometry,
  DirectionalLight,
  Group,
  HemisphereLight,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  Color,
  Vector3,
  Vector4,
  WebGLRenderer,
} from "three";

/** Four directional waves: amplitude, direction (x, z), wavelength and speed. */
const WAVES = [
  { amplitude: 0.16, direction: [1.0, 0.25], length: 7.5, speed: 1.0 },
  { amplitude: 0.09, direction: [0.35, 1.0], length: 4.2, speed: 1.35 },
  { amplitude: 0.05, direction: [-0.8, 0.6], length: 2.3, speed: 1.8 },
  { amplitude: 0.025, direction: [0.6, -0.9], length: 1.1, speed: 2.4 },
] as const;

const PALETTE = {
  deep: "#0077b6",
  mid: "#0096c7",
  shallow: "#48cae4",
  sky: "#dff4fa",
  horizon: "#eef9fc",
  sun: "#ffffff",
} as const;

function waveUniforms() {
  return WAVES.map((wave) => {
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
}

const WAVE_SET = waveUniforms();

/** Height and slope of the surface at (x, z), the CPU twin of the vertex shader. */
export function surfaceAt(x: number, z: number, t: number) {
  let height = 0;
  let dx = 0;
  let dz = 0;
  for (const wave of WAVE_SET) {
    const phase = (wave.dirX * x + wave.dirZ * z) * wave.k + t * wave.w;
    const cos = Math.cos(phase) * wave.amplitude * wave.k;
    height += Math.sin(phase) * wave.amplitude;
    dx += cos * wave.dirX;
    dz += cos * wave.dirZ;
  }
  return { height, dx, dz };
}

const VERTEX = /* glsl */ `
  uniform float uTime;
  uniform vec4 uWaveA[4]; // amplitude, dirX, dirZ, k
  uniform float uWaveW[4];
  varying vec3 vNormal;
  varying vec3 vWorld;
  varying float vHeight;
  void main() {
    vec3 p = position;
    float h = 0.0;
    float dx = 0.0;
    float dz = 0.0;
    for (int i = 0; i < 4; i++) {
      vec4 w = uWaveA[i];
      float phase = (w.y * p.x + w.z * p.y) * w.w + uTime * uWaveW[i];
      float c = cos(phase) * w.x * w.w;
      h += sin(phase) * w.x;
      dx += c * w.y;
      dz += c * w.z;
    }
    // The plane lies flat: its local y is world z, its local z is world y (height).
    vec3 displaced = vec3(p.x, p.y, h);
    vec3 n = normalize(vec3(-dx, -dz, 1.0));
    vHeight = h;
    // World-space normal (the model transform is a rotation and a translation only), so it
    // matches the world-space view and sun vectors in the fragment shader.
    vNormal = normalize(mat3(modelMatrix) * n);
    vec4 world = modelMatrix * vec4(displaced, 1.0);
    vWorld = world.xyz;
    gl_Position = projectionMatrix * viewMatrix * world;
  }
`;

const FRAGMENT = /* glsl */ `
  precision highp float;
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
    vec3 n = normalize(vNormal);
    vec3 v = normalize(uCamera - vWorld);
    // Crest-to-trough colouring, then the sky reflected at grazing angles.
    float crest = smoothstep(-0.22, 0.26, vHeight);
    vec3 water = mix(uDeep, uMid, crest);
    water = mix(water, uShallow, crest * crest * 0.75);
    float fresnel = pow(1.0 - max(dot(n, v), 0.0), 3.2);
    vec3 colour = mix(water, uSky, fresnel * 0.9);
    // Two specular lobes: a tight sun glint and a broad sheen.
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

function makeFloat(): Group {
  const group = new Group();
  const hull = new MeshStandardMaterial({
    color: "#f4f6f8",
    roughness: 0.55,
    metalness: 0.05,
  });
  const navy = new MeshStandardMaterial({
    color: "#03045e",
    roughness: 0.6,
    metalness: 0.1,
  });
  const band = new MeshStandardMaterial({
    color: "#0077b6",
    roughness: 0.5,
  });
  const body = new Mesh(new CylinderGeometry(0.2, 0.2, 1.5, 28), hull);
  body.position.y = -0.3;
  const stripe = new Mesh(new CylinderGeometry(0.205, 0.205, 0.08, 28), band);
  stripe.position.y = 0.22;
  const cap = new Mesh(new CylinderGeometry(0.17, 0.2, 0.2, 28), navy);
  cap.position.y = 0.55;
  const dome = new Mesh(new SphereGeometry(0.17, 24, 14), navy);
  dome.scale.y = 0.45;
  dome.position.y = 0.65;
  const antenna = new Mesh(new CylinderGeometry(0.012, 0.012, 0.95, 10), navy);
  antenna.position.y = 1.1;
  const tip = new Mesh(new SphereGeometry(0.03, 12, 8), navy);
  tip.position.y = 1.58;
  group.add(body, stripe, cap, dome, antenna, tip);
  return group;
}

export type OceanSceneOptions = {
  /** Draw one frame and stop. */
  still: boolean;
  /** Called once the first frame has been drawn. */
  onReady?: () => void;
};

/** Mounts the scene into `container` and returns its disposer. */
export function mountOceanScene(
  container: HTMLElement,
  options: OceanSceneOptions,
): () => void {
  const renderer = new WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  const scene = new Scene();
  const camera = new PerspectiveCamera(38, 1, 0.1, 80);
  // Pitched a few degrees down so the horizon sits just above the middle of the frame.
  camera.position.set(0, 2.1, 8.5);
  const target = new Vector3(0.6, 1.5, 0);
  camera.lookAt(target);

  const sunDir = new Vector3(0.55, 0.42, -1).normalize();
  const uniforms = {
    uTime: { value: 0 },
    uWaveA: {
      value: WAVE_SET.map(
        (wave) => new Vector4(wave.amplitude, wave.dirX, wave.dirZ, wave.k),
      ),
    },
    uWaveW: { value: WAVE_SET.map((wave) => wave.w) },
    uDeep: { value: new Color(PALETTE.deep) },
    uMid: { value: new Color(PALETTE.mid) },
    uShallow: { value: new Color(PALETTE.shallow) },
    uSky: { value: new Color(PALETTE.sky) },
    uHorizon: { value: new Color(PALETTE.horizon) },
    uSun: { value: new Color(PALETTE.sun) },
    uSunDir: { value: sunDir },
    uCamera: { value: camera.position },
    uFogNear: { value: 14 },
    uFogFar: { value: 46 },
  };
  const waterGeometry = new PlaneGeometry(90, 70, 150, 110);
  const waterMaterial = new ShaderMaterial({
    uniforms,
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
  });
  const water = new Mesh(waterGeometry, waterMaterial);
  water.rotation.x = -Math.PI / 2;
  water.position.z = -20;
  scene.add(water);

  const floatModel = makeFloat();
  // Right of centre on wide frames, nearer the middle on phones.
  let floatX = 2.9;
  const floatZ = 2.6;
  floatModel.position.set(floatX, 0, floatZ);
  floatModel.rotation.y = 0.4;
  scene.add(floatModel);

  const sun = new DirectionalLight("#ffffff", 2.6);
  sun.position.copy(sunDir).multiplyScalar(20);
  scene.add(sun);
  scene.add(new HemisphereLight("#eaf8fc", "#0077b6", 1.1));
  scene.add(new AmbientLight("#ffffff", 0.35));

  let width = 0;
  let height = 0;
  const resize = () => {
    const next = container.getBoundingClientRect();
    if (next.width === width && next.height === height) return;
    width = Math.max(1, next.width);
    height = Math.max(1, next.height);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    camera.lookAt(target);
    floatX = camera.aspect < 0.9 ? 0.7 : camera.aspect < 1.4 ? 1.9 : 2.9;
    floatModel.position.x = floatX;
  };
  resize();

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
    uniforms.uTime.value = t;
    // The float follows the surface: height from the same waves, tilt from the slope, with
    // a little lag so it reads as a heavy body rather than a cork. The plane is rotated
    // -90 degrees about x and pushed back, so plane-local y is -(world z + 20) and the
    // local y slope points along -z in the world.
    const surface = surfaceAt(floatX, -(floatZ + 20), t);
    const slopeX = surface.dx;
    const slopeZ = -surface.dz;
    const ease = 1 - Math.exp(-dt * 6);
    const settle = 1 - Math.exp(-dt * 3.5);
    floatModel.position.y +=
      (surface.height - 0.08 - floatModel.position.y) * ease;
    floatModel.rotation.z += (slopeX * 0.9 - floatModel.rotation.z) * settle;
    floatModel.rotation.x += (-slopeZ * 0.9 - floatModel.rotation.x) * settle;
    floatModel.rotation.y = 0.4 + Math.sin(t * 0.11) * 0.08;
    renderer.render(scene, camera);
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
  const resizeObserver =
    typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
          resize();
          if (options.still) draw(3.2);
        })
      : null;
  resizeObserver?.observe(container);

  if (options.still) {
    // Settle the float on the surface before the single frame.
    for (let i = 0; i < 40; i += 1) draw(1.2 + i * 0.05);
    draw(3.2);
  } else {
    paused = started = performance.now();
    frame = requestAnimationFrame(loop);
  }

  return () => {
    pause();
    observer?.disconnect();
    resizeObserver?.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    waterGeometry.dispose();
    waterMaterial.dispose();
    floatModel.traverse((object) => {
      if (object instanceof Mesh) {
        object.geometry.dispose();
        (object.material as MeshStandardMaterial).dispose();
      }
    });
    renderer.dispose();
    renderer.forceContextLoss();
    renderer.domElement.remove();
  };
}
